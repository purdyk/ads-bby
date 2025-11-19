"""
Listen to dump1090-fa on localhost port 30003 which outputs CSV in the format:
message_type,
transmission_type,
session_id,
aircraft_id,
hex_ident,
flight_id,
generated_date,
generated_time,
logged_date,
logged_time,
callsign,
altitude,
ground_speed,
track,
lat,
lon,
vertical_rate,
squawk,
alert,
emergency,
spi,
is_on_ground

Translates this into the OpenSkyData model.
Keeps a dict of all current aircraft based on hex_ident and expires them if no messages in the last 15 minutes.
Can have a hook to output states once every N seconds (configurable).
Runs in its own thread and retries failed connections to the port once every 30 seconds.
"""

import socket
import threading
import time
from typing import Dict, Optional, Callable, List
from datetime import datetime
from bby.models.Aircraft import OpenSkyData


class DumpSlurp:
    """
    Listens to dump1090-fa's raw output on port 30003 and converts CSV messages
    to OpenSkyData objects.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 30003,
        expire_seconds: int = 900,  # 15 minutes
        state_callback: Optional[Callable[[List[OpenSkyData]], None]] = None,
        state_callback_interval: float = 1.0,  # seconds
    ):
        """
        Initialize the DumpSlurp listener.

        Args:
            host: Host to connect to (default: localhost)
            port: Port to connect to (default: 30003)
            expire_seconds: Seconds before aircraft is expired (default: 900 = 15 minutes)
            state_callback: Optional callback function to receive aircraft states
            state_callback_interval: Seconds between state callback invocations
        """
        self.host = host
        self.port = port
        self.expire_seconds = expire_seconds
        self.state_callback = state_callback
        self.state_callback_interval = state_callback_interval

        self.aircraft: Dict[str, OpenSkyData] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callback_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self):
        """Start the listener thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        if self.state_callback:
            self._callback_thread = threading.Thread(target=self._callback_loop, daemon=True)
            self._callback_thread.start()

    def stop(self):
        """Stop the listener thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        if self._callback_thread:
            self._callback_thread.join(timeout=5)

    def get_aircraft(self) -> List[OpenSkyData]:
        """Get current list of tracked aircraft."""
        with self._lock:
            return list(self.aircraft.values())

    def _callback_loop(self):
        """Periodically invoke the state callback with current aircraft list."""
        while self._running:
            time.sleep(self.state_callback_interval)
            if self.state_callback:
                aircraft_list = self.get_aircraft()
                try:
                    self.state_callback(aircraft_list)
                except Exception as e:
                    print(f"Error in state callback: {e}")

    def _run(self):
        """Main loop that connects to dump1090 and processes messages."""
        while self._running:
            try:
                print(f"Connecting to dump1090 at {self.host}:{self.port}...")
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect((self.host, self.port))
                print("Connected to dump1090")

                buffer = ""
                while self._running:
                    try:
                        data = sock.recv(4096)
                        if not data:
                            print("Connection closed by dump1090")
                            break

                        buffer += data.decode('utf-8', errors='ignore')

                        # Process complete lines
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.strip()
                            if line:
                                self._process_message(line)

                        # Periodically clean up expired aircraft
                        self._expire_old_aircraft()

                    except socket.timeout:
                        # Timeout is expected, continue
                        self._expire_old_aircraft()
                        continue
                    except Exception as e:
                        print(f"Error reading from socket: {e}")
                        break

                sock.close()

            except Exception as e:
                print(f"Connection error: {e}")

            if self._running:
                print("Retrying connection in 30 seconds...")
                time.sleep(30)

    def _process_message(self, line: str):
        """Parse a CSV message line and update aircraft state."""
        try:
            fields = line.split(',')

            # Need at least the basic fields
            if len(fields) < 22:
                return

            message_type = fields[0]
            hex_ident = fields[4].strip().lower()

            # Skip if no hex ident
            if not hex_ident:
                return

            # Parse time fields
            generated_date = fields[6].strip() if len(fields) > 6 else ""
            generated_time = fields[7].strip() if len(fields) > 7 else ""
            logged_date = fields[8].strip() if len(fields) > 8 else ""
            logged_time = fields[9].strip() if len(fields) > 9 else ""

            # Parse the logged timestamp (used for last_contact and time_position)
            logged_timestamp = self._parse_timestamp(logged_date, logged_time)
            if logged_timestamp is None:
                # Fallback to current time if parsing fails
                logged_timestamp = int(datetime.now().timestamp())

            # Parse fields (with handling for empty values)
            callsign = fields[10].strip() if len(fields) > 10 and fields[10].strip() else None
            altitude = self._parse_float(fields[11])  # feet
            ground_speed = self._parse_float(fields[12])  # knots
            track = self._parse_float(fields[13])  # degrees
            lat = self._parse_float(fields[14])
            lon = self._parse_float(fields[15])
            vertical_rate = self._parse_float(fields[16])  # feet/min
            squawk = fields[17].strip() if len(fields) > 17 and fields[17].strip() else None
            spi = fields[20].strip() == '1' if len(fields) > 20 else False
            is_on_ground = fields[21].strip() == '1' if len(fields) > 21 else False

            # Convert units to match OpenSkyData format
            baro_altitude = altitude / 3.28084 if altitude is not None else None  # feet to meters
            velocity = ground_speed / 1.94384 if ground_speed is not None else None  # knots to m/s
            vertical_rate_ms = vertical_rate / 196.85 if vertical_rate is not None else None  # fpm to m/s

            with self._lock:
                # Get or create aircraft
                if hex_ident in self.aircraft:
                    aircraft = self.aircraft[hex_ident]
                    opensky = aircraft
                else:
                    # Create new aircraft with OpenSkyData
                    opensky = OpenSkyData(icao24=hex_ident)
                    self.aircraft[hex_ident] = opensky

                # Update last_contact with logged timestamp (always)
                opensky.last_contact = logged_timestamp

                # Update fields based on what's available in this message
                if callsign:
                    opensky.callsign = callsign
                if baro_altitude is not None:
                    opensky.baro_altitude = baro_altitude
                if velocity is not None:
                    opensky.velocity = velocity
                if track is not None:
                    opensky.true_track = track
                if lat is not None:
                    opensky.latitude = lat
                if lon is not None:
                    opensky.longitude = lon
                if vertical_rate_ms is not None:
                    opensky.vertical_rate = vertical_rate_ms
                if squawk:
                    opensky.squawk = squawk

                opensky.spi = spi
                opensky.on_ground = is_on_ground

                # Update time_position when we get position data (using logged timestamp)
                if lat is not None and lon is not None:
                    opensky.time_position = logged_timestamp

        except Exception as e:
            print(f"Error parsing message: {e}")
            print(f"Line: {line}")

    @staticmethod
    def _parse_float(value: str) -> Optional[float]:
        """Parse a string to float, returning None if empty or invalid."""
        value = value.strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    @staticmethod
    def _parse_timestamp(date_str: str, time_str: str) -> Optional[int]:
        """
        Parse dump1090 date and time strings into a Unix timestamp.

        Args:
            date_str: Date string in format YYYY/MM/DD
            time_str: Time string in format HH:MM:SS.mmm

        Returns:
            Unix timestamp as integer, or None if parsing fails
        """
        if not date_str or not time_str:
            return None

        try:
            # Combine date and time
            datetime_str = f"{date_str} {time_str}"

            # Try parsing with milliseconds first
            try:
                dt = datetime.strptime(datetime_str, "%Y/%m/%d %H:%M:%S.%f")
            except ValueError:
                # Try without milliseconds
                dt = datetime.strptime(datetime_str, "%Y/%m/%d %H:%M:%S")

            return int(dt.timestamp())
        except Exception as e:
            print(f"Error parsing timestamp '{date_str} {time_str}': {e}")
            return None

    def _expire_old_aircraft(self):
        """Remove aircraft that haven't been seen in expire_seconds."""
        current_time = datetime.now().timestamp()
        with self._lock:
            expired = [
                icao24 for icao24, aircraft in self.aircraft.items()
                if current_time - aircraft.last_contact > self.expire_seconds
            ]
            for icao24 in expired:
                print(f"Expiring aircraft {icao24}")
                del self.aircraft[icao24]
