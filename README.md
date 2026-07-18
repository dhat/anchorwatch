anchorwatch
===========

Simple python anchor watch program which runs in a terminal window.

GPS position comes from two possible sources, tried in this order on every update:

1. **Masthead GPS**, via a raw NMEA0183 stream on `localhost:23000` (parsed directly -- GPSD is not
   needed for this source). This unit does 6-axis motion correction and has a clear view of the sky,
   so it's preferred whenever it has a current 3D fix.
2. **GPSD** (an in-boat GPS puck), used as a fallback whenever the masthead feed is stale, not
   reporting a 3D fix, or unreachable. GPSD does not need to be running at startup -- the program
   retries it automatically in the background.

Either source can be down or drop out mid-session without stopping the program; it automatically
falls back and reconnects, logging a message each time the active source changes.

When started, anchorwatch waits until one of these sources reports a quality position, then captures
that position as the center of the alarm radius (offering to reuse the last saved center from a
previous run). The program then prompts for an alarm radius in feet. Once entered, it streams status
updates to the terminal: current distance from center, max distance, alarm count, invalid-data count,
and current/max speed.

Menu (also shown with `h` while running):
- `r` -- change the alarm radius
- `s` -- change the speed limit
- `c` -- change the alarm center (lat/lon)
- `a` -- show the current center position, bearing, and distance
- `x` -- toggle between compact and extended status line
- `p` -- pause the audible alarm for ~30 seconds
- `t` -- test the alarm (buzzer/light/sound)
- `q` -- quit

Alarm sounds use hildon system sounds on maemo OS devices and Gnome sounds on other devices (assumed
Linux-based) -- Gnome sounds must be installed, and if nothing plays, check that the sound file paths
near the top of `anchorwatchnew.py` are correct for your system. A USB buzzer/light is also supported
over serial if present at `/dev/buzzer`.

Setup
-----
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python anchorwatchnew.py
```

Code layout
-----------
- `anchorwatchnew.py` -- the main program: GPS source selection, the menu, and the alarm/hardware loop.
- `geo.py` -- distance/bearing/DMS math.
- `alarm_state.py` -- the drag-alarm decision logic (smoothing, radius/speed checks, bad-data
  handling), as a testable `AlarmState` class.
- `nmea_gps_source.py` -- parses the masthead's NMEA stream into `gpsd.GpsResponse`-shaped fixes,
  with automatic reconnect.
- `gpsd_source.py` -- wraps gpsd-py3 so a missing or dropped gpsd degrades gracefully (bounded read
  timeout, automatic reconnect) instead of hanging or crashing the program.
- `gpsd_compat.py` -- works around a gpsd-py3 bug where some receiver/driver combinations always
  report 0 satellites.
- `tests/` -- unit tests for the above: `python -m unittest discover -s tests -t .`
