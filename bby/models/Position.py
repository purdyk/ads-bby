from dataclasses import dataclass
from typing import Optional
import math

@dataclass
class Position:
    longitude: float
    latitude: float
    velocity: Optional[float] = None  # Ground speed in m/s
    heading: Optional[float] = None  # Direction in degrees

    def calculate_distance(self, other: 'Position') -> float:
        """
        Calculate great circle distance from a point (or home if not specified) in meters.
        Uses Haversine formula.
        """
        # Haversine formula
        radius = 6378137  # Earth radius in meters

        lat1_rad = math.radians(other.latitude)
        lat2_rad = math.radians(self.latitude)
        delta_lat = math.radians(self.latitude - other.latitude)
        delta_lon = math.radians(self.longitude - other.longitude)

        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) *
             math.sin(delta_lon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return radius * c

    def calculate_bearing_to(self, other: 'Position') -> float:
        """
        Calculate bearing from this position to another in degrees.
        """
        lat1_rad = math.radians(self.latitude)
        lat2_rad = math.radians(other.latitude)
        delta_lon = math.radians(other.longitude - self.longitude)

        y = math.sin(delta_lon) * math.cos(lat2_rad)
        x = (math.cos(lat1_rad) * math.sin(lat2_rad) -
             math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lon))

        bearing = math.degrees(math.atan2(y, x))
        return (bearing + 360) % 360

    def is_approaching(self, other: 'Position', threshold_degrees: float = 90) -> bool:
        """
        Determine if aircraft is approaching a point based on heading and bearing.
        Returns True if approaching, False if departing
        """
        bearing_to_point = self.calculate_bearing_to(other)

        # Calculate angular difference
        angle_diff = abs((bearing_to_point - self.heading + 180) % 360 - 180)

        # If angle difference is less than threshold, aircraft is approaching
        return angle_diff < threshold_degrees