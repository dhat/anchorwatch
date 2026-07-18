"""Masthead GPS position via the raw NMEA0183 stream on localhost:23000.

This is the masthead GPS unit (6-axis motion corrected, clear view of the
sky) -- it feeds this NMEA stream and a SignalK server from the same
underlying fix. This module parses the stream directly and produces
gpsd.GpsResponse-shaped fixes, so it's a drop-in alternative to
gpsd.get_current() in anchorwatchnew.py, meant to be tried first with the
gpsd-connected in-boat puck as the fallback when this feed is stale/down.
If the connection drops mid-session (or was never up at startup), it
retries automatically -- see NmeaGpsSource's docstring -- so a transient
outage during an unattended overnight anchor watch doesn't permanently
strand the program on the less accurate puck.

GGA, RMC, GSA and VTG sentences are used:
  GGA gives fix quality, lat/lon, satellite count, HDOP, altitude, time.
  RMC gives speed over ground and course, plus an independent A/V validity
    check.
  GSA gives fix dimensionality (2D/3D) and VDOP, and a satellite-used count
    as a fallback if a GGA hasn't arrived yet this cycle.
  VTG also gives speed over ground and course. Some multiplexers (this
    boat's masthead unit among them) never emit RMC at all -- only GGA,
    GSA/GSV-less position sentences, and VTG for speed/track -- so relying
    on RMC alone silently left speed stuck at 0 on that feed. Whichever of
    RMC/VTG is actually present updates speed/track; if both arrive, the
    most recent one wins, same as every other field here.
There's no GST sentence assumed available, so horizontal/vertical position
error estimates are approximated from HDOP/VDOP using a typical single-
frequency GPS accuracy figure rather than a measured value. NMEA has no
standard speed-error sentence at all (gpsd's eps is derived internally,
not read off the wire), so speed error is approximated the same way,
scaled by HDOP.
"""
import socket
import time as time_module

import pynmea2

import gpsd

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 23000

# How long without a usable sentence before treating the feed as down.
DEFAULT_STALE_AFTER = 5.0

# How long to wait between reconnect attempts while the feed is down. Needs
# to be a real throttle: connect() can block for its own timeout (below) on
# each attempt, so retrying every loop tick during a real outage would stall
# the whole alarm loop by that much on every single tick.
DEFAULT_RECONNECT_INTERVAL = 30.0

# Timeout for establishing the TCP connection itself (connect(), not reads).
CONNECT_TIMEOUT = 5.0

# Rough single-frequency GPS user equivalent range error, in meters (95%),
# used to turn a DOP value into an epx/epy/epv-style estimate when the
# stream has no GST sentence to give a measured accuracy figure directly.
DEFAULT_UERE_METERS = 5.0

# Rough single-frequency GPS speed accuracy, in m/s, at HDOP=1 -- there's no
# NMEA sentence for this at all, so it's approximated the same way position
# error is: scaled by HDOP as a stand-in for "how good is the fix right now".
DEFAULT_SPEED_UERE_MPS = 0.5

KNOTS_TO_MPS = 0.514444


class NmeaGpsSource:
    """Parses a live NMEA0183 stream into gpsd.GpsResponse-shaped fixes.

    Call connect() once, then get_current() each loop tick, same shape as
    gpsd.get_current(). If the connection drops (or the initial connect()
    failed), get_current() retries it automatically, throttled to at most
    once per reconnect_interval, so a real outage can't stall the caller's
    loop by repeatedly blocking on a fresh connection attempt every tick.
    ingest_line() is exposed separately so tests can feed sentences directly
    without a real socket.
    """

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, stale_after=DEFAULT_STALE_AFTER,
                 reconnect_interval=DEFAULT_RECONNECT_INTERVAL):
        self.host = host
        self.port = port
        self.stale_after = stale_after
        self.reconnect_interval = reconnect_interval
        self._sock = None
        self._buffer = b""
        self._last_sentence_at = None
        self._last_connect_attempt_at = None

        self._fix_quality = 0    # GGA gps_qual: 0=invalid, 1=GPS, 2=DGPS, 4/5=RTK, ...
        self._fix_dimension = 0  # GSA mode_fix_type: 1=no fix, 2=2D, 3=3D
        self._lat = 0.0
        self._lon = 0.0
        self._alt = 0.0
        self._time = ''
        self._sats_used = 0
        self._hdop = 0.0
        self._vdop = 0.0
        self._speed_mps = 0.0
        self._track = 0.0

    def connect(self):
        self._sock = socket.create_connection((self.host, self.port), timeout=CONNECT_TIMEOUT)
        self._sock.settimeout(0.2)
        self._buffer = b""

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
                self._buffer = b""

    def ingest_line(self, raw_line):
        """Parse one raw NMEA sentence and fold it into the running fix state."""
        if not raw_line:
            return
        try:
            msg = pynmea2.parse(raw_line)
        except pynmea2.ParseError:
            return

        sentence = getattr(msg, 'sentence_type', '')
        if sentence == 'GGA':
            self._ingest_gga(msg)
        elif sentence == 'RMC':
            self._ingest_rmc(msg)
        elif sentence == 'GSA':
            self._ingest_gsa(msg)
        elif sentence == 'VTG':
            self._ingest_vtg(msg)
        else:
            return
        self._last_sentence_at = time_module.monotonic()

    def _ingest_gga(self, msg):
        self._fix_quality = msg.gps_qual or 0
        if self._fix_quality > 0:
            self._lat = msg.latitude
            self._lon = msg.longitude
            if msg.altitude is not None:
                self._alt = msg.altitude
        if msg.num_sats:
            try:
                self._sats_used = int(msg.num_sats)
            except ValueError:
                pass
        if msg.horizontal_dil:
            try:
                self._hdop = float(msg.horizontal_dil)
            except ValueError:
                pass
        if msg.timestamp:
            self._time = msg.timestamp.isoformat()

    def _ingest_rmc(self, msg):
        if msg.status == 'A':
            if msg.spd_over_grnd is not None:
                self._speed_mps = msg.spd_over_grnd * KNOTS_TO_MPS
            if msg.true_course is not None:
                self._track = msg.true_course

    def _ingest_vtg(self, msg):
        # faa_mode is a NMEA 2.3+ addition: 'N' means "not valid", blank/
        # absent means the sentence predates that field (treat as valid,
        # same as the rest of this pre-2.3-friendly parser).
        if getattr(msg, 'faa_mode', None) == 'N':
            return
        if msg.spd_over_grnd_kts is not None:
            self._speed_mps = float(msg.spd_over_grnd_kts) * KNOTS_TO_MPS
        if msg.true_track is not None:
            self._track = msg.true_track

    def _ingest_gsa(self, msg):
        if msg.mode_fix_type:
            try:
                self._fix_dimension = int(msg.mode_fix_type)
            except ValueError:
                pass
        if msg.vdop:
            try:
                self._vdop = float(msg.vdop)
            except ValueError:
                pass
        sv_ids = [getattr(msg, 'sv_id%02d' % i, '') for i in range(1, 13)]
        used = len([sv for sv in sv_ids if sv])
        if used:
            self._sats_used = used

    def is_stale(self):
        return self._last_sentence_at is None or (
            time_module.monotonic() - self._last_sentence_at > self.stale_after
        )

    def get_current(self):
        if self._sock is None:
            self._maybe_reconnect()
        if self._sock is not None:
            self._drain_available_lines()
        return self._build_fix()

    def _maybe_reconnect(self):
        now = time_module.monotonic()
        if (self._last_connect_attempt_at is not None
                and now - self._last_connect_attempt_at < self.reconnect_interval):
            return
        self._last_connect_attempt_at = now
        try:
            self.connect()
        except OSError:
            self._sock = None

    def _drain_available_lines(self):
        # Deliberately not using socket.makefile()/readline() here: once a
        # read on that file-like wrapper times out once, every subsequent
        # read raises OSError("cannot read from timed out object") instead
        # of a normal timeout (a longstanding CPython socket module quirk),
        # which would permanently break this after its very first empty read.
        # Reading raw bytes off the socket directly and splitting lines
        # ourselves doesn't have that problem.
        while True:
            try:
                chunk = self._sock.recv(4096)
            except (socket.timeout, BlockingIOError):
                return
            if not chunk:
                # Peer closed the connection; go stale and let the caller's
                # fallback-to-gpsd path take over rather than erroring here.
                self.close()
                return
            self._buffer += chunk
            while b"\n" in self._buffer:
                line, _, self._buffer = self._buffer.partition(b"\n")
                self.ingest_line(line.decode('ascii', errors='replace').strip())

    def _build_fix(self):
        fix = gpsd.GpsResponse()

        if self.is_stale():
            fix.mode = 0
        elif self._fix_quality <= 0:
            fix.mode = 1
        elif self._fix_dimension in (2, 3):
            fix.mode = self._fix_dimension
        else:
            fix.mode = 3

        fix.lat = self._lat
        fix.lon = self._lon
        fix.alt = self._alt
        fix.track = self._track
        fix.hspeed = self._speed_mps
        fix.sats = self._sats_used
        fix.sats_valid = self._sats_used
        fix.time = self._time

        epx = self._hdop * DEFAULT_UERE_METERS if self._hdop else 10.0
        epv = self._vdop * DEFAULT_UERE_METERS if self._vdop else epx * 1.5
        eps = self._hdop * DEFAULT_SPEED_UERE_MPS if self._hdop else DEFAULT_SPEED_UERE_MPS * 2
        fix.error = {'x': epx, 'y': epx, 'v': epv, 's': eps, 'c': 0.0, 't': 0.01}

        return fix
