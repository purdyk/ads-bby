from PIL import Image
from rgbmatrix import graphics, FrameCanvas

from bby.display.AircraftRenderer import AircraftRenderer
from bby.models.Position import Position


class ScreenRenderer(AircraftRenderer):
    def __init__(self, home: Position, width: int, height: int, name: str):
        super().__init__(home, width, height)
        self.name = name
        try:
            self.font = graphics.Font()
            self.font.LoadFont("bby/fonts/6x10.bdf")
            self.image = Image.open("bby/images/cub2.ppm").convert("RGB")
            self.img_width = self.image.size[0]
        except:
            print("Failed to load font, yikes")

    def render(self, canvas: FrameCanvas, current_time: float) -> None:
        graphics.DrawText(canvas, self.font, 0, 0 + self.font.height + 1, graphics.Color(255,255,255), self.name)
        x_pos = (current_time * 10) % self.img_width
        y_pos = abs((int(current_time) % 4) - 2) - 1
        canvas.SetImage(self.image, -x_pos, y_pos, unsafe=False)
        if x_pos > self.img_width - self.width:
            canvas.SetImage(self.image, -x_pos + self.img_width, y_pos, unsafe=False)
        graphics.DrawText(canvas, self.font, -x_pos + 92, 16 + (self.font.height / 2) + y_pos, graphics.Color(0,0,0), self.name)
