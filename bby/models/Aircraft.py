from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from datetime import datetime
import math
from models.Position import Position

# Represents a single aircraft provided from the hybrid api
# Includes directly provided information
# Includes methods for projecting position based on last data sample and vector of travel
# Also includes helpers to determine distance from a fixed point and direction of travel ( from/to said fixed point )

# Relevant properties to expose
# - Tail Number / Airline + Flight Number
# - Airspeed
# - Distance
# - Aircraft Make + Model
# - #NR souls on board
# - Flight Time ( current duration, estimated total time, estimated time until arrival )
# - Heading
# - It would be very cool to have a database of low-pixel airline logos to render

# Derived properties
# - Current estimated position ( extrapolated from heading, sampled position, and airspeed )
# - Current estimated distance ( from fixed point, extrapolated from current estimated position  )
# - Approaching / departing fixed point ( based on estimated position and heading )


@dataclass
class OpenSkyData:
    """Encapsulates all properties from the OpenSky API state vector."""
    # Required identifier
    icao24: str

    # Basic identification
    callsign: Optional[str] = None
    origin_country: str = ""

    # Timing information
    time_position: Optional[int] = None
    last_contact: int = 0

    # Position data
    longitude: Optional[float] = None
    latitude: Optional[float] = None

    # Altitude information
    geo_altitude: Optional[float] = None  # Geometric altitude in meters
    baro_altitude: Optional[float] = None  # Barometric altitude in meters
    on_ground: bool = False

    # Movement data
    velocity: Optional[float] = None  # Ground speed in m/s
    true_track: Optional[float] = None  # Direction in degrees
    vertical_rate: Optional[float] = None  # Vertical speed in m/s

    # Transponder data
    squawk: Optional[str] = None
    spi: bool = False  # Special purpose indicator

    # Metadata
    sensors: List[int] = field(default_factory=list)
    position_source: int = 0
    category: int = 0  # Aircraft category (0-20)


@dataclass
class FlightAwareData:
    """Encapsulates supplemental data from FlightAware API."""
    airline: Optional[str] = None
    flight_number: Optional[str] = None
    aircraft_type: Optional[str] = None
    origin_airport: Optional[str] = None
    destination_airport: Optional[str] = None
    estimated_arrival_time: Optional[datetime] = None
    departure_time: Optional[datetime] = None


@dataclass
class Aircraft:
    """
    Represents a single aircraft with data from OpenSky API (required)
    and optional supplemental information from FlightAware.
    """
    # Required OpenSky data
    opensky: OpenSkyData

    # Optional FlightAware supplemental data
    flightaware: Optional[FlightAwareData] = None

    def get_altitude(self) -> Optional[float]:
        """Return the best available altitude in meters."""
        return self.opensky.geo_altitude if self.opensky.geo_altitude is not None \
            else self.opensky.baro_altitude if self.opensky.baro_altitude is not None else 0.0

    def get_altitude_ft(self) -> Optional[float]:
        """Return the best available altitude in feet."""
        altitude_m = self.get_altitude()
        return altitude_m * 3.28084 if altitude_m is not None else None

    def get_speed_knots(self) -> Optional[float]:
        """Return ground speed in knots."""
        return self.opensky.velocity * 1.94384 if self.opensky.velocity is not None else None

    def get_vertical_rate_fpm(self) -> Optional[float]:
        """Return vertical rate in feet per minute."""
        return self.opensky.vertical_rate * 196.85 if self.opensky.vertical_rate is not None else None

    def bonus(self) -> str:
        if self.flightaware:
            return f"{self.flightaware.origin_airport} -> {self.flightaware.destination_airport}"
        else:
            return self.get_aircraft_category_name()

    def extrapolate_position(self, seconds_elapsed: float) -> Optional[Position]:
        """
        Extrapolate current position based on last known position, speed, and heading.
        Returns a Position object with the extrapolated location.
        """
        if (self.opensky.latitude is None or self.opensky.longitude is None or
            self.opensky.velocity is None or self.opensky.true_track is None):
            return None

        # Calculate distance traveled
        distance_m = self.opensky.velocity * seconds_elapsed

        # Convert to angular distance
        radius = 6378137  # Earth radius in meters
        angular_distance = distance_m / radius

        # Convert positions and heading to radians
        lat1_rad = math.radians(self.opensky.latitude)
        lon1_rad = math.radians(self.opensky.longitude)
        heading_rad = math.radians(self.opensky.true_track)

        # Calculate new position
        lat2_rad = math.asin(
            math.sin(lat1_rad) * math.cos(angular_distance) +
            math.cos(lat1_rad) * math.sin(angular_distance) * math.cos(heading_rad)
        )

        lon2_rad = lon1_rad + math.atan2(
            math.sin(heading_rad) * math.sin(angular_distance) * math.cos(lat1_rad),
            math.cos(angular_distance) - math.sin(lat1_rad) * math.sin(lat2_rad)
        )

        # Convert back to degrees
        new_latitude = math.degrees(lat2_rad)
        new_longitude = math.degrees(lon2_rad)

        new_position = Position(new_longitude, new_latitude, self.opensky.velocity, self.opensky.true_track)

        return new_position

    def get_display_name(self) -> str:
        """Get a display name for the aircraft."""
        if self.flightaware and self.flightaware.flight_number and self.flightaware.airline:
            return f"{self.flightaware.airline}{self.flightaware.flight_number}"
        elif self.opensky.callsign:
            return self.opensky.callsign.strip()
        else:
            return self.opensky.icao24.upper()

    def get_aircraft_category_name(self) -> str:
        """Convert category number to human-readable string."""
        categories = {
            0: "No category",
            1: "No ADS-B emitter",
            2: "Light aircraft",
            3: "Small aircraft",
            4: "Large aircraft",
            5: "High vortex aircraft",
            6: "Heavy aircraft",
            7: "High performance aircraft",
            8: "Rotorcraft",
            9: "Glider",
            10: "Lighter than air",
            11: "Parachutist",
            12: "Ultralight",
            13: "Reserved",
            14: "Unmanned vehicle",
            15: "Space vehicle",
            16: "Surface vehicle",
            17: "Point obstacle",
            18: "Cluster obstacle",
            19: "Line obstacle",
            20: "Reserved",
        }
        return categories.get(self.opensky.category, "Unknown")

    def time_since_contact(self) -> Optional[float]:
        """Return seconds since last contact."""
        if self.opensky.last_contact:
            current_time = datetime.now().timestamp()
            return current_time - self.opensky.last_contact
        return None

    def is_data_fresh(self, max_age_seconds: float = 60) -> bool:
        """Check if the aircraft data is recent enough to be considered fresh."""
        time_since = self.time_since_contact()
        return time_since is not None and time_since < max_age_seconds
