from typing import List, Tuple

from rgbmatrix import graphics, FrameCanvas

from bby.display.AircraftRenderer import AircraftRenderer
from bby.models.Aircraft import Aircraft
from bby.models.Position import Position


class AircraftGraphRenderer(AircraftRenderer):
    def __init__(self, home: Position, width: int, height: int, range_km: int):
        super().__init__(home, width, height)
        self.range = range_km * 1000.0
        self.red = graphics.Color(255, 0, 0)
        self.green = graphics.Color(0, 255, 0)

    def draw_block(self, canvas: FrameCanvas, x: float, y:float, color: graphics.Color):
        for xx in range(0, 3):
            color_scale = 1.0
            if xx == 0:
                color_scale = 1 - (x % 1.0)
            elif xx == 2:
                color_scale = (x % 1.0)

            for yy in range(0, self.height):
                canvas.SetPixel(x+xx, y+yy, color.red * color_scale, color.green * color_scale, color.blue * color_scale)

    def render(self, canvas: FrameCanvas, x: int, y: int, aircraft: List[Tuple[Aircraft, Position, float]]) -> None:
        for aircraft in aircraft:
            is_approaching = aircraft[1].is_approaching(self.home)
            scale = x + ((canvas.width - x) * (aircraft[2] / self.range))
            if is_approaching:
                color = self.green
            else:
                color = self.red
            self.draw_block(canvas, scale, y, color)
