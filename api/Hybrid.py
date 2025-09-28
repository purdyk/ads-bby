import threading
import time
from typing import Dict, List, Optional, Set, Callable
from dataclasses import dataclass
from datetime import datetime
import requests
import os
import sys
import math

# Hybrid API driver
# Loads initial results from low-cost, low data API
# Loads supplemental information per-aircraft from higher cost
# Initializes with a home location ( lat / lng pair ) and uses this to poll for aircraft within a provided radius
# Low Cost: Use OpenSky api to load nearby aircraft ( refresh once every 30 seconds? ) ( documentation: https://openskynetwork.github.io/opensky-api/python.html )
# Supplemental: use FlightAware AeroApi to load supplemental information ( Airline, flight number, origin/dest airport, estimated time ) ( documentation: use the position call on https://www.flightaware.com/aeroapi/portal/#get-/flights/-id-/position )
# Ideally provides some observable stream of "current aircraft" and automatically manages loading extra information once per new aircraft, with appropriate error handling

# Add parent directory to path to import models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from opensky_api import OpenSkyApi
from models.Aircraft import Aircraft, OpenSkyData, FlightAwareData
from models.Position import Position


@dataclass
class HybridAPIConfig:
    """Configuration for the Hybrid API driver."""
    home_latitude: float
    home_longitude: float
    radius_km: float = 50.0  # Default 50km radius
    opensky_username: Optional[str] = None
    opensky_password: Optional[str] = None
    flightaware_api_key: Optional[str] = None
    opensky_refresh_interval: int = 30  # seconds
    max_flightaware_requests_per_minute: int = 10


class HybridAPI:
    """
    Hybrid API driver that combines OpenSky (free/low-cost) and FlightAware (paid) data.
    Provides a stream of aircraft with automatic supplemental data loading.
    """

    def __init__(self, config: HybridAPIConfig):
        self.config = config
        self.home = Position(config.home_longitude, config.home_latitude)

        # Initialize OpenSky API
        self.opensky_api = OpenSkyApi(
            username=config.opensky_username,
            password=config.opensky_password
        )

        # Aircraft tracking
        self.current_aircraft: Dict[str, Aircraft] = {}  # icao24 -> Aircraft
        self.aircraft_with_flightaware: Set[str] = set()  # icao24s that have FA data
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

    def calculate_bounding_box(self) -> tuple:
        """Calculate bounding box from home position and radius."""
        # Earth radius in km
        R = 6371.0

        # Convert radius to degrees (approximation)
        lat_delta = self.config.radius_km / R * (180 / math.pi)
        lon_delta = self.config.radius_km / (R * math.cos(math.radians(self.config.home_latitude))) * (180 / math.pi)

        min_lat = self.config.home_latitude - lat_delta
        max_lat = self.config.home_latitude + lat_delta
        min_lon = self.config.home_longitude - lon_delta
        max_lon = self.config.home_longitude + lon_delta

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
        if self.config.flightaware_api_key:
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

    def _opensky_poll_loop(self):
        """Background thread that polls OpenSky API."""
        bbox = self.calculate_bounding_box()

        while self.running:
            try:
                # Get states from OpenSky
                states = self.opensky_api.get_states(bbox=bbox)

                if states:
                    self._process_opensky_states(states.states)

                # Sleep for configured interval
                time.sleep(self.config.opensky_refresh_interval)

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
                    self.aircraft_with_flightaware.discard(icao24)

            # Notify observers
            self._notify_observers()

    def _flightaware_enrich_loop(self):
        """Background thread that enriches aircraft with FlightAware data."""
        while self.running:
            try:
                with self.lock:
                    # Find aircraft that need FlightAware data
                    unenriched = [
                        icao24 for icao24 in self.current_aircraft.keys()
                        if icao24 not in self.aircraft_with_flightaware
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

            if len(self.fa_request_times) < self.config.max_flightaware_requests_per_minute:
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
                'x-apikey': self.config.flightaware_api_key
            }

            # Try to get flight info by callsign (flight identifier)
            # Note: Real implementation would need proper FA API endpoint
            url = f"https://aeroapi.flightaware.com/aeroapi/flights/{aircraft.opensky.callsign.strip()}"

            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()

                # Parse FlightAware response and create FlightAwareData
                # Note: Actual field names depend on FA API response structure
                fa_data = FlightAwareData(
                    airline=data.get('operator'),
                    flight_number=data.get('flight_number'),
                    aircraft_type=data.get('aircraft_type'),
                    origin_airport=data.get('origin', {}).get('code'),
                    destination_airport=data.get('destination', {}).get('code'),
                    estimated_arrival_time=self._parse_fa_datetime(data.get('estimated_arrival')),
                    departure_time=self._parse_fa_datetime(data.get('actual_departure'))
                )

                with self.lock:
                    if icao24 in self.current_aircraft:
                        self.current_aircraft[icao24].flightaware = fa_data
                        self.aircraft_with_flightaware.add(icao24)
                        self._notify_observers()

        except Exception as e:
            print(f"Error enriching {icao24} with FlightAware data: {e}")

    def _parse_fa_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """Parse FlightAware datetime string."""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except:
            return None

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
    config = HybridAPIConfig(
        home_latitude=37.7749,
        home_longitude=-122.4194,
        # home_latitude=44.59000326746005,
        # home_longitude=-123.30320891807465,
        radius_km=25,
        opensky_username=None,  # Optional for better rate limits
        opensky_password=None,
        flightaware_api_key=os.getenv("FLIGHTAWARE_API_KEY"),  # Set via environment
        opensky_refresh_interval=30
    )

    def on_aircraft_update(aircraft: List[Aircraft]):
        print(f"Aircraft update: {len(aircraft)} aircraft in range")
        for a in aircraft:  # demo shows all aircraft
            # print(a)
            print(f"  - {a.get_display_name()}: {a.get_altitude_ft():.0f}ft @ {a.get_speed_knots():.0f}kt {a.bonus()}")

    api = HybridAPI(config)
    api.add_observer(on_aircraft_update)

    try:
        api.start()
        print("Hybrid API running... Press Ctrl+C to stop")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        api.stop()