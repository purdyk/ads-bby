from typing import List, Tuple

from rgbmatrix import graphics, FrameCanvas

from bby.display.AircraftRenderer import AircraftRenderer
from bby.models.Aircraft import Aircraft
from bby.models.Position import Position

import math

class AircraftMapRenderer(AircraftRenderer):
    def __init__(self, home: Position, width: int, height: int, range_km: float):
        super().__init__(home, width, height)
        (self.min_lat, self.max_lat, self.min_lon, self.max_lon) = home.bbox_around(range_km)

        self.lat_range = self.max_lat - self.min_lat
        self.lon_range = self.max_lon - self.min_lon

        self.min_size = min(width, height)
        self.x_off = (width - self.min_size) / 2
        self.y_off = (height - self.min_size) / 2

        self.aircraft_color = graphics.Color(255, 255, 255)
        self.home_color = graphics.Color(0, 0, 255)

    def render(self, canvas: FrameCanvas, x: int, y: int, aircraft: List[Tuple[Aircraft, Position, float]]) -> None:

        (home_lon, home_lat) = self.get_local_xy(self.home)
        self.draw_antialiased(canvas, home_lon, home_lat, self.home_color)

        for craft in aircraft:
            # print(f"rendering {craft[0].opensky.icao24} at {pos_lon}, {pos_lat}")
            (pos_lon, pos_lat) = self.get_local_xy(craft[1])

            self.draw_antialiased(canvas, pos_lon, pos_lat, self.aircraft_color)
            # canvas.SetPixel(pos_lon, pos_lat, 255, 255, 255)

    def get_local_xy(self, position: Position) -> Tuple[float, float]:
        # Lat is north/south, Y value
        # Top is high, but our display is reversed
        pos_lat = self.height - ((((position.latitude - self.min_lat) / self.lat_range) * self.min_size) + self.y_off)

        # Lon is East/West, left is low ( we're ignoring antimeridian for now )
        # pos_lon_offset = (craft[1].longitude - self.min_lon)
        # pos_lon_pct = (pos_lon_offset / self.lon_range)
        # pos_lon_pix = (pos_lon_pct * self.min_size)
        # pos_lon = pos_lon_pix + self.x_off
        # print(f"lon_offset: {pos_lon_offset}, pct: {pos_lon_pct}, pix: {pos_lon_pix}")
        pos_lon = (((position.longitude - self.min_lon) / self.lon_range) * self.min_size) + self.x_off

        return pos_lon, pos_lat

    def draw_antialiased(self, canvas: FrameCanvas, x: float, y: float, color: graphics.Color) -> None:
        """
        Draws an anti-aliased point by distributing intensity across up to 4 pixels
        using bilinear interpolation based on the fractional position.
        """
        # Get the base pixel coordinates
        base_x = math.floor(x)
        base_y = math.floor(y)

        # Calculate fractional offsets (0.0 to 1.0)
        fx = x - base_x
        fy = y - base_y

        # Distribute intensity across 4 neighboring pixels using bilinear interpolation
        # Each pixel's weight is the product of its distance factors
        weights = [
            ((1 - fx) * (1 - fy), 0, 0),  # Top-left
            (fx * (1 - fy), 1, 0),         # Top-right
            ((1 - fx) * fy, 0, 1),         # Bottom-left
            (fx * fy, 1, 1)                # Bottom-right
        ]

        for weight, dx, dy in weights:
            if weight > 0.001:  # Skip negligible contributions
                pixel_x = base_x + dx
                pixel_y = base_y + dy

                canvas.SetPixel(
                    pixel_x, pixel_y,
                    int(color.red * weight),
                    int(color.green * weight),
                    int(color.blue * weight)
                )