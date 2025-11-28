import threading
import time
from typing import Dict, List, Optional, Callable, Tuple
from datetime import datetime, timedelta, timezone
import requests
from zoneinfo import ZoneInfo
import math
from json import load


from bby.models.BbyCfg import BBYConfig
from bby.models.Aircraft import Aircraft, OpenSkyData, FlightAwareData
from opensky_api import OpenSkyApi
from bby.api.DumpSlurp import DumpSlurp
# from bby.models.Position import Position

# Hybrid API driver
# Loads initial results from low-cost, low data API
# Loads supplemental information per-aircraft from higher cost
# Initializes with a home location ( lat / lng pair ) and uses this to poll for aircraft within a provided radius
# Low Cost: Use OpenSky api to load nearby aircraft ( refresh once every 30 seconds? ) ( documentation: https://openskynetwork.github.io/opensky-api/python.html )
# Supplemental: use FlightAware AeroApi to load supplemental information ( Airline, flight number, origin/dest airport, estimated time ) ( documentation: use the position call on https://www.flightaware.com/aeroapi/portal/#get-/flights/-id-/position )
# Ideally provides some observable stream of "current aircraft" and automatically manages loading extra information once per new aircraft, with appropriate error handling

# Add parent directory to path to import models
# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))



class HybridAPI:
    """
    Hybrid API driver that combines OpenSky (free/low-cost) and FlightAware (paid) data.
    Provides a stream of aircraft with automatic supplemental data loading.
    """

    def __init__(self, config: BBYConfig):
        self.config = config
        self.home = config.home.position
        self.bbox = self.calculate_bounding_box()

        # Initialize OpenSky API (if not using dump1090 exclusively)
        self.opensky_api = None
        if not config.api.use_dump1090_only:
            self.opensky_api = OpenSkyApi(
                # username=config.api.opensky_username,
                # password=config.api.opensky_password,
                client_id=config.api.opensky_client_id,
                client_secret=config.api.opensky_client_secret
            )

        # Initialize DumpSlurp (dump1090) if configured
        self.dump_slurp: Optional[DumpSlurp] = None
        if config.api.dump1090_host and config.api.dump1090_port:
            self.dump_slurp = DumpSlurp(
                host=config.api.dump1090_host,
                port=config.api.dump1090_port,
                expire_seconds=config.api.aircraft_expire_seconds,
                state_callback=self._process_dump1090_states,
                state_callback_interval=1.0
            )
        self.dump_slurp_last_announce = 0

        # Aircraft tracking
        self.current_aircraft: Dict[str, Aircraft] = {}  # icao24 -> Aircraft
        self.lock = threading.Lock()

        # Callbacks for aircraft updates
        self.on_aircraft_updated: List[Callable[[List[Aircraft]], None]] = []

        # Background threads
        self.opensky_thread: Optional[threading.Thread] = None
        self.flightaware_thread: Optional[threading.Thread] = None
        self.running = False

        # FlightAware rate limiting
        self.fa_cache: Dict[str, requests.Response] = {}
        self.fa_request_times: List[float] = []
        self.fa_lock = threading.Lock()
        self.fa_queue: List[str] = []

    def calculate_bounding_box(self) -> tuple:
        return self.config.home.position.bbox_around(self.config.api.radius_km)

    def start(self):
        """Start the hybrid API service."""
        if self.running:
            return

        self.running = True

        # Start DumpSlurp if configured
        if self.dump_slurp:
            print("Starting dump1090 data collection...")
            self.dump_slurp.start()

        # Start OpenSky polling thread (if not using dump1090)
        if self.opensky_api:
            self.opensky_thread = threading.Thread(target=self._opensky_poll_loop, daemon=True)
            self.opensky_thread.start()

        # Start FlightAware enrichment thread if API key is provided
        # Instead of doing this for every aircraft, lets only do it when we display them
        if self.config.api.flightaware_api_key:
            print("starting flightaware enrichment")
            self.flightaware_thread = threading.Thread(target=self._flightaware_enrich_loop, daemon=True)
            self.flightaware_thread.start()

    def stop(self):
        """Stop the hybrid API service."""
        self.running = False

        # Stop DumpSlurp if running
        if self.dump_slurp:
            self.dump_slurp.stop()

        if self.opensky_thread:
            self.opensky_thread.join(timeout=5)

        if self.flightaware_thread:
            self.flightaware_thread.join(timeout=5)

    def request_enrich(self, icao24: str):
        if self.config.api.flightaware_api_key:
            with self.lock:
                try:
                    self.fa_queue.remove(icao24)
                except ValueError:
                    # We don't care if it is already here, this is faster than checking before adding
                    pass
                self.fa_queue.append(icao24)

    def _opensky_poll_loop(self):
        """Background thread that polls OpenSky API."""

        while self.running:
            try:
                # Get states from OpenSky
                # print(self.bbox)
                states = self.opensky_api.get_states(bbox=self.bbox)

                if states:
                    self._process_opensky_states(states.states)

                # Sleep for configured interval
                time.sleep(self.config.api.opensky_refresh_interval)

            except Exception as e:
                print(f"Error polling OpenSky API: {e}")
                time.sleep(10)  # Wait before retrying

    def _process_opensky_states(self, states):
        """Process state vectors from OpenSky API."""
        out_states = []
        for state in states:
            # Create OpenSkyData from state vector
            opensky_data = OpenSkyData(
                icao24=state.icao24,
                callsign=state.callsign,
                origin_country=state.origin_country,
                last_position=state.time_position,
                last_contact=state.last_contact,
                longitude=state.longitude,
                latitude=state.latitude,
                geo_altitude=state.geo_altitude,
                baro_altitude=state.baro_altitude,
                on_ground=state.on_ground,
                velocity=state.velocity,
                true_track=state.true_track,
                vertical_rate=state.vertical_rate,
                squawk=state.squawk,
                spi=state.spi,
                position_source=state.position_source,
                # Category might not be available in all API versions
                category=getattr(state, 'category', 0)
            )

            out_states.append(opensky_data)

        print(f"Processed OpenSky states: {len(out_states)}")
        self._merge_osky_states(out_states)

    def _process_dump1090_states(self, aircraft_list: List[OpenSkyData]):
        """Process aircraft states from dump1090 via DumpSlurp."""
        now = datetime.now().timestamp()

        if now - self.dump_slurp_last_announce > 30:
            self.dump_slurp_last_announce = now
            print(f"Processed dump1090 states: {len(aircraft_list)}")

        self._merge_osky_states(aircraft_list)

    def _merge_osky_states(self, states: List[OpenSkyData]):
        with self.lock:
            # Track which aircraft are present in this update
            current_icao24s = set()

            for state in states:
                icao24 = state.icao24
                current_icao24s.add(icao24)

                # Update or create aircraft
                if icao24 in self.current_aircraft:
                    # Only update if newer data
                    current = self.current_aircraft[icao24]
                    if state.last_contact > current.opensky.last_contact:
                        current.opensky.merge(state)
                else:
                    # Create new aircraft (DumpSlurp provides Aircraft objects)
                    self.current_aircraft[icao24] = Aircraft(opensky=state)

            # Remove any stale aircraft
            now = datetime.now().timestamp()
            expire_seconds = self.config.api.aircraft_expire_seconds
            for icao24 in list(self.current_aircraft.keys()):
                if icao24 not in current_icao24s:
                    if now - self.current_aircraft[icao24].opensky.last_contact > expire_seconds:
                        del self.current_aircraft[icao24]

            # Notify observers
            self._notify_observers()

    def _flightaware_enrich_loop(self):
        """Background thread that enriches aircraft with FlightAware data."""
        while self.running:
            try:
                with self.lock:
                    # Find aircraft that need FlightAware data
                    expired = [
                        icao24 for icao24 in self.fa_queue if icao24 not in self.current_aircraft
                    ]

                    for each in expired:
                        self.fa_queue.remove(each)

                    unenriched = [
                        icao24 for icao24 in self.fa_queue
                        if icao24 in self.current_aircraft
                        and self.current_aircraft[icao24].flightaware is None
                        and self.current_aircraft[icao24].opensky
                        and self.current_aircraft[icao24].opensky.callsign  # Only if we have a callsign
                    ]


                for icao24 in unenriched:
                    if not self.running:
                        break

                    # Rate limit check
                    if not self._can_make_flightaware_request():
                        time.sleep(1)
                        continue

                    # Get FlightAware data
                    if icao24 in self.fa_queue:
                        self.fa_queue.remove(icao24)

                    self._enrich_with_flightaware(icao24)

                time.sleep(1)  # Brief pause between enrichment attempts

            except Exception as e:
                print(f"Error in FlightAware enrichment: {e}")
                time.sleep(5)

    def _can_process_flightaware_request(self) -> bool:
        start = self.config.api.quiet_start
        end = self.config.api.quiet_end

        if start is None or end is None:
            return True

        tz = ZoneInfo(key=self.config.api.quiet_tz)
        now = datetime.now().astimezone(tz)

        if start > end:
            return start > now.hour >= end
        else:
            return start <= now.hour or now.hour < end

    def _can_make_flightaware_request(self) -> bool:
        """Check if we can make a FlightAware request (rate limiting)."""
        with self.fa_lock:
            now = time.time()
            # Remove requests older than 1 minute
            self.fa_request_times = [t for t in self.fa_request_times if now - t < 60]

            if len(self.fa_request_times) < self.config.api.max_flightaware_requests_per_minute:
                self.fa_request_times.append(now)
                return True
            return False

    @staticmethod
    def _parse_fa_components_from_flight(flight: Dict, default: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        origin = flight.get('origin', {}) or {}
        origin_apt = origin.get('code_iata', default) or default
        dest = flight.get('destination', {}) or {}
        dest_apt = dest.get('code_iata', default) or default
        aircraft = flight.get('aircraft_type', default) or default
        return origin_apt, dest_apt, aircraft

    ## Flights which have identical src, dest, and aircraft can just be cached
    @staticmethod
    def _can_cache_flightaware_request(flights: List[Dict]) -> bool:
        if len(flights) == 0:
            return False

        comps = [".".join(HybridAPI._parse_fa_components_from_flight(x, '')) for x in flights]
        init = comps[0]
        return all(x == init for x in comps)

    def _enrich_with_flightaware(self, icao24: str):
        """Enrich an aircraft with FlightAware data."""
        try:
            aircraft = self.current_aircraft.get(icao24)
            if not aircraft or not aircraft.opensky.callsign:
                return

            # Make FlightAware API request
            # Note: This is a simplified version - actual FA API might require different endpoints
            headers = {
                'x-apikey': self.config.api.flightaware_api_key
            }

            # Any attempt marks the aircraft as loaded
            with self.lock:
                self.current_aircraft[icao24].flightaware = FlightAwareData()

            # when processing is not allowed, we don't want to retry
            # so this bailout happens after we've marked the aircraft as loaded
            if not self._can_process_flightaware_request():
                return

            now = datetime.now()
            tomorrow = now + timedelta(days=1)
            yesterday = now - timedelta(days=1)

            params = {
                'start': self._make_fa_datetime(yesterday),
                'end': self._make_fa_datetime(tomorrow),
            }

            # Try to get flight info by callsign (flight identifier)
            callsign = aircraft.opensky.callsign.strip()

            url = f"https://aeroapi.flightaware.com/aeroapi/flights/{callsign}"

            response: requests.Response
            if callsign in self.fa_cache:
                response = self.fa_cache.get(callsign, None)
                print(f"using cached response: {callsign}")
            else:
                response = requests.get(url, params=params, headers=headers, timeout=10)
                print(f"fetched {callsign}: response: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                if data is None:
                    return

                flights = data.get('flights', []) or []

                # print(f"parsed {len(flights)} flights")
                if callsign not in self.fa_cache and HybridAPI._can_cache_flightaware_request(flights):
                    print(f"caching flight: {callsign}")
                    self.fa_cache[callsign] = response

                flights.append({})
                # TODO this should be based on takeoff time with our cached options
                flight = next(filter(lambda x: "En Route" in x.get('status', " "), flights), flights[0])

                (origin_apt, dest_apt, aircraft) = self._parse_fa_components_from_flight(flight)
                # print("parsed origin and dest")


                # Parse FlightAware response and create FlightAwareData
                # Note: Actual field names depend on FA API response structure
                fa_data = FlightAwareData(
                    airline=flight.get('operator_iata', None),
                    flight_number=flight.get('flight_number', None),
                    aircraft_type=aircraft,
                    origin_airport=origin_apt,
                    destination_airport=dest_apt,
                    estimated_arrival_time=self._parse_fa_datetime(flight.get('estimated_arrival', '')),
                    departure_time=self._parse_fa_datetime(flight.get('actual_departure', ''))
                )

                with self.lock:
                    self.current_aircraft[icao24].flightaware = fa_data
                    self._notify_observers()

        except Exception as e:
            print(f"Error enriching {icao24} with FlightAware data: {e}")

    @staticmethod
    def _parse_fa_datetime(dt_str: Optional[str]) -> Optional[datetime]:
        """Parse FlightAware datetime string."""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except:
            return None

    @staticmethod
    def _make_fa_datetime(dt: datetime) -> str:
        local = dt.astimezone()
        utc = local.astimezone(timezone.utc)
        return utc.isoformat(timespec='seconds').replace('+00:00', 'Z')

    def _notify_observers(self):
        """Notify all observers of aircraft updates."""
        aircraft_list = list(self.current_aircraft.values())
        for callback in self.on_aircraft_updated:
            try:
                callback(aircraft_list)
            except Exception as e:
                print(f"Error notifying observer: {e}")

    def add_observer(self, callback: Callable[[List[Aircraft]], None]):
        """Add an observer callback for aircraft updates."""
        self.on_aircraft_updated.append(callback)

    def remove_observer(self, callback: Callable[[List[Aircraft]], None]):
        """Remove an observer callback."""
        if callback in self.on_aircraft_updated:
            self.on_aircraft_updated.remove(callback)

    def get_current_aircraft(self) -> List[Aircraft]:
        """Get current list of aircraft."""
        with self.lock:
            return list(self.current_aircraft.values())


# Example usage
if __name__ == "__main__":
    # Example configuration for Corvallis area
    config = load(open("config.json"))
    config = BBYConfig(config)

    def on_aircraft_update(aircraft: List[Aircraft]):
        print(f"Aircraft update: {len(aircraft)} aircraft in range")
        for a in aircraft:  # demo shows all aircraft
            # print(a)
            dist = config.home.position.calculate_distance(a.extrapolate_position(0))
            print(f"  - {a.get_display_name()}: {a.get_altitude_ft():.0f}ft @ {a.get_speed_knots():.0f}kt {a.bonus()} {dist}")

    api = HybridAPI(config)
    api.add_observer(on_aircraft_update)

    print(f"bbox: {api.bbox}")

    try:
        api.start()
        print("Hybrid API running... Press Ctrl+C to stop")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        api.stop()
