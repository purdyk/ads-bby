from typing import List, Tuple, Dict

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

    @staticmethod
    def generate_blocks(blocks: Dict[int, graphics.Color], x: float, color: graphics.Color):
        for xx in range(0, 3):
            color_scale = 1.0
            if xx == 0:
                color_scale = 1 - (x % 1.0)
            elif xx == 2:
                color_scale = (x % 1.0)

            target = int(x+xx)
            blend = blocks.get(target, graphics.Color(0, 0, 0))
            new = graphics.Color(color.red * color_scale, color.green * color_scale, color.blue * color_scale)
            blended = graphics.Color(max(blend.red, new.red), max(blend.green, new.green), max(blend.blue, new.blue))
            blocks[target] = blended


    def write_blocks(self, blocks: Dict[int, graphics.Color], y: float, canvas: FrameCanvas):
        for x in blocks.keys():
            color = blocks[x]
            for yy in range(0, self.height):
                canvas.SetPixel(x, y + yy, color.red, color.green, color.blue)


    def render(self, canvas: FrameCanvas, x: int, y: int, aircraft: List[Tuple[Aircraft, Position, float]]) -> None:

        blocks: Dict[int, graphics.Color] = {}

        for aircraft in aircraft:
            is_approaching = aircraft[1].is_approaching(self.home)
            scale = x + ((canvas.width - x) * (aircraft[2] / self.range))
            if is_approaching:
                color = self.green
            else:
                color = self.red
            AircraftGraphRenderer.generate_blocks(blocks, scale, color)

        self.write_blocks(blocks, y, canvas)
