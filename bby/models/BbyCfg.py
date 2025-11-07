from dataclasses import dataclass
from typing import Dict, Optional
from models.Position import Position


@dataclass
class DisplayConfig:
    """Configuration for the ADS-BBY display."""
    width: int
    height: int
    mapping: str
    name: str

    def __init__(self, dict: Dict):
        self.width = dict["width"]
        self.height = dict["height"]
        self.mapping = dict["mapping"]
        self.name = dict["name"]


@dataclass
class HomeConfig:
    """Configuration for the ADS-BBY home."""
    latitude: float
    longitude: float
    position: Position

    def __init__(self, dict: Dict):
        self.latitude = dict["latitude"]
        self.longitude = dict["longitude"]
        self.position = Position(longitude=self.longitude, latitude=self.latitude)


@dataclass
class ApiConfig:
    """Configuration for the ADS-BBY API Clients."""
    radius_km: float = 24.99  # Default <25km radius
    opensky_username: Optional[str] = None
    opensky_password: Optional[str] = None
    flightaware_api_key: Optional[str] = None
    opensky_refresh_interval: int = 30  # seconds
    max_flightaware_requests_per_minute: int = 10

@dataclass
class BBYConfig:
    """Configuration for the ADS-BBY system."""
    display: DisplayConfig
    home: HomeConfig
    api: ApiConfig


    def __init__(self, dict: Dict):
        self.display = DisplayConfig(dict['display'])
        self.home = HomeConfig(dict['home'])
        self.api = ApiConfig(dict['api'])
