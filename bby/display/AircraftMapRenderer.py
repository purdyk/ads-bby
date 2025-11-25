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
        self.draw_interpolated(canvas, home_lon, home_lat, self.home_color)

        for craft in aircraft:
            # print(f"rendering {craft[0].opensky.icao24} at {pos_lon}, {pos_lat}")
            (pos_lon, pos_lat) = self.get_local_xy(craft[1])

            self.draw_interpolated(canvas, pos_lon, pos_lat, self.aircraft_color)
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

    def draw_interpolated(self, canvas: FrameCanvas, x: float, y: float, color: graphics.Color) -> None:
        for xx in range(0, 2):
            for yy in range(0, 2):
                out_x = math.floor(x + xx)
                out_y = math.floor(y + yy)
                x_comp = 1 - abs(x - out_x)
                y_comp = 1 - abs(y - out_y)
                xy_comp = (x_comp + y_comp) / 2
                # print(f"setting: {x} -> {out_x}, {y} -> {out_y}, {xy_comp}")
                canvas.SetPixel(out_x, out_y, color.red * xy_comp, color.green * xy_comp, color.blue * xy_comp)