from multiprocessing.pool import worker

from PIL import Image, ImageDraw, ImageFont
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
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.Aircraft import Aircraft
from models.Position import Position


class AircraftRenderer:
    """Base class for rendering aircraft information."""

    def __init__(self,  home: Position, width: int, height: int):
        self.home = home
        self.width = width
        self.height = height
        self.frame_count = 0

    def get_strobe_color(self, is_approaching: bool, frame_count: int) -> Tuple[int, int, int]:
        """Get strobing color based on approach status and frame count."""
        # Strobe every 10 frames
        if (frame_count // 10) % 2 == 0:
            return (255, 255, 255)  # White
        else:
            if is_approaching:
                return (0, 255, 0)  # Green for approaching
            else:
                return (255, 0, 0)  # Red for departing

    def format_distance(self, distance_km: Optional[float]) -> str:
        """Format distance for display."""
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
            return ""
        return "↓" if is_approaching else "↑"


class LargeAircraftRenderer(AircraftRenderer):
    """Renderer for the primary aircraft display (top 16 pixels)."""

    def __init__(self, home: Position, width: int = 64, height: int = 16):
        super().__init__(home, width, height)
        try:
            # Try to use a small bitmap font, fallback to default if not available
            self.font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 10)
            self.font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 8)
        except:
            self.font_large = ImageFont.load_default()
            self.font_small = ImageFont.load_default()

    def render(self, aircraft: Aircraft, position: Position,
               image: Image.Image, x: int, y: int, frame_count: int) -> None:
        """Render large aircraft display at specified position."""
        draw = ImageDraw.Draw(image)

        # Calculate current distance from projected position
        distance = self.home.calculate_distance(position)
        is_approaching = position.is_approaching(self.home)

        # Get strobe color for text
        text_color = self.get_strobe_color(is_approaching, frame_count)

        # Line 1: Flight identifier (0-5 pixels)
        flight_name = aircraft.get_display_name()
        draw.text((x + 1, y), flight_name[:8], fill=text_color, font=self.font_small)

        # Direction arrow at the right
        arrow = self.get_direction_arrow(is_approaching)
        if arrow:
            draw.text((x + 58, y), arrow, fill=text_color, font=self.font_small)

        # Line 2: Distance, altitude, speed (6-11 pixels)
        distance_str = self.format_distance(distance)
        altitude_str = f"{int(aircraft.get_altitude_ft() or 0):,}ft" if aircraft.get_altitude_ft() else "--ft"
        speed_str = f"{int(aircraft.get_speed_knots() or 0)}kt" if aircraft.get_speed_knots() else "--kt"

        # Split the line into three parts
        draw.text((x + 1, y + 6), distance_str, fill=text_color, font=self.font_small)
        draw.text((x + 22, y + 6), altitude_str, fill=text_color, font=self.font_small)
        draw.text((x + 44, y + 6), speed_str, fill=text_color, font=self.font_small)

        # Line 3: Aircraft type or category (12-15 pixels)
        if aircraft.flightaware and aircraft.flightaware.aircraft_type:
            type_str = aircraft.flightaware.aircraft_type[:10]
        else:
            type_str = aircraft.get_aircraft_category_name()[:10]
        draw.text((x + 1, y + 12), type_str, fill=text_color, font=self.font_small)

        # Vertical rate indicator on the right
        vrate = aircraft.get_vertical_rate_fpm()
        if vrate:
            if vrate > 100:
                vrate_symbol = "↗"
            elif vrate < -100:
                vrate_symbol = "↘"
            else:
                vrate_symbol = "→"
            draw.text((x + 58, y + 12), vrate_symbol, fill=text_color, font=self.font_small)



class SmallAircraftRenderer(AircraftRenderer):
    """Renderer for secondary aircraft in 16x16 pixel grids."""

    def __init__(self, home: Position, width: int = 16, height: int = 16):
        super().__init__(home, width, height)
        try:
            self.font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 7)
        except:
            self.font = ImageFont.load_default()

    def render(self, aircraft: Aircraft, position: Position,
               image: Image.Image, x: int, y: int, frame_count: int) -> None:
        """Render small aircraft display in 16x16 grid."""
        draw = ImageDraw.Draw(image)

        # Calculate current distance
        distance = self.home.calculate_distance(position)
        is_approaching = position.is_approaching(self.home)

        # Get strobe color
        text_color = self.get_strobe_color(is_approaching, frame_count)

        # Draw border for this aircraft cell
        draw.rectangle([x, y, x + 15, y + 15], outline=(64, 64, 64))

        # Line 1: Shortened flight ID (1-6 pixels)
        flight_name = aircraft.get_display_name()
        if len(flight_name) > 5:
            flight_name = flight_name[:5]
        draw.text((x + 1, y + 1), flight_name, fill=text_color, font=self.font)

        # Line 2: Distance (7-11 pixels)
        distance_str = self.format_distance(distance)[:5]
        draw.text((x + 1, y + 7), distance_str, fill=text_color, font=self.font)

        # Direction indicator (bottom right)
        arrow = "↓" if is_approaching else "↑"
        draw.text((x + 11, y + 10), arrow, fill=text_color, font=self.font)



class DisplayCompositor:
    """Composites multiple aircraft renderers into a single display."""

    def __init__(self, home: Position, width: int = 64, height: int = 32):
        self.width = width
        self.height = height
        self.home =  home
        self.large_renderer = LargeAircraftRenderer(home = home, width = width, height = int(height / 2))
        self.small_renderer = SmallAircraftRenderer(home = home, width = int(width / 4), height = int(height / 2))
        self.frame_count = 0
        try:
            self.font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
        except:
            self.font = ImageFont.load_default()

    def render_frame(self, aircraft_list: List[Aircraft], home_lat: float, home_lon: float) -> Image.Image:
        """Render a complete frame with all aircraft."""
        # Create black background
        image = Image.new('RGB', (self.width, self.height), color=(0, 0, 0))

        if len(aircraft_list) == 0:
            # Show screensaver or "No Aircraft" message
            draw = ImageDraw.Draw(image)

            draw.text((8, 12), "No Aircraft", fill=(128, 128, 128), font=self.font)
            return image

        # Get current positions for all aircraft
        current_time = datetime.now().timestamp()
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
                primary[0], primary[1],
                image, 0, 0, self.frame_count
            )

        # Render up to 4 secondary aircraft in bottom half (2x2 grid of 16x16)
        secondary_positions = [
            (0, 16),   # Top-left
            (16, 16),  # Top-right
            (32, 16),  # Top-right-right
            (48, 16),  # Top-right-right-right
        ]

        for i, pos in enumerate(secondary_positions):
            if i + 1 < len(aircraft_with_positions):
                secondary = aircraft_with_positions[i + 1]
                self.small_renderer.render(
                    secondary[0], secondary[1],
                    image, pos[0], pos[1], self.frame_count
                )

        self.frame_count += 1
        return image
