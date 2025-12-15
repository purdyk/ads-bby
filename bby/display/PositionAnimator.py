from typing import List, Tuple

from rgbmatrix import FrameCanvas

from bby.display.SmallAircraftRenderer import SmallAircraftRenderer
from bby.models.Aircraft import Aircraft
from bby.models.Position import Position


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
    def __init__(self, count: int = 3):
        self.positions: dict[str, AnimationInformation] = {}
        self.count = count
        self.cleanup = 0.0

    def render(self, canvas: FrameCanvas, aircraft: List[Tuple[Aircraft, Position, float]], renderer: SmallAircraftRenderer, y: int, current_time: float) -> None:
        if current_time > self.cleanup:
            self.cleanup = current_time + 10
            included = [x[0].opensky.icao24 for x in aircraft]
            has = list(self.positions.keys())
            for each in has:
                if each not in included:
                    del self.positions[each]

        # Note we're "drawing" 2 offscreen aircraft
        # for the sake of animating them in
        for i in range(0, self.count + 2):
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
                current_info.get_x(current_time), y, current_time)
