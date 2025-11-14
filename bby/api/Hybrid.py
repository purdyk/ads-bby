import threading
import time
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta, timezone
import requests
import math
from json import load


from bby.models.BbyCfg import BBYConfig
from bby.models.Aircraft import Aircraft, OpenSkyData, FlightAwareData
from opensky_api import OpenSkyApi
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

        # Initialize OpenSky API
        self.opensky_api = OpenSkyApi(
            # username=config.api.opensky_username,
            # password=config.api.opensky_password,
            client_id=config.api.opensky_client_id,
            client_secret=config.api.opensky_client_secret
        )

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
        self.fa_request_times: List[float] = []
        self.fa_lock = threading.Lock()
        self.fa_queue: List[str] = []

    def calculate_bounding_box(self) -> tuple:
        """Calculate bounding box from home position and radius."""
        # Earth radius in km
        R = 6371.0

        # Convert radius to degrees (approximation)
        lat_delta = self.config.api.radius_km / R * (180 / math.pi)
        lon_delta = self.config.api.radius_km / (R * math.cos(math.radians(self.config.home.latitude))) * (180 / math.pi)

        min_lat = self.config.home.latitude - lat_delta
        max_lat = self.config.home.latitude + lat_delta
        min_lon = self.config.home.longitude - lon_delta
        max_lon = self.config.home.longitude + lon_delta

        # OpenSky expects (min_lat, max_lat, min_lon, max_lon)
        return min_lat, max_lat, min_lon, max_lon

    def start(self):
        """Start the hybrid API service."""
        if self.running:
            return

        self.running = True

        # Start OpenSky polling thread
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
        with self.lock:
            # Track which aircraft are still present
            current_icao24s = set()

            for state in states:
                icao24 = state.icao24
                current_icao24s.add(icao24)

                # Create OpenSkyData from state vector
                opensky_data = OpenSkyData(
                    icao24=state.icao24,
                    callsign=state.callsign,
                    origin_country=state.origin_country,
                    time_position=state.time_position,
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

                # Update or create aircraft
                if icao24 in self.current_aircraft:
                    # Update existing aircraft's OpenSky data
                    self.current_aircraft[icao24].opensky = opensky_data
                else:
                    # Create new aircraft
                    aircraft = Aircraft(opensky=opensky_data)
                    self.current_aircraft[icao24] = aircraft

            # Remove aircraft that are no longer in range
            for icao24 in list(self.current_aircraft.keys()):
                if icao24 not in current_icao24s:
                    del self.current_aircraft[icao24]

            # Notify observers
            self._notify_observers()

    def _flightaware_enrich_loop(self):
        """Background thread that enriches aircraft with FlightAware data."""
        while self.running:
            try:
                with self.lock:
                    # Find aircraft that need FlightAware data
                    unenriched = [
                        icao24 for icao24 in self.fa_queue
                        if self.current_aircraft[icao24].flightaware is None
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
                    self.fa_queue.remove(icao24)
                    self._enrich_with_flightaware(icao24)

                time.sleep(1)  # Brief pause between enrichment attempts

            except Exception as e:
                print(f"Error in FlightAware enrichment: {e}")
                time.sleep(5)

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

            now = datetime.now()
            tomorrow = now + timedelta(days=1)
            yesterday = now - timedelta(days=1)

            params = {
                'start': self._make_fa_datetime(yesterday),
                'end': self._make_fa_datetime(tomorrow),
            }

            # Try to get flight info by callsign (flight identifier)
            # Note: Real implementation would need proper FA API endpoint
            url = f"https://aeroapi.flightaware.com/aeroapi/flights/{aircraft.opensky.callsign.strip()}"

            response = requests.get(url, params=params, headers=headers, timeout=10)

            print(f"fetched: {url}\nresponse: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                if data is None:
                    return

                flights = data.get('flights', []) or []
                flights.append({})
                flight = next(filter(lambda x: "En Route" in x.get('status', " ") or " ", flights), flights[0])

                # print(f"parsed {len(flights)} flights")

                origin = flight.get('origin', {}) or {}
                origin_apt = origin.get('code_iata', None)
                dest = flight.get('destination', {}) or {}
                dest_apt = dest.get('code_iata', None)

                # print("parsed origin and dest")

                # Parse FlightAware response and create FlightAwareData
                # Note: Actual field names depend on FA API response structure
                fa_data = FlightAwareData(
                    airline=flight.get('operator_iata', None),
                    flight_number=flight.get('flight_number', None),
                    aircraft_type=flight.get('aircraft_type', None),
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
