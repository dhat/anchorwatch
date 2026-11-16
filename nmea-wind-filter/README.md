# nmea-wind-filter

Sits between the raw Airmar stream (port 23000) and everything that uses wind,
and serves a cleaned stream on port 23001. Raw port 23000 and the raw logs in
~/airmar-data are untouched, so "filtered vs raw" is just a choice of port.

## Install (on vega)
    sudo install -m 755 nmea_wind_filter.py /usr/local/bin/
    sudo install -m 644 nmea-wind-filter.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now nmea-wind-filter
    journalctl -u nmea-wind-filter -f          # rejections are logged here
    nc localhost 23001 | head                  # should look like the raw feed

## Use it
- Anchor alarm: change its NMEA TCP port from 23000 to 23001.
- SignalK: Server > Connections > Airmar: change the port to 23001.
  (Grafana, the gust plugin and Freeboard-SK then all see clean wind.)
- Switch back to raw at any time by pointing them at 23000 again.
- If the anchor alarm runs on another machine: add `--bind 0.0.0.0` to
  ExecStart and allow the port, e.g. `sudo iptables -I INPUT -p tcp --dport 23001 -j ACCEPT`.

## What it does
Wind sentences (MWV apparent and true, VWR, MWD) are rejected if the speed
changes by more than 12 kn from the last accepted value 1 s earlier. A rejected
sentence is replaced by the last good one (checksum recomputed). Everything else
passes through unchanged. Re-sync: a rejected HIGH reading is accepted after
120 s, a rejected LOW reading after 10 s, so it can never stay locked out.

Options: --jump 12  --hold-max 120  --hold-down 10  --mode hold|drop
         --bind 127.0.0.1  --port 23001  --src-port 23000

## Tested on
Raw Airmar log of the 13 Nov 2026 storm at the dock (154,171 sentences):
0 false rejections in the ~96,000 sentences outside the rain period, including
the real gale to 42 kn; rain-period peak 71 kn -> 39.7 kn, none above 45 kn.
Not yet tested underway.
