from typing import List, Optional, Tuple
from datetime import datetime
import os
import sys

# Primary entry point for rendering aircraft to the frame buffer
# Should take a list of aircraft
# Should refresh the display frequently
# Providing relevant updated information from the aircraft list
# And a mechanism for updating the list of aircraft
# Ideally: A primary display for the closest aircraft with extended attributes, and a secondary display for
#   the N other closest aircraft, which displays more items in a truncated form.  These readouts should have semi-realtime
#   distance updates based on projections from the aircraft models, and smooth animations for reordering the list
# It should also have something like a screensaver to display if there are no current aircraft present to display
#
#
# Consider that you have access to PIL for rendering frames, and the access to the `rgbmatrix` library with the ability to write an RGB image to the buffer entirely
# Create renderer classes for both Large and Small aircraft display, then a compositor to place these renders into the frame buffer at specific positions

# Add parent directory to path to import models
# sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bby.models.Aircraft import Aircraft
from bby.models.BbyCfg import DisplayConfig
from bby.models.Position import Position
from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions, FrameCanvas
import time

class AircraftRenderer:
    """Base class for rendering aircraft information."""

    def __init__(self,  home: Position, width: int, height: int):
        self.home = home
        self.width = width
        self.height = height
        self.frame_count = 0


    def get_strobe_color(self, is_approaching: bool, current_time: float) -> graphics.Color:
        """Get text color based on approach status and frame count."""
        # Based on current time, use a 8 second window, go to white at 4 seconds, interpolate the color from full red
        # or full green to white, exponentially as the time approaches or withdraws from the 4 second asymptote

        # Scale 0 - 1, then
        factor = abs((current_time % 4.0) - 2.0) / 2.0
        scale = (factor * 255)
        if is_approaching:
            return graphics.Color(scale, 255, scale)  # Green for approaching
        else:
            return graphics.Color(255, scale, scale)  # Red for departing

    def format_distance(self, distance_m: Optional[float]) -> str:
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

    def get_direction_arrow(self, is_approaching: Optional[bool]) -> str:
        """Get arrow character based on approach status."""
        if is_approaching is None:
            return "-"
        return "↓" if is_approaching else "↑"

class LargeAircraftRenderer(AircraftRenderer):
    """Renderer for the primary aircraft display (top 16 pixels)."""

    def __init__(self, home: Position, width: int = 64, height: int = 16):
        super().__init__(home, width, height)
        try:
            self.font_large = graphics.Font()
            self.font_large.LoadFont("fonts/6x10.bdf")
            self.font_small = graphics.Font()
            self.font_small.LoadFont("fonts/4x6.bdf")
            self.first_offset = self.font_large.height - 2
            self.second_offset = self.font_large.height + self.font_small.height - 1
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

        line1 = f"{flight_name[:6]} {distance_str} {speed_str}"
        graphics.DrawText(canvas, self.font_large, x, y + self.first_offset, text_color, line1)

        # Line 2: Aircraft type, Origin, Destination, V-rate
        line2 = f"{aircraft.get_type()[:7]}:{aircraft.get_origin_airport()}-{aircraft.get_dest_airport()}"
        graphics.DrawText(canvas, self.font_small, x, y + self.second_offset, text_color, line2)


class SmallAircraftRenderer(AircraftRenderer):
    """Renderer for secondary aircraft in 16x16 pixel grids."""

    def __init__(self, home: Position, width: int = 16, height: int = 16):
        super().__init__(home, width, height)
        try:
            self.font = graphics.Font()
            self.font.LoadFont("fonts/4x6.bdf")
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

        graphics.DrawText(canvas, self.font, x, y, text_color, flight_name)

        # Line 2: Distance
        distance_str = self.format_distance(distance)[:5]
        graphics.DrawText(canvas, self.font, x, y + self.font.height + 1, text_color, distance_str)

        # # Direction indicator (bottom right)
        # arrow = "↓" if is_approaching else "↑"
        # draw.text((x + 11, y + 10), arrow, fill=text_color, font=self.font)

class ScreenRenderer(AircraftRenderer):
    def __init__(self, home: Position, width: int, height: int, name: str):
        super().__init__(home, width, height)
        self.name = name
        try:
            self.font = graphics.Font()
            self.font.LoadFont("fonts/6x10.bdf")
        except:
            print("Failed to load font, yikes")

    def render(self, canvas: FrameCanvas, current_time: float) -> None:
        graphics.DrawText(canvas, self.font, 0, 0 + self.font.height + 1, graphics.Color(255,255,255), self.name)

class DisplayCompositor:
    """Composites multiple aircraft renderers into a single display."""

    """
    Clients can set this property to update the list of rendered aircrafts.
    The compositor will choose which to display, and what properties to show.
    It expects timestamps on the aircraft to be relevant to local time for extrapolation.
    
    """
    aircraft: List[Aircraft]

    def __init__(self, home: Position, config: DisplayConfig):
        self.width = config.width
        self.height = config.height
        self.home =  home
        self.large_renderer = LargeAircraftRenderer(home = home, width = self.width, height = int(self.height / 2))
        self.small_renderer = SmallAircraftRenderer(home = home, width = int(self.width / 4), height = int(self.height / 2))
        self.screensaver = ScreenRenderer(home = home, width = int(self.width / 4), height = int(self.height / 4), name = config.name)
        self.frame_count = 0
        self.aircraft = []

        # Renderers should load their own fonts

        # Init the matrix with width and height
        options = RGBMatrixOptions()
        options.rows = config.height
        options.cols = config.width
        options.chain_length = 1
        options.parallel = 1
        options.pwm_bits = 11
        options.brightness = 80
        options.pwm_lsb_nanoseconds = 130
        options.hardware_mapping = config.mapping

        self.matrix = RGBMatrix(options=options)


    def render_frame(self, canvas: FrameCanvas, aircraft_list: List[Aircraft]):
        """Render a complete frame with all aircraft."""
        # Create black background
        canvas.Clear()

        # Get current positions for all aircraft
        current_time = datetime.now().timestamp()

        if len(aircraft_list) == 0:
            # Show screensaver or "No Aircraft" message
            # draw = ImageDraw.Draw(image)
            #
            # draw.text((8, 12), "No Aircraft", fill=(128, 128, 128), font=self.font)
            # return image
            # TODO screensaver
            self.screensaver.render(canvas, current_time)

        aircraft_with_positions = []

        for aircraft in aircraft_list:
            if aircraft.opensky.last_contact:
                seconds_elapsed = current_time - aircraft.opensky.last_contact
                position = aircraft.extrapolate_position(seconds_elapsed)
                if position:
                    distance = self.home.calculate_distance(position)
                    aircraft_with_positions.append((aircraft, position, distance))

        # Sort by distance
        aircraft_with_positions.sort(key=lambda x: x[2])

        # This is cheap, it only renders everything in-place
        # it should be submitting the list to an _actual_ compositor which chooses to animate their positions/size

        # Render primary aircraft (closest) in top half
        if aircraft_with_positions:
            primary = aircraft_with_positions[0]
            self.large_renderer.render(
                primary[0], primary[1], primary[2],
                canvas, 0, 0, current_time
            )

        # Render up to 4 secondary aircraft in bottom half
        secondary_positions = [
            (0, 25),
            (22, 25),
            (44, 25),
            # (44, 16),
        ]

        for i, pos in enumerate(secondary_positions):
            if i + 1 < len(aircraft_with_positions):
                secondary = aircraft_with_positions[i + 1]
                self.small_renderer.render(
                    secondary[0], secondary[1], secondary[2],
                    canvas, pos[0], pos[1], current_time
                )

    def run(self):
        # Maybe init a few things
        offscreen_canvas = self.matrix.CreateFrameCanvas()

        while True:
            self.render_frame(offscreen_canvas, self.aircraft)
            offscreen_canvas = self.matrix.SwapOnVSync(offscreen_canvas)