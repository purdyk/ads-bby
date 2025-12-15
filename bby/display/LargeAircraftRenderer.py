from rgbmatrix import graphics, FrameCanvas

from bby.display.AircraftRenderer import AircraftRenderer
from bby.models.Aircraft import Aircraft
from bby.models.BbyCfg import DisplayConfig
from bby.models.Position import Position


class LargeAircraftRenderer(AircraftRenderer):
    """Renderer for the primary aircraft display (top 16 pixels)."""

    def __init__(self, home: Position, width: int = 64, height: int = 16, cfg: DisplayConfig = None):
        super().__init__(home, width, height)
        try:
            self.font_large = graphics.Font()
            self.font_large.LoadFont(f"bby/fonts/{cfg.font_big}")
            self.font_small = graphics.Font()
            self.font_small.LoadFont(f"bby/fonts/{cfg.font_small}")
            self.first_offset = self.font_large.height - 3
            self.second_offset = self.font_large.height + self.font_small.height - 3
            self.bottom = self.second_offset
        except Exception as e:
            print(f"Failed to load font, yikes {e}")

    def render(self, aircraft: Aircraft, position: Position, distance: float,
               canvas: FrameCanvas, x: int, y: int, current_time: float) -> None:
        """
        Render large aircraft display at specified position.
        Designed to take up roughly half the vertical space and all the horizontal space. This is highly detailed
        """

        # Calculate current distance from projected position
        is_approaching = position.is_approaching(self.home)

        # Get strobe color for text
        text_color = self.get_strobe_color(is_approaching, current_time)

        # Line 1: Flight identifier (0-5 pixels), distance, speed
        flight_name = aircraft.get_display_name()
        distance_str = self.format_distance(distance)
        speed_str = f"{int(aircraft.get_speed_knots() or 0)}kt" if aircraft.get_speed_knots() else "--kt"

        line1a = f"{flight_name}"
        line1b = f"{distance_str}"
        off = graphics.DrawText(canvas, self.font_large, x, y + self.first_offset, text_color, line1a)
        off += graphics.DrawText(canvas, self.font_large, x + off + 2, y + self.first_offset, text_color, line1b)

        # Line 2: Aircraft type, Origin, Destination, V-rate
        line2a = f"{aircraft.get_type()[:7]}"
        line2b = f"{aircraft.get_origin_airport()}-{aircraft.get_dest_airport()}"
        line2c = f"{speed_str}"
        off = graphics.DrawText(canvas, self.font_small, x, y + self.second_offset, text_color, line2a) + 2
        # graphics.DrawText(canvas, self.font_small, x + off - 1, y + self.second_offset, text_color, ":")
        canvas.SetPixel(x + off - 2, y + self.second_offset - 3, text_color.red, text_color.green, text_color.blue)
        off += graphics.DrawText(canvas, self.font_small, x + off, y + self.second_offset, text_color, line2b) + 2
        # graphics.DrawText(canvas, self.font_small, x + off - 1, y + self.second_offset, text_color, ":")
        canvas.SetPixel(x + off - 2, y + self.second_offset - 3, text_color.red, text_color.green, text_color.blue)
        off += graphics.DrawText(canvas, self.font_small, x + off, y + self.second_offset, text_color, line2c) + 2
