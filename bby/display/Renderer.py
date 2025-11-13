import time
from datetime import datetime
from typing import List, Tuple, Callable

from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions, FrameCanvas

from bby.display.AircraftGraphRenderer import AircraftGraphRenderer
from bby.display.LargeAircraftRenderer import LargeAircraftRenderer
from bby.display.PositionAnimator import PositionAnimator
from bby.display.ScreenRenderer import ScreenRenderer
from bby.display.SmallAircraftRenderer import SmallAircraftRenderer
from bby.models.Aircraft import Aircraft
from bby.models.BbyCfg import BBYConfig
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


class DisplayCompositor:
    """Composites multiple aircraft renderers into a single display."""

    """
    Clients can set this property to update the list of rendered aircrafts.
    The compositor will choose which to display, and what properties to show.
    It expects timestamps on the aircraft to be relevant to local time for extrapolation.
    
    """
    aircraft: List[Aircraft]

    def __init__(self, home: Position, bconfig: BBYConfig, enrich: Callable[[str], None]):
        config = bconfig.display
        self.width = config.width
        self.height = config.height
        self.home =  home
        self.large_renderer = LargeAircraftRenderer(home = home, width = self.width, height = int(self.height / 2))
        self.small_renderer = SmallAircraftRenderer(home = home, width = int(self.width / 4), height = int(self.height / 2))
        self.request_enrich = enrich

        # API radius is actually an x+y range, farthest possible is a hypotenuse
        # So graph range should reflect this
        hyp = ((bconfig.api.radius_km**2)*2)**0.5

        self.graph = AircraftGraphRenderer(home = home, width = self.width, height = 5, range_km=hyp)
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

        aircraft_with_positions: List[Tuple[Aircraft, Position, float]] = []

        for aircraft in aircraft_list:
            if aircraft.opensky.last_contact:
                seconds_elapsed = current_time - aircraft.opensky.last_contact
                position = aircraft.extrapolate_position(seconds_elapsed)
                if position:
                    distance = self.home.calculate_distance(position)
                    aircraft_with_positions.append((aircraft, position, distance))

        # Sort by distance
        aircraft_with_positions.sort(key=lambda x: x[2])

        for each in aircraft_with_positions[:4]:
            if each[0].flightaware is None and each[0].opensky.callsign:
                self.request_enrich(each[0].opensky.icao24)

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