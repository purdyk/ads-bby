import time
from datetime import datetime
from typing import List, Optional, Tuple

from PIL import Image
from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions, FrameCanvas

from bby.models.Aircraft import Aircraft
from bby.models.BbyCfg import DisplayConfig
from bby.models.Position import Position


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
        scale = (factor * 100)
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
            self.font_large.LoadFont("bby/fonts/6x10.bdf")
            self.font_small = graphics.Font()
            self.font_small.LoadFont("bby/fonts/4x6.bdf")
            self.first_offset = self.font_large.height - 3
            self.second_offset = self.font_large.height + self.font_small.height - 3
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

        line1a = f"{flight_name[:6]}"
        line1b = f"{distance_str}"
        off = graphics.DrawText(canvas, self.font_large, x, y + self.first_offset, text_color, line1a)
        off += graphics.DrawText(canvas, self.font_large, x + off + 2, y + self.first_offset, text_color, line1b)

        # Line 2: Aircraft type, Origin, Destination, V-rate
        line2 = f"{aircraft.get_type()[:7]}:{aircraft.get_origin_airport()}-{aircraft.get_dest_airport()}:{speed_str}"
        graphics.DrawText(canvas, self.font_small, x, y + self.second_offset, text_color, line2)

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

class AircraftGraphRenderer(AircraftRenderer):
    def __init__(self, home: Position, width: int, height: int, range_km: int):
        super().__init__(home, width, height)
        # 50 km to draw
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
            scale = canvas.width * (aircraft[2] / self.range)
            if is_approaching:
                color = self.green
            else:
                color = self.red
            self.draw_block(canvas, scale, y, color)

class ScreenRenderer(AircraftRenderer):
    def __init__(self, home: Position, width: int, height: int, name: str):
        super().__init__(home, width, height)
        self.name = name
        try:
            self.font = graphics.Font()
            self.font.LoadFont("bby/fonts/6x10.bdf")
            self.image = Image.open("bby/images/cub2.ppm").convert("RGB")
            self.imgwidth = self.image.size[0]
        except:
            print("Failed to load font, yikes")

    def render(self, canvas: FrameCanvas, current_time: float) -> None:
        graphics.DrawText(canvas, self.font, 0, 0 + self.font.height + 1, graphics.Color(255,255,255), self.name)
        x_pos = (current_time * 10) % self.imgwidth
        y_pos = abs((int(current_time) % 4) - 2) - 1
        canvas.SetImage(self.image, -x_pos, y_pos, unsafe=False)
        if x_pos > self.imgwidth - self.width:
            canvas.SetImage(self.image, -x_pos + self.imgwidth, y_pos, unsafe=False)
        graphics.DrawText(canvas, self.font, -x_pos + 92, 16 + (self.font.height / 2) + y_pos, graphics.Color(0,0,0), self.name)

class AnimationInformation:
    destination: int
    source: int
    started: float

    def __init__(self, destination: int, source: int, started: float) -> None:
        self.destination = destination
        self.source = source
        self.started = started
        self.complete = destination < 0 and source > 3
        self.x_size = 22
        self.duration = 0.5
        self.x_dest = (self.destination * self.x_size)
        self.x_src = (self.source * self.x_size)
        self.x_off = (self.x_size * (self.destination - self.source))

    def get_x(self, current_time: float) -> int:
        delta = current_time - self.started
        if delta >= self.duration:
            self.complete = True

        if self.complete:
            return self.x_dest
        else:
            # make 2 square it, then divide by 4 gives exponential?
            scale = (((delta / self.duration)*10)**3)/1000.0
            offset = scale * self.x_off
            x_out = int(self.x_src + offset)
            #print(f"Anim {self.source} -> {self.destination}: {self.x_src} + {offset} = {x_out}")
            return x_out

class PositionAnimator:
    def __init__(self):
        self.positions: dict[str, AnimationInformation] = {}
        self.y_pos = 19
        self.cleanup = 0.0

    def render(self, canvas: FrameCanvas, aircraft: List[Tuple[Aircraft, Position, float]], renderer: SmallAircraftRenderer, current_time: float) -> None:
        if current_time > self.cleanup:
            self.cleanup = current_time + 10
            included = [x[0].opensky.icao24 for x in aircraft]
            has = list(self.positions.keys())
            for each in has:
                if each not in included:
                    del self.positions[each]

        # Note we're drawing 2 offscreen aircraft
        for i in range(0, 6):
            if i == len(aircraft):
                break

            info = aircraft[i]
            craft = info[0]
            current_info = self.positions.get(craft.opensky.icao24, None)

            # Offset dest
            dest = i - 1

            if current_info is not None and current_info.destination != dest:
                current_info = AnimationInformation(dest, current_info.destination, current_time)
                self.positions[craft.opensky.icao24] = current_info

            elif current_info is None:
                current_info = AnimationInformation(dest, 5, current_time)
                self.positions[craft.opensky.icao24] = current_info

            renderer.render(
                info[0], info[1], info[2],canvas,
                current_info.get_x(current_time), self.y_pos, current_time)

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
        self.graph = AircraftGraphRenderer(home = home, width = self.width, height = 5, range_km=50)
        self.screensaver = ScreenRenderer(home = home, width = self.width, height = self.height, name = config.name)
        self.animator = PositionAnimator()
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


    def render_frame(self, canvas: FrameCanvas, aircraft_list: List[Aircraft]) -> None:
        """Render a complete frame with all aircraft."""
        # Create black background
        canvas.Clear()

        # Get current positions for all aircraft
        current_time = datetime.now().timestamp()

        if len(aircraft_list) == 0:
            self.screensaver.render(canvas, current_time)
            return

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

        # Render a graph in the middle
        self.graph.render(canvas, 0, 14, aircraft_with_positions)

        # Render the bottom row of aircraft
        self.animator.render(canvas, aircraft_with_positions, self.small_renderer, current_time)

    def run(self):
        # Maybe init a few things
        offscreen_canvas = self.matrix.CreateFrameCanvas()

        while True:
            self.render_frame(offscreen_canvas, self.aircraft)
            offscreen_canvas = self.matrix.SwapOnVSync(offscreen_canvas)
            time.sleep(0.02)