from typing import Optional

from rgbmatrix import graphics

from bby.models.Position import Position


class AircraftRenderer:
    """Base class for rendering aircraft information."""

    def __init__(self,  home: Position, width: int, height: int):
        self.home = home
        self.width = width
        self.height = height
        self.frame_count = 0


    @staticmethod
    def get_strobe_color(is_approaching: bool, current_time: float) -> graphics.Color:
        """Get text color based on approach status and frame count."""
        # Based on current time, use a 8 second window, go to white at 4 seconds, interpolate the color from full red
        # or full green to white, exponentially as the time approaches or withdraws from the 4 second asymptote

        # Scale 0 - 1, then
        factor = abs((current_time % 4.0) - 2.0) / 2.0
        scale = (factor * 100)
        if is_approaching:
            return graphics.Color(scale, 255, scale)  # Green for approaching
        else:
            return graphics.Color(255, scale, scale)  # Red for departing

    @staticmethod
    def format_distance(distance_m: Optional[float]) -> str:
        """Format distance for display."""
        distance_km = distance_m/1000.0
        if distance_km is None:
            return "--"
        if distance_km < 1:
            return f"{int(distance_km * 1000)}m"
        elif distance_km < 10:
            return f"{distance_km:.1f}km"
        else:
            return f"{int(distance_km)}km"

    @staticmethod
    def get_direction_arrow(is_approaching: Optional[bool]) -> str:
        """Get arrow character based on approach status."""
        if is_approaching is None:
            return "-"
        return "↓" if is_approaching else "↑"
