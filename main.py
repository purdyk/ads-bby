from time import sleep

from api.Hybrid import HybridAPI
from display.Renderer import (DisplayCompositor)
from json import load
from typing import List

from models.Aircraft import Aircraft
from models.BbyCfg import BBYConfig
from models.Position import Position

def main():
    print("Hello from ads-bby!")
    # Primary entry point for the app
    # This should create API models with appropriate authentication
    # It should set up threads for loading and updating aircraft information from the hybrid API
    # It should pass these into the rendering system at an appropriate refresh interval
    # It should afford the rendering system the resources to draw frequent updates to the display
    config = load(open("config.json"))

    config = BBYConfig(config)
    api = HybridAPI(config)

    compositor = DisplayCompositor(Position(latitude= config.home.latitude, longitude=config.home.longitude))

    def onApiUpdate(newAircraft: List[Aircraft]):
        print(f"found {len(newAircraft)}")
        compositor.aircraft = newAircraft

    api.add_observer(onApiUpdate)
    api.start()
    compositor.run()

if __name__ == "__main__":
    main()
