#!/usr/bin/env python3
"""NMEA 0183 wind spike filter / proxy.

Reads the raw Airmar stream (default localhost:23000), repairs wind sentences
whose speed makes an impossible jump, and serves the cleaned stream on a new
port (default 23001). Every other sentence passes through byte for byte.

Wind sentences handled: MWV (apparent and true), VWR, MWD.
A wind sentence is "rejected" when its speed differs from the last accepted
speed for that same sentence by more than --jump knots (scaled up a little if
samples arrive slowly). Rejected sentences are replaced by the last accepted
one (--mode hold, checksum recomputed) or dropped (--mode drop).
If nothing has been accepted for --hold-max seconds the filter re-syncs and
accepts the new value, so a real, sustained change can never be locked out.

Standard library only.
"""
import argparse
import asyncio
import logging
import signal
import time

log = logging.getLogger("nmea-wind-filter")

KN_PER_UNIT = {"N": 1.0, "M": 1.94384, "K": 0.539957}  # knots, m/s, km/h


def checksum(body):
    c = 0
    for ch in body:
        c ^= ord(ch)
    return "%02X" % c


def _speed(fields, idx):
    """Speed in knots from fields[idx] with unit in fields[idx+1], else None."""
    try:
        return float(fields[idx]) * KN_PER_UNIT[fields[idx + 1]]
    except (ValueError, KeyError, IndexError):
        return None


def classify(fields):
    """Return (key, speed_kn, angle_deg|None) for filterable wind sentences."""
    kind = fields[0][-3:]
    try:
        if kind == "MWV" and len(fields) >= 6:
            sp = _speed(fields, 3)
            return ("MWV" + fields[2], sp, float(fields[1])) if sp is not None else None
        if kind == "VWR" and len(fields) >= 5:
            sp = _speed(fields, 3)
            ang = float(fields[1]) * (-1 if fields[2] == "L" else 1)
            return ("VWR", sp, ang) if sp is not None else None
        if kind == "MWD" and len(fields) >= 7:
            sp = _speed(fields, 5)
            return ("MWD", sp, float(fields[1])) if sp is not None else None
    except ValueError:
        pass
    return None


def angle_diff(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


class WindFilter:
    def __init__(self, jump_kn=12.0, hold_max=120.0, mode="hold", base_dt=1.0,
                 combo_kn=None, combo_deg=None, hold_down=10.0):
        self.hold_down = hold_down    # re-sync time when the new value is LOWER
        self.combo_kn = combo_kn      # smaller speed step that counts if the angle also jumps
        self.combo_deg = combo_deg    # ... by at least this many degrees
        self.jump_kn = jump_kn
        self.hold_max = hold_max
        self.mode = mode
        self.base_dt = base_dt
        self.good = {}   # key -> (speed_kn, fields, t_accepted)
        self.seen = {}   # key -> t of previous sentence (any)
        self.streak = 0          # consecutive rejected sentences
        self.episode_rejects = 0
        self.total_rejects = 0
        self.resyncs = 0

    def process(self, line, now):
        """line: sentence without line terminator. Returns (out_line|None, rejected)."""
        if not line.startswith("$") or "*" not in line:
            return line, False
        body, _, cs = line[1:].rpartition("*")
        if len(cs) != 2 or checksum(body).upper() != cs.upper():
            return line, False          # not ours to judge; pass through
        fields = body.split(",")
        info = classify(fields)
        if info is None:
            return line, False
        key, speed, angle = info
        prev_seen = self.seen.get(key)
        self.seen[key] = now
        good = self.good.get(key)
        accept = True
        if good is not None:
            dt = (now - prev_seen) if prev_seen is not None else self.base_dt
            scale = min(max(dt / self.base_dt, 1.0), 4.0)
            dsp = abs(speed - good[0])
            bad = dsp > self.jump_kn * scale
            if (not bad and self.combo_kn is not None and angle is not None
                    and good[3] is not None):
                bad = (dsp > self.combo_kn * scale
                       and angle_diff(angle, good[3]) > self.combo_deg)
            if bad:
                limit = self.hold_down if speed < good[0] else self.hold_max
                if now - good[2] > limit:
                    self.resyncs += 1
                    log.info("%s: no accepted value for %.0f s, re-syncing at %.1f kn",
                             key, now - good[2], speed)
                else:
                    accept = False
        if accept:
            self.good[key] = (speed, fields, now, angle)
            if self.streak:
                log.info("wind readings back to normal after %d rejected sentences",
                         self.streak)
            self.streak = 0
            self.episode_rejects = 0
            return line, False
        # rejected
        self.streak += 1
        self.episode_rejects += 1
        self.total_rejects += 1
        if self.streak == 1:
            log.warning("rejecting wind sentence %s: %.1f kn vs last good %.1f kn "
                        "(possible rain/interference)", key, speed, good[0])
        if self.mode == "drop":
            return None, True
        held = ",".join(good[1])
        return "$%s*%s" % (held, checksum(held)), True


# ----------------------------------------------------------------- service
class Proxy:
    def __init__(self, args):
        self.args = args
        self.filter = WindFilter(args.jump, args.hold_max, args.mode, args.cadence,
                                 hold_down=args.hold_down)
        self.clients = set()

    def broadcast(self, line):
        data = (line + "\r\n").encode("ascii", "replace")
        for w in list(self.clients):
            try:
                if w.transport.get_write_buffer_size() > 1_000_000:
                    w.close()
                    self.clients.discard(w)
                else:
                    w.write(data)
            except Exception:
                self.clients.discard(w)

    async def on_client(self, reader, writer):
        peer = writer.get_extra_info("peername")
        log.info("client connected: %s", peer)
        self.clients.add(writer)
        try:
            while await reader.read(1024):
                pass
        except Exception:
            pass
        finally:
            self.clients.discard(writer)
            writer.close()
            log.info("client left: %s", peer)

    async def upstream(self):
        a = self.args
        while True:
            try:
                reader, writer = await asyncio.open_connection(a.src_host, a.src_port)
                log.info("connected to source %s:%d", a.src_host, a.src_port)
                while True:
                    raw = await asyncio.wait_for(reader.readline(), a.stale)
                    if not raw:
                        raise ConnectionError("source closed")
                    line = raw.decode("ascii", "replace").rstrip("\r\n")
                    if not line:
                        continue
                    out, _ = self.filter.process(line, time.monotonic())
                    if out is not None:
                        self.broadcast(out)
            except Exception as e:
                log.warning("source problem (%s); retrying in 5 s", e or type(e).__name__)
                await asyncio.sleep(5)

    async def run(self):
        a = self.args
        server = await asyncio.start_server(self.on_client, a.bind, a.port)
        log.info("serving filtered NMEA on %s:%d (jump=%.1f kn per %.1f s, hold-max=%.0f s, mode=%s)",
                 a.bind, a.port, a.jump, a.cadence, a.hold_max, a.mode)
        async with server:
            await self.upstream()


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--src-host", default="127.0.0.1")
    p.add_argument("--src-port", type=int, default=23000)
    p.add_argument("--bind", default="127.0.0.1",
                   help="address to listen on (0.0.0.0 for other machines)")
    p.add_argument("--port", type=int, default=23001)
    p.add_argument("--jump", type=float, default=12.0,
                   help="max speed change between consecutive sentences "
                        "(about 1 s apart), knots")
    p.add_argument("--hold-max", type=float, default=120.0,
                   help="seconds of rejected HIGH readings before accepting them")
    p.add_argument("--hold-down", type=float, default=10.0,
                   help="seconds of rejected LOW readings before accepting them")
    p.add_argument("--mode", choices=["hold", "drop"], default="hold")
    p.add_argument("--cadence", type=float, default=1.0,
                   help="normal seconds between wind sentences of one kind")
    p.add_argument("--stale", type=float, default=30.0,
                   help="reconnect if the source is silent this many seconds")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(message)s")  # journald adds timestamps
    loop = asyncio.new_event_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(s, loop.stop)
    try:
        loop.run_until_complete(Proxy(args).run())
    except RuntimeError:
        pass


if __name__ == "__main__":
    main()
