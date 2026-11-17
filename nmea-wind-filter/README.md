# nmea-wind-filter v2

Sits between the raw Airmar stream (port 23000) and everything that uses wind,
and serves a cleaned stream on port 23001. Raw port 23000 and the raw logs in
~/airmar-data are untouched, so "filtered vs raw" is just a choice of port.
Every connected client gets every sentence (a fan-out, like remserial).

## Install / upgrade on vega
    sudo install -m 755 nmea_wind_filter.py /usr/local/bin/
    sudo install -m 644 nmea-wind-filter.service /etc/systemd/system/    # first install only
    sudo systemctl daemon-reload
    sudo systemctl enable --now nmea-wind-filter     # upgrade: sudo systemctl restart nmea-wind-filter
    journalctl -u nmea-wind-filter -f

## What changed in v2 (after the Nov 16 alarms)
- $WIMDA is now filtered. The Airmar repeats wind speed in that sentence and it
  was passing through unfiltered (66 kn at 20:15 on Nov 16). Only the wind fields
  are replaced; pressure and temperature in it stay live.
- $WIVWT is covered too, if a sensor sends it.
- Each sentence type's own rhythm is learned (MDA arrives every 2 s, the others
  every 1 s), so the 12 kn limit means the same thing for all of them.
- Ramp mode (default). Instead of repeating the old value, the output moves 3 kn
  per sentence toward the new reading, so a real change is followed within
  seconds and a short spike does little harm. A jump bigger than 15 kn is held
  (not ramped): real wind did not do that in the data so far.
- Quieter log: at most one "rejecting wind" line per 10 s, with a count.

## Options
    --mode ramp|hold|drop   --jump 12   --ramp-step 3   --hard-jump 15
    --hold-max 120   --hold-down 10   --bind 127.0.0.1   --port 23001   --src-port 23000
`--mode hold` gives the v1 behaviour. Use --bind 0.0.0.0 if another machine
reads the filtered port (and allow it in iptables).

## Tested on
Raw Airmar logs of the 13 Nov storm and the evening of 16 Nov (200,000+
sentences): nothing outside the artifact periods is altered; all repaired
sentences have valid checksums; non-wind sentences are byte-for-byte unchanged.
Tuned on three artifact events, so watch the log and adjust.
Not yet tested underway.
