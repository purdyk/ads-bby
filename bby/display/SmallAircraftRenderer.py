from rgbmatrix import graphics, FrameCanvas

from bby.display.AircraftRenderer import AircraftRenderer
from bby.models.Aircraft import Aircraft
from bby.models.Position import Position


class SmallAircraftRenderer(AircraftRenderer):
    """Renderer for secondary aircraft in 16x16 pixel grids."""

    def __init__(self, home: Position, width: int = 16, height: int = 16):
        super().__init__(home, width, height)
        try:
            self.font = graphics.Font()
            self.font.LoadFont("bby/fonts/4x6.bdf")
            self.font_offset = self.font.height
        except:
            print("Failed to load font, yikes")


    def render(self, aircraft: Aircraft, position: Position, distance: float,
               canvas: FrameCanvas, x: int, y: int, current_time: float) -> None:
        """Render small aircraft display in 16x16 grid."""

        # Calculate current distance
        distance = self.home.calculate_distance(position)
        is_approaching = position.is_approaching(self.home)

        # Get strobe color
        text_color = self.get_strobe_color(is_approaching, current_time)

        # Draw border for this aircraft cell
        # draw.rectangle([x, y, x + 15, y + 15], outline=(64, 64, 64))

        # Line 1: Shortened flight ID (1-6 pixels)
        flight_name = aircraft.get_display_name()[:5]
        # if len(flight_name) > 5:
        #     flight_name = flight_name[:5]
        # draw.text((x + 1, y + 1), flight_name, fill=text_color, font=self.font)

        graphics.DrawText(canvas, self.font, x, y + self.font_offset, text_color, flight_name)

        # Line 2: Distance
        distance_str = self.format_distance(distance)[:5]
        graphics.DrawText(canvas, self.font, x, y + (self.font_offset * 2) + 1, text_color, distance_str)

        # # Direction indicator (bottom right)
        # arrow = "↓" if is_approaching else "↑"
        # draw.text((x + 11, y + 10), arrow, fill=text_color, font=self.font)
