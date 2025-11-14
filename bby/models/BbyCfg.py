from dataclasses import dataclass
from typing import Dict, Optional
from bby.models.Position import Position

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
    opensky_client_id: Optional[str] = None
    opensky_client_secret: Optional[str] = None
    flightaware_api_key: Optional[str] = None
    quiet_start: Optional[int] = None
    quiet_end: Optional[int] = None
    opensky_refresh_interval: int = 30  # seconds
    max_flightaware_requests_per_minute: int = 10

    def __init__(self, dict: Dict):
        self.radius_km = dict["radius_km"]
        self.opensky_username = dict["opensky_username"]
        self.opensky_password = dict["opensky_password"]
        self.opensky_client_id = dict["opensky_client_id"]
        self.opensky_client_secret = dict["opensky_client_secret"]
        self.flightaware_api_key = dict["flightaware_api_key"]
        self.quiet_start = dict["quiet_start"]
        self.quiet_end = dict["quiet_end"]
        self.opensky_refresh_interval = dict["opensky_refresh_interval"]
        self.max_flightaware_requests_per_minute = dict["max_flightaware_requests_per_minute"]

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
