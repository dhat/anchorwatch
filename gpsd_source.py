"""Robust wrapper around gpsd-py3, mirroring NmeaGpsSource's interface.

gpsd-py3's connect()/get_current() are bare module-level functions with two
sharp edges this wraps around:

  1. The socket they open has no read timeout. If gpsd dies or the
     connection otherwise goes stale mid-session, a later get_current() call
     can block forever instead of raising -- which would silently freeze the
     whole anchor watch loop (no error, no alarm, nothing). We set a timeout
     on the underlying socket right after connecting so a dead connection
     surfaces as a bounded failure instead of a hang.
  2. Any failure (gpsd not running at startup, connection dropped later)
     raises straight out of get_current(), and gpsd-py3 has no built-in way
     to reconnect -- callers are expected to call connect() again
     themselves. This wraps that in the same throttled-retry pattern
     NmeaGpsSource uses for the masthead feed, and get_current() here never
     raises: it returns a mode=0 gpsd.GpsResponse instead, so a caller's
     normal "invalid fix" handling covers a down gpsd the same way it
     already covers a down masthead feed.
"""
import time as time_module

import gpsd

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 2947

# How long to wait between reconnect attempts while gpsd is unreachable.
DEFAULT_RECONNECT_INTERVAL = 30.0

# Read timeout applied to the gpsd socket after connecting, since gpsd-py3
# itself sets none.
DEFAULT_READ_TIMEOUT = 5.0


class GpsdSource:
    """Wraps gpsd-py3 so a missing/dropped gpsd never raises or hangs the caller.

    connect() is exposed separately (and does raise) so startup code can log
    a clear one-time message; get_current() itself is always safe to call.
    """

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT,
                 reconnect_interval=DEFAULT_RECONNECT_INTERVAL,
                 read_timeout=DEFAULT_READ_TIMEOUT):
        self.host = host
        self.port = port
        self.reconnect_interval = reconnect_interval
        self.read_timeout = read_timeout
        self._connected = False
        self._last_connect_attempt_at = None

    def connect(self):
        """Connect (or raise). Also used internally for throttled reconnects."""
        self._last_connect_attempt_at = time_module.monotonic()
        gpsd.connect(host=self.host, port=self.port)
        if gpsd.gpsd_socket is not None:
            gpsd.gpsd_socket.settimeout(self.read_timeout)
        self._connected = True

    def _maybe_reconnect(self):
        now = time_module.monotonic()
        if (self._last_connect_attempt_at is not None
                and now - self._last_connect_attempt_at < self.reconnect_interval):
            return
        try:
            self.connect()
        except Exception:
            self._connected = False

    def get_current(self):
        if not self._connected:
            self._maybe_reconnect()
        if not self._connected:
            return gpsd.GpsResponse()
        try:
            return gpsd.get_current()
        except Exception:
            # Connection died (or finally timed out on a stale read) --
            # mark down so the next call is throttled through
            # _maybe_reconnect() instead of hitting gpsd-py3 directly again.
            self._connected = False
            return gpsd.GpsResponse()
