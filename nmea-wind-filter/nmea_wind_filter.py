#!/usr/bin/env python3
"""NMEA 0183 wind spike filter / proxy (v2).

Reads the raw Airmar stream (default localhost:23000), repairs wind sentences
whose speed makes an impossible jump, and serves the cleaned stream on a new
port (default 23001). Every other sentence passes through byte for byte.

Wind-bearing sentences handled: MWV (apparent and true), VWR, VWT, MWD, MDA.

Rule: a sentence is rejected when its speed differs from the current output
for that sentence type by more than --jump knots (about 1 s apart).
  --mode ramp (default): the output moves --ramp-step knots per sentence toward
      the new reading, so a real change is followed within seconds while a short
      spike does little harm. A jump bigger than --hard-jump is held instead
      (the output does not move at all) because real wind does not do that.
  --mode hold: the last accepted values are repeated.
  --mode drop: rejected sentences are not forwarded.
If a rejected reading persists, it is accepted after --hold-max seconds (higher)
or --hold-down seconds (lower), so the filter can never stay locked out.

Standard library only.
"""
import argparse
import asyncio
import logging
import signal
import time

log = logging.getLogger("nmea-wind-filter")

KN_PER_UNIT = {"N": 1.0, "M": 1.94384, "K": 0.539957}   # knots, m/s, km/h


def checksum(body):
    c = 0
    for ch in body:
        c ^= ord(ch)
    return "%02X" % c


def _num(fields, i):
    try:
        return float(fields[i])
    except (ValueError, IndexError):
        return None


def classify(fields):
    """-> dict(key, speed, angle, spd_fields, wind_idx) or None.
    spd_fields: [(value_index, unit_index)]; wind_idx: every wind-bearing field."""
    kind = fields[0][-3:]
    try:
        if kind == "MWV" and len(fields) >= 6:
            sp = _num(fields, 3) * KN_PER_UNIT[fields[4]]
            return dict(key="MWV" + fields[2], speed=sp, angle=float(fields[1]),
                        spd_fields=[(3, 4)], wind_idx=[1, 3])
        if kind in ("VWR", "VWT") and len(fields) >= 9:
            sp = _num(fields, 3) * KN_PER_UNIT[fields[4]]
            ang = float(fields[1]) * (-1 if fields[2] == "L" else 1)
            return dict(key=kind, speed=sp, angle=ang,
                        spd_fields=[(3, 4), (5, 6), (7, 8)], wind_idx=[1, 2, 3, 5, 7])
        if kind == "MWD" and len(fields) >= 9:
            sp = _num(fields, 5) * KN_PER_UNIT[fields[6]]
            return dict(key="MWD", speed=sp, angle=float(fields[1]),
                        spd_fields=[(5, 6), (7, 8)], wind_idx=[1, 3, 5, 7])
        if kind == "MDA" and len(fields) >= 21:
            sp = _num(fields, 17) * KN_PER_UNIT[fields[18]]
            return dict(key="MDA", speed=sp, angle=_num(fields, 13),
                        spd_fields=[(17, 18), (19, 20)], wind_idx=[13, 15, 17, 19])
    except (ValueError, KeyError, TypeError):
        pass
    return None


def angle_diff(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


class WindFilter:
    """mode 'hold': a rejected sentence repeats the last accepted wind values.
    mode 'ramp': the output moves ramp_step kn per sentence toward the new reading.
    hard_jump (kn, 0=off): in ramp mode, a jump bigger than this is held, not ramped."""

    def __init__(self, jump_kn=12.0, hold_max=120.0, hold_down=10.0, mode="hold",
                 base_dt=1.0, ramp_step=None, hard_jump=0.0):
        self.jump, self.hold_max, self.hold_down = jump_kn, hold_max, hold_down
        self.mode, self.base_dt = mode, base_dt
        self.ramp_step = ramp_step if ramp_step is not None else jump_kn / 2.0
        self.hard_jump = hard_jump
        self.st = {}          # key -> dict(out, fields, t_acc, t_seen)
        self.streak = 0
        self.total_rejects = 0
        self.resyncs = 0
        self.events = []      # (kind, message) for the caller to log

    def process(self, line, now):
        if not line.startswith("$") or "*" not in line:
            return line, False
        body, _, cs = line[1:].rpartition("*")
        if len(cs) != 2 or checksum(body).upper() != cs.upper():
            return line, False
        fields = body.split(",")
        info = classify(fields)
        if info is None:
            return line, False
        key, raw = info["key"], info["speed"]
        s = self.st.get(key)
        if s is None:
            self.st[key] = dict(out=raw, fields=fields, t_acc=now, t_seen=now,
                                cad=self.base_dt)
            return line, False
        dt = now - s["t_seen"]
        s["t_seen"] = now
        # each sentence type has its own rhythm (MDA ~2 s, others ~1 s): learn it
        # from short gaps only, so a long silence cannot loosen the limit for good
        if dt < 2.5 * s["cad"]:
            s["cad"] = max(0.2, 0.9 * s["cad"] + 0.1 * dt)
        scale = min(max(dt / s["cad"], 1.0), 4.0)
        diff = raw - s["out"]
        accept = abs(diff) <= self.jump * scale
        if not accept:
            limit = self.hold_down if diff < 0 else self.hold_max
            if now - s["t_acc"] > limit:
                self.resyncs += 1
                self.events.append(("resync", "%s re-sync at %.1f kn" % (key, raw)))
                accept = True
        if accept:
            s.update(out=raw, fields=fields, t_acc=now)
            if self.streak:
                self.events.append(("normal", "back to normal after %d rejected" % self.streak))
            self.streak = 0
            return line, False
        # ---- rejected
        self.streak += 1
        self.total_rejects += 1
        if self.streak == 1:
            self.events.append(("reject", "%s: %.1f kn vs output %.1f kn" % (key, raw, s["out"])))
        ramp = (self.mode == "ramp"
                and not (self.hard_jump and abs(diff) > self.hard_jump))
        if ramp:
            step = min(self.ramp_step, abs(diff))
            s["out"] += step if diff > 0 else -step
        if self.mode == "drop":
            return None, True
        out = list(fields)
        good = s["fields"]
        for i in info["wind_idx"]:            # wind values come from the last good sentence
            if i < len(good):
                out[i] = good[i]
        if ramp:                              # ... with the ramped speed
            for vi, ui in info["spd_fields"]:
                out[vi] = "%.1f" % (s["out"] / KN_PER_UNIT[out[ui]])
        b = ",".join(out)
        return "$%s*%s" % (b, checksum(b)), True


# ----------------------------------------------------------------- service
class Proxy:
    def __init__(self, args):
        self.args = args
        self.filter = WindFilter(args.jump, args.hold_max, args.hold_down, args.mode,
                                 args.cadence, args.ramp_step, args.hard_jump)
        self.clients = set()
        self._last_log = -1e9
        self._suppressed = 0

    def drain_events(self):
        f = self.filter
        ev, f.events = f.events, []
        now = time.monotonic()
        for kind, msg in ev:
            if kind == "reject":
                if now - self._last_log >= 10.0:
                    extra = (" (+%d similar in the last 10 s)" % self._suppressed
                             if self._suppressed else "")
                    log.warning("rejecting wind: %s%s", msg, extra)
                    self._last_log, self._suppressed = now, 0
                else:
                    self._suppressed += 1
            elif kind == "resync":
                log.info(msg)

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
                    if self.filter.events:
                        self.drain_events()
                    if out is not None:
                        self.broadcast(out)
            except Exception as e:
                log.warning("source problem (%s); retrying in 5 s", e or type(e).__name__)
                await asyncio.sleep(5)

    async def run(self):
        a = self.args
        server = await asyncio.start_server(self.on_client, a.bind, a.port)
        log.info("serving filtered NMEA on %s:%d (mode=%s jump=%.1f ramp-step=%.1f "
                 "hard-jump=%.1f hold-max=%.0f hold-down=%.0f)", a.bind, a.port, a.mode,
                 a.jump, self.filter.ramp_step, a.hard_jump, a.hold_max, a.hold_down)
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
    p.add_argument("--mode", choices=["ramp", "hold", "drop"], default="ramp")
    p.add_argument("--jump", type=float, default=12.0,
                   help="largest normal speed change between consecutive sentences, kn")
    p.add_argument("--ramp-step", type=float, default=3.0,
                   help="ramp mode: knots per sentence the output moves toward a new reading")
    p.add_argument("--hard-jump", type=float, default=15.0,
                   help="ramp mode: jumps bigger than this are held, not ramped (0 = off)")
    p.add_argument("--hold-max", type=float, default=120.0,
                   help="seconds before a persistent HIGH reading is accepted")
    p.add_argument("--hold-down", type=float, default=10.0,
                   help="seconds before a persistent LOW reading is accepted")
    p.add_argument("--cadence", type=float, default=1.0,
                   help="starting guess for seconds between sentences of one type")
    p.add_argument("--stale", type=float, default=30.0,
                   help="reconnect if the source is silent this many seconds")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    loop = asyncio.new_event_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(s, loop.stop)
    try:
        loop.run_until_complete(Proxy(args).run())
    except RuntimeError:
        pass


if __name__ == "__main__":
    main()
