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
and current/max speed. The alarm can be triggered by either distance (drifting past the radius,
adjusted for current GPS error) or speed (moving faster than the configured limit, regardless of
distance).

Menu (also shown with `h` while running):
- `r` -- change the alarm radius
- `s` -- change the speed limit
- `c` -- change the alarm center (lat/lon)
- `a` -- show the current center position, bearing, and distance
- `x` -- toggle between compact and extended status line
- `v` -- toggle a live swing-pattern view (see below)
- `z` -- clear recorded alarm positions (from the swing-pattern view)
- `p` -- pause the audible alarm for ~30 seconds
- `t` -- test the alarm (buzzer/light/sound)
- `q` -- quit

Swing-pattern view
-------------------
A genuine anchor drag tends to show up spatially before the alarm radius is even crossed: normal
swinging clusters in an arc downwind of center, while a real drag walks steadily outward instead of
staying contained. Pressing `v` toggles a live, continuously-redrawing ASCII plot of recent boat
positions relative to center:

```
                  ooooo
            oooo         oooo
         ooo                 ooo
       oo                       oo
     oo                           oo
    oo                             oo
   oo                               oo
   o                                 o
  oo                                 oo
  oo                X                oo
  oo          -++                    oo
   o         :B*#%#                  o
   oo         :+-@=                 oo
    oo  a        :                 oo
     oo                           oo
       oo                       oo
         ooo                 ooo
            oooo         oooo
                  ooooo

N up / E right -- radius=100ft, GPS error=38ft -- 150 pts, 1 alarm pts, 0 speed-alarm pts
X=center  o=radius  e=worst-case (current+error)  a=alarm sounded (distance)  s=alarm sounded (speed)
B=boat-now  |  density, rarely..often visited: :-=+*#%@
```

- `X` marks the anchor center, `o` the configured alarm radius, and `B` the boat's current position.
- Recent positions are density-shaded from rarely visited (`:`) to frequently visited (`@`) -- this is
  the pattern to watch for clustering/drifting.
- `e` marks the *worst-case* position given current GPS error (current distance + error, same
  bearing) -- comparing it to the radius ring shows whether GPS uncertainty alone could be putting
  you past the limit, not just the raw measured position.
- `a` marks every position recorded while the alarm was sounding due to **distance** (at its
  worst-case point); `s` marks positions recorded while it was sounding due to **speed** (at the raw
  current position, since GPS error doesn't have the same "worst case" relationship to a speed
  threshold). Both persist across the session -- they don't roll off like the recent-history trail --
  until cleared with `z`.

While the live view is on, the screen clears and redraws each tick, which also clears away other
printed messages (alarm triggered, invalid GPS, etc.) -- the buzzer/light alarm remains the primary
alert while this view is active, not the on-screen text.

Alarm sounds use hildon system sounds on maemo OS devices and Gnome sounds on other devices (assumed
Linux-based) -- Gnome sounds must be installed, and if nothing plays, check that the sound file paths
near the top of `anchorwatchnew.py` are correct for your system. A USB buzzer/light is also supported
over serial if present at `/dev/buzzer`, reusing one persistent connection with a bounded timeout so an
unresponsive device can't stall the whole program.

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
- `swing_plot.py` -- renders the live ASCII swing-pattern view described above.
- `nmea_gps_source.py` -- parses the masthead's NMEA stream (GGA/RMC/GSA/VTG) into
  `gpsd.GpsResponse`-shaped fixes, with automatic reconnect.
- `gpsd_source.py` -- wraps gpsd-py3 so a missing or dropped gpsd degrades gracefully (bounded read
  timeout, automatic reconnect) instead of hanging or crashing the program.
- `gpsd_compat.py` -- works around a gpsd-py3 bug where some receiver/driver combinations always
  report 0 satellites.
- `buzzer.py` -- controls the USB buzzer/light over one persistent, timeout-bounded serial connection.
- `tests/` -- unit tests for the above: `python -m unittest discover -s tests -t .`
