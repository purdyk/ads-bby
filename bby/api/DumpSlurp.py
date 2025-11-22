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
import json
import urllib.request
import urllib.error
from typing import Dict, Optional, Callable, List, Tuple
from datetime import datetime
from bby.models.Aircraft import OpenSkyData


# ICAO24 address allocation ranges by country
# Source: https://github.com/rikgale/ICAOList/blob/main/ICAOHexRange.csv
# Format: (start_hex, end_hex, country_code, country_name)
ICAO24_RANGES: List[Tuple[str, str, str, str]] = [
    ("000000", "003FFF", "", "Unallocated"),
    ("004000", "0043FF", "ZW", "Zimbabwe"),
    ("006000", "006FFF", "MZ", "Mozambique"),
    ("008000", "00FFFF", "ZA", "South Africa"),
    ("010000", "017FFF", "EG", "Egypt"),
    ("018000", "01FFFF", "LY", "Libya"),
    ("020000", "027FFF", "MA", "Morocco"),
    ("028000", "02FFFF", "TN", "Tunisia"),
    ("030000", "0303FF", "BW", "Botswana"),
    ("032000", "032FFF", "BI", "Burundi"),
    ("034000", "034FFF", "CM", "Cameroon"),
    ("035000", "0353FF", "KM", "Comoros"),
    ("036000", "036FFF", "CG", "Congo"),
    ("038000", "038FFF", "CI", "Côte d'Ivoire"),
    ("03E000", "03EFFF", "GA", "Gabon"),
    ("040000", "040FFF", "ET", "Ethiopia"),
    ("042000", "042FFF", "GQ", "Equatorial Guinea"),
    ("044000", "044FFF", "GH", "Ghana"),
    ("046000", "046FFF", "GN", "Guinea"),
    ("048000", "0483FF", "GW", "Guinea-Bissau"),
    ("04A000", "04A3FF", "LS", "Lesotho"),
    ("04C000", "04CFFF", "KE", "Kenya"),
    ("050000", "050FFF", "LR", "Liberia"),
    ("054000", "054FFF", "MG", "Madagascar"),
    ("058000", "058FFF", "MW", "Malawi"),
    ("05A000", "05A3FF", "MV", "Maldives"),
    ("05C000", "05CFFF", "ML", "Mali"),
    ("05E000", "05E3FF", "MR", "Mauritania"),
    ("060000", "0603FF", "MU", "Mauritius"),
    ("062000", "062FFF", "NE", "Niger"),
    ("064000", "064FFF", "NG", "Nigeria"),
    ("068000", "068FFF", "UG", "Uganda"),
    ("06A000", "06A3FF", "QA", "Qatar"),
    ("06C000", "06CFFF", "CF", "Central African Republic"),
    ("06E000", "06EFFF", "RW", "Rwanda"),
    ("070000", "070FFF", "SN", "Senegal"),
    ("074000", "0743FF", "SC", "Seychelles"),
    ("076000", "0763FF", "SL", "Sierra Leone"),
    ("078000", "078FFF", "SO", "Somalia"),
    ("07A000", "07A3FF", "SZ", "Eswatini"),
    ("07C000", "07CFFF", "SD", "Sudan"),
    ("080000", "080FFF", "TZ", "Tanzania"),
    ("084000", "084FFF", "TD", "Chad"),
    ("088000", "088FFF", "TG", "Togo"),
    ("08A000", "08AFFF", "ZM", "Zambia"),
    ("08C000", "08CFFF", "CD", "DR Congo"),
    ("090000", "090FFF", "AO", "Angola"),
    ("094000", "0943FF", "BJ", "Benin"),
    ("096000", "0963FF", "CV", "Cape Verde"),
    ("098000", "0983FF", "DJ", "Djibouti"),
    ("09A000", "09AFFF", "GM", "Gambia"),
    ("09C000", "09CFFF", "BF", "Burkina Faso"),
    ("09E000", "09E3FF", "ST", "São Tomé"),
    ("0A0000", "0A7FFF", "DZ", "Algeria"),
    ("0A8000", "0A8FFF", "BS", "Bahamas"),
    ("0AA000", "0AA3FF", "BB", "Barbados"),
    ("0AB000", "0AB3FF", "BZ", "Belize"),
    ("0AC000", "0ACFFF", "CO", "Colombia"),
    ("0AE000", "0AEFFF", "CR", "Costa Rica"),
    ("0B0000", "0B0FFF", "CU", "Cuba"),
    ("0B2000", "0B2FFF", "SV", "El Salvador"),
    ("0B4000", "0B4FFF", "GT", "Guatemala"),
    ("0B6000", "0B6FFF", "GY", "Guyana"),
    ("0B8000", "0B8FFF", "HT", "Haiti"),
    ("0BA000", "0BAFFF", "HN", "Honduras"),
    ("0BC000", "0BC3FF", "VC", "St. Vincent & Grenadines"),
    ("0BE000", "0BEFFF", "JM", "Jamaica"),
    ("0C0000", "0C0FFF", "NI", "Nicaragua"),
    ("0C2000", "0C2FFF", "PA", "Panama"),
    ("0C4000", "0C4FFF", "DO", "Dominican Republic"),
    ("0C6000", "0C6FFF", "TT", "Trinidad and Tobago"),
    ("0C8000", "0C8FFF", "SR", "Suriname"),
    ("0CA000", "0CA3FF", "AG", "Antigua & Barbuda"),
    ("0CC000", "0CC3FF", "GD", "Grenada"),
    ("0D0000", "0D7FFF", "MX", "Mexico"),
    ("0D8000", "0DFFFF", "VE", "Venezuela"),
    ("100000", "1FFFFF", "RU", "Russia"),
    ("201000", "2013FF", "NA", "Namibia"),
    ("202000", "2023FF", "ER", "Eritrea"),
    ("300000", "33FFFF", "IT", "Italy"),
    ("340000", "37FFFF", "ES", "Spain"),
    ("380000", "3BFFFF", "FR", "France"),
    ("3C0000", "3FFFFF", "DE", "Germany"),
    ("400000", "43FFFF", "GB", "United Kingdom"),
    ("440000", "447FFF", "AT", "Austria"),
    ("448000", "44FFFF", "BE", "Belgium"),
    ("450000", "457FFF", "BG", "Bulgaria"),
    ("458000", "45FFFF", "DK", "Denmark"),
    ("460000", "467FFF", "FI", "Finland"),
    ("468000", "46FFFF", "GR", "Greece"),
    ("470000", "477FFF", "HU", "Hungary"),
    ("478000", "47FFFF", "NO", "Norway"),
    ("480000", "487FFF", "NL", "Netherlands"),
    ("488000", "48FFFF", "PL", "Poland"),
    ("490000", "497FFF", "PT", "Portugal"),
    ("498000", "49FFFF", "CZ", "Czech Republic"),
    ("4A0000", "4A7FFF", "RO", "Romania"),
    ("4A8000", "4AFFFF", "SE", "Sweden"),
    ("4B0000", "4B7FFF", "CH", "Switzerland"),
    ("4B8000", "4BFFFF", "TR", "Turkey"),
    ("4C0000", "4C7FFF", "YU", "Yugoslavia"),
    ("4C8000", "4C83FF", "CY", "Cyprus"),
    ("4CA000", "4CAFFF", "IE", "Ireland"),
    ("4CC000", "4CCFFF", "IS", "Iceland"),
    ("4D0000", "4D03FF", "LU", "Luxembourg"),
    ("4D2000", "4D23FF", "MT", "Malta"),
    ("4D4000", "4D43FF", "MC", "Monaco"),
    ("500000", "5003FF", "SM", "San Marino"),
    ("501000", "5013FF", "AL", "Albania"),
    ("501C00", "501FFF", "HR", "Croatia"),
    ("502C00", "502FFF", "LV", "Latvia"),
    ("503C00", "503FFF", "LT", "Lithuania"),
    ("504C00", "504FFF", "MD", "Moldova"),
    ("505C00", "505FFF", "SK", "Slovakia"),
    ("506C00", "506FFF", "SI", "Slovenia"),
    ("507C00", "507FFF", "UZ", "Uzbekistan"),
    ("508000", "50FFFF", "UA", "Ukraine"),
    ("510000", "5103FF", "BY", "Belarus"),
    ("511000", "5113FF", "EE", "Estonia"),
    ("512000", "5123FF", "MK", "North Macedonia"),
    ("513000", "5133FF", "BA", "Bosnia & Herzegovina"),
    ("514000", "5143FF", "GE", "Georgia"),
    ("515000", "5153FF", "TJ", "Tajikistan"),
    ("600000", "6003FF", "AM", "Armenia"),
    ("600800", "600BFF", "AZ", "Azerbaijan"),
    ("601000", "6013FF", "KG", "Kyrgyzstan"),
    ("601800", "601BFF", "TM", "Turkmenistan"),
    ("680000", "6803FF", "BT", "Bhutan"),
    ("681000", "6813FF", "FM", "Micronesia"),
    ("682000", "6823FF", "MN", "Mongolia"),
    ("683000", "6833FF", "KZ", "Kazakhstan"),
    ("684000", "6843FF", "PW", "Palau"),
    ("700000", "700FFF", "AF", "Afghanistan"),
    ("702000", "702FFF", "BD", "Bangladesh"),
    ("704000", "704FFF", "MM", "Myanmar"),
    ("706000", "706FFF", "KW", "Kuwait"),
    ("708000", "708FFF", "LA", "Laos"),
    ("70A000", "70AFFF", "NP", "Nepal"),
    ("70C000", "70C3FF", "OM", "Oman"),
    ("70E000", "70EFFF", "KH", "Cambodia"),
    ("710000", "717FFF", "SA", "Saudi Arabia"),
    ("718000", "71FFFF", "KR", "South Korea"),
    ("720000", "727FFF", "KP", "North Korea"),
    ("728000", "72FFFF", "IQ", "Iraq"),
    ("730000", "737FFF", "IR", "Iran"),
    ("738000", "73FFFF", "IL", "Israel"),
    ("740000", "747FFF", "JO", "Jordan"),
    ("748000", "74FFFF", "LB", "Lebanon"),
    ("750000", "757FFF", "MY", "Malaysia"),
    ("758000", "75FFFF", "PH", "Philippines"),
    ("760000", "767FFF", "PK", "Pakistan"),
    ("768000", "76FFFF", "SG", "Singapore"),
    ("770000", "777FFF", "LK", "Sri Lanka"),
    ("778000", "77FFFF", "SY", "Syria"),
    ("780000", "7BFFFF", "CN", "China"),
    ("7C0000", "7FFFFF", "AU", "Australia"),
    ("800000", "83FFFF", "IN", "India"),
    ("840000", "87FFFF", "JP", "Japan"),
    ("880000", "887FFF", "TH", "Thailand"),
    ("888000", "88FFFF", "VN", "Vietnam"),
    ("890000", "890FFF", "YE", "Yemen"),
    ("894000", "894FFF", "BH", "Bahrain"),
    ("895000", "8953FF", "BN", "Brunei"),
    ("896000", "896FFF", "AE", "United Arab Emirates"),
    ("897000", "8973FF", "SB", "Solomon Islands"),
    ("898000", "898FFF", "PG", "Papua New Guinea"),
    ("899000", "8993FF", "TW", "Taiwan"),
    ("8A0000", "8A7FFF", "ID", "Indonesia"),
    ("900000", "9003FF", "MH", "Marshall Islands"),
    ("901000", "9013FF", "CK", "Cook Islands"),
    ("902000", "9023FF", "WS", "Samoa"),
    ("A00000", "AFFFFF", "US", "United States"),
    ("C00000", "C3FFFF", "CA", "Canada"),
    ("C80000", "C87FFF", "NZ", "New Zealand"),
    ("C88000", "C88FFF", "FJ", "Fiji"),
    ("C8A000", "C8A3FF", "NR", "Nauru"),
    ("C8C000", "C8C3FF", "LC", "Saint Lucia"),
    ("C8D000", "C8D3FF", "TO", "Tonga"),
    ("C8E000", "C8E3FF", "KI", "Kiribati"),
    ("C90000", "C903FF", "VU", "Vanuatu"),
    ("E00000", "E3FFFF", "AR", "Argentina"),
    ("E40000", "E7FFFF", "BR", "Brazil"),
    ("E80000", "E80FFF", "CL", "Chile"),
    ("E84000", "E84FFF", "EC", "Ecuador"),
    ("E88000", "E88FFF", "PY", "Paraguay"),
    ("E8C000", "E8CFFF", "PE", "Peru"),
    ("E90000", "E90FFF", "UY", "Uruguay"),
    ("E94000", "E94FFF", "BO", "Bolivia"),
    ("F00000", "F07FFF", "ICAO", "ICAO"),
    ("F09000", "F093FF", "ICAO", "ICAO"),
]

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

        # Cache for aircraft type database lookups
        # Key: 3-character hex prefix, Value: dict mapping suffix to aircraft data
        self._type_database_cache: Dict[str, Dict[str, dict]] = {}
        self._type_cache_lock = threading.Lock()

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
                    opensky = OpenSkyData(icao24=hex_ident, source=1, origin_country=self.get_country_from_icao24(hex_ident))
                    self.aircraft[hex_ident] = opensky
                    opensky.aircraft_type = self.get_aircraft_type_from_icao24(hex_ident)

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
                    opensky.last_position = logged_timestamp

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

    def get_country_from_icao24(self, icao24: str) -> Optional[str]:
        """
        Determine the country of registration from an ICAO24 hex address.

        Args:
            icao24: The ICAO24 hex address (6 hex characters)

        Returns:
            Tuple of (country_code, country_name) or None if not found
        """
        # Normalize the input
        icao24 = icao24.strip().upper().replace(" ", "")

        # Pad to 6 characters if needed
        if len(icao24) < 6:
            icao24 = icao24.ljust(6, '0')

        # Convert to integer for comparison
        try:
            icao_int = int(icao24[:6], 16)
        except ValueError:
            return None

        # Binary search through ranges
        for start_hex, end_hex, country_code, country_name in ICAO24_RANGES:
            start_int = int(start_hex, 16)
            end_int = int(end_hex, 16)

            if start_int <= icao_int <= end_int:
                # print(f"Found country of registration from {icao24}: {country_name}")
                return country_name

        return None

    def get_aircraft_type_from_icao24(
            self,
            icao24: str,

    ) -> Optional[str]:
        """
        Look up aircraft type from local database server.

        Args:
            icao24: The ICAO24 hex address (6 hex characters)
            database_host: Host for the aircraft database (default: localhost)
            database_port: Port for the aircraft database (default: 8080)
            timeout: Request timeout in seconds (default: 2.0)

        Returns:
            Aircraft type string or None if not found
        """
        # Normalize the input
        icao24 = icao24.strip().upper().replace(" ", "")

        # Need at least 6 characters
        if len(icao24) < 6:
            icao24 = icao24.ljust(6, '0')

        return self._fetch_aircraft(icao24, 1)

    def _fetch_aircraft(self, icao24: str, split: int,
                        database_host: str = "localhost",
                        database_port: int = 8080,
                        timeout: float = 2.0) -> Optional[str]:

        # Split into prefix (first 3 chars) and suffix (last 3 chars)
        prefix = icao24[:split]
        suffix = icao24[split:]

        entry = None

        # Check cache first
        with self._type_cache_lock:
            if prefix in self._type_database_cache:
                entry = self._type_database_cache[prefix]

        # Fetch from database server
        if entry is None:
            try:
                url = f"http://{database_host}:{database_port}/db/{prefix}.json"
                req = urllib.request.Request(url)

                # print(f"fetching {url}")

                with urllib.request.urlopen(req, timeout=timeout) as response:
                    entry = json.loads(response.read().decode('utf-8'))

                    # print(f"loaded data, caching")

                    # Cache the entire database for this prefix
                    with self._type_cache_lock:
                        self._type_database_cache[prefix] = entry

            except urllib.error.HTTPError as e:
                if e.code != 404:
                    print(f"HTTP error fetching aircraft type for {icao24}: {e.code}")
            except urllib.error.URLError as e:
                print(f"URL error fetching aircraft type for {icao24}: {e}")
            except json.JSONDecodeError as e:
                print(f"JSON decode error for {icao24}: {e}")
            except Exception as e:
                print(f"Unexpected error fetching aircraft type for {icao24}: {e}")

        if not entry:
            return None

        if suffix in entry:
            t = entry[suffix].get('t')
            # print(f"Found aircraft type from database: {t}")
            return t

        if "children" in entry:
            sub = icao24[:split+1]
            if sub in entry["children"]:
                return self._fetch_aircraft(icao24, split+1)

        return None

