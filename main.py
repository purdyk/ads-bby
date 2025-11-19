from time import sleep

from bby.api.Hybrid import HybridAPI
from bby.display.Renderer import (DisplayCompositor)
from json import load
from typing import List

from bby.models.Aircraft import Aircraft
from bby.models.BbyCfg import BBYConfig
from bby.models.Position import Position

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

    def enrich(icao24: str) -> None:
        api.request_enrich(icao24)

    compositor = DisplayCompositor(
        home=Position(latitude= config.home.latitude,
                      longitude=config.home.longitude),
        bconfig = config,
        enrich=enrich)

    def on_api_update(new_aircraft: List[Aircraft]) -> None:
        compositor.aircraft = new_aircraft

    api.add_observer(on_api_update)
    api.start()
    compositor.run()

if __name__ == "__main__":
    main()
