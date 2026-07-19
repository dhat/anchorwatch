import socket
import threading
import time
import unittest

from nmea_gps_source import NmeaGpsSource

GGA_GOOD = "$GPGGA,190001,4200.0000,N,07000.0000,W,1,09,0.9,23.0,M,-33.4,M,,*40"
RMC_GOOD = "$GPRMC,190001,A,4200.0000,N,07000.0000,W,000.1,151.0,180726,,,A*64"
GSA_3D = "$GPGSA,A,3,04,05,09,12,15,18,21,24,,,,,1.8,0.9,1.6*36"
GGA_NO_FIX = "$GPGGA,190002,,,,,0,00,,,M,,M,,*6C"
# Real sentence shape from the boat's actual masthead multiplexer, which
# (confirmed by capturing the live feed) never sends RMC at all -- only
# GGA/GSA-less position sentences plus VTG for speed/track.
VTG_GOOD = "$GPVTG,164.7,T,153.2,M,5.5,N,10.2,K,D*14"
VTG_NOT_VALID = "$GPVTG,164.7,T,153.2,M,0.0,N,0.0,K,N*2D"
VTG_LEGACY_NO_MODE = "$GPVTG,164.7,T,153.2,M,3.0,N,5.6,K*4F"
# Matches the real captured live feed: wind ~30deg off the bow, 8kt.
MWV_GOOD = "$WIMWV,29.8,R,8.0,N,A*18"
MWV_BEAM_ON = "$WIMWV,90.0,R,10.0,N,A*2B"
MWV_LIGHT_WIND = "$WIMWV,45.0,R,2.0,N,A*10"
MWV_TRUE_REFERENCE = "$WIMWV,15.0,T,8.0,N,A*19"
MWV_INVALID_STATUS = "$WIMWV,20.0,R,8.0,N,V*0E"
MWV_NEAR_ZERO_WRAP = "$WIMWV,350.0,R,10.0,N,A*14"


def _free_port():
    """A currently-unused local port, for tests that must NOT reach a real
    server. NmeaGpsSource's default port (23000) is the real masthead feed
    on the actual boat network -- in an environment with a route to it,
    connecting to the *default* host/port is a real network call, not a
    guaranteed no-op, now that auto-reconnect actively dials out whenever
    the socket is down. Any test exercising get_current()/_maybe_reconnect()
    without deliberately standing up its own fake server must bind to a
    port obtained here instead of relying on defaults being unreachable.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class NmeaGpsSourceTests(unittest.TestCase):
    def test_starts_stale_with_no_sentences_ingested(self):
        source = NmeaGpsSource(host='127.0.0.1', port=_free_port())
        self.assertTrue(source.is_stale())
        fix = source.get_current()
        self.assertEqual(fix.mode, 0)

    def test_gga_alone_gives_lat_lon_and_tentative_3d_mode(self):
        source = NmeaGpsSource()
        source.ingest_line(GGA_GOOD)
        fix = source._build_fix()
        self.assertAlmostEqual(fix.lat, 42.0)
        self.assertAlmostEqual(fix.lon, -70.0)
        self.assertEqual(fix.sats, 9)
        self.assertEqual(fix.sats_valid, 9)
        self.assertEqual(fix.mode, 3)

    def test_gsa_overrides_mode_with_actual_fix_dimension(self):
        source = NmeaGpsSource()
        source.ingest_line(GGA_GOOD)
        source.ingest_line(GSA_3D)
        fix = source._build_fix()
        self.assertEqual(fix.mode, 3)
        self.assertEqual(fix.sats, 8)  # 8 non-empty sv_id fields in GSA_3D

    def test_rmc_supplies_speed_and_track(self):
        source = NmeaGpsSource()
        source.ingest_line(GGA_GOOD)
        source.ingest_line(RMC_GOOD)
        fix = source._build_fix()
        self.assertAlmostEqual(fix.hspeed, 0.1 * 0.514444, places=5)
        self.assertAlmostEqual(fix.track, 151.0)

    def test_vtg_supplies_speed_and_track(self):
        # Regression test: this boat's actual masthead feed never sends
        # RMC, only VTG, so speed/track used to silently stay at 0.
        source = NmeaGpsSource()
        source.ingest_line(GGA_GOOD)
        source.ingest_line(VTG_GOOD)
        fix = source._build_fix()
        self.assertAlmostEqual(fix.hspeed, 5.5 * 0.514444, places=5)
        self.assertAlmostEqual(fix.track, 164.7)

    def test_vtg_with_not_valid_mode_indicator_is_ignored(self):
        source = NmeaGpsSource()
        source.ingest_line(GGA_GOOD)
        source.ingest_line(VTG_NOT_VALID)
        fix = source._build_fix()
        self.assertEqual(fix.hspeed, 0.0)
        self.assertEqual(fix.track, 0.0)

    def test_legacy_vtg_without_mode_indicator_is_still_accepted(self):
        # Pre-NMEA-2.3 VTG sentences don't have the mode indicator field at
        # all -- that should be treated as valid, not rejected.
        source = NmeaGpsSource()
        source.ingest_line(GGA_GOOD)
        source.ingest_line(VTG_LEGACY_NO_MODE)
        fix = source._build_fix()
        self.assertAlmostEqual(fix.hspeed, 3.0 * 0.514444, places=5)
        self.assertAlmostEqual(fix.track, 164.7)

    def test_wind_starts_with_no_reading(self):
        source = NmeaGpsSource()
        wind = source.get_wind()
        self.assertIsNone(wind.relative_angle_off_bow)
        self.assertIsNone(wind.wind_speed_knots)
        self.assertTrue(wind.low_wind)

    def test_mwv_supplies_relative_angle_and_speed(self):
        # Matches the real captured live feed exactly.
        source = NmeaGpsSource()
        source.ingest_line(MWV_GOOD)
        wind = source.get_wind()
        self.assertAlmostEqual(wind.wind_speed_knots, 8.0)
        self.assertAlmostEqual(wind.relative_angle_off_bow, 29.8)
        self.assertFalse(wind.low_wind)

    def test_beam_on_wind_reports_angle_near_90(self):
        source = NmeaGpsSource()
        source.ingest_line(MWV_BEAM_ON)
        wind = source.get_wind()
        self.assertAlmostEqual(wind.relative_angle_off_bow, 90.0)

    def test_angle_off_bow_collapses_port_starboard_near_360(self):
        # 350deg (nearly dead ahead from the other side) should collapse to
        # "10deg off the bow", not stay as a large near-360 number.
        source = NmeaGpsSource()
        source.ingest_line(MWV_NEAR_ZERO_WRAP)
        wind = source.get_wind()
        self.assertAlmostEqual(wind.relative_angle_off_bow, 10.0)

    def test_true_reference_wind_is_ignored(self):
        # Only relative-to-bow readings are used -- a true-referenced angle
        # would need heading folded back in, reintroducing compass noise.
        source = NmeaGpsSource()
        source.ingest_line(MWV_TRUE_REFERENCE)
        wind = source.get_wind()
        self.assertIsNone(wind.relative_angle_off_bow)
        self.assertIsNone(wind.wind_speed_knots)

    def test_invalid_status_wind_is_ignored(self):
        source = NmeaGpsSource()
        source.ingest_line(MWV_INVALID_STATUS)
        wind = source.get_wind()
        self.assertIsNone(wind.relative_angle_off_bow)

    def test_light_wind_does_not_update_the_smoothed_angle(self):
        # Regression test for the core ask: in light air a boat can spin
        # freely with nothing holding a heading, so a low-wind reading
        # should not be averaged into the smoothed signal at all.
        source = NmeaGpsSource()
        source.ingest_line(MWV_GOOD)  # establishes a trustworthy baseline (8kt, 29.8deg)
        baseline = source.get_wind().relative_angle_off_bow
        source.ingest_line(MWV_LIGHT_WIND)  # 2kt, 45deg -- should be ignored
        wind = source.get_wind()
        self.assertEqual(wind.relative_angle_off_bow, baseline)
        self.assertTrue(wind.low_wind)
        # The raw wind speed itself still updates, just not the smoothed angle.
        self.assertAlmostEqual(wind.wind_speed_knots, 2.0)

    def test_wind_goes_blank_when_feed_is_stale(self):
        # Regression test: get_wind() used to keep returning the last
        # known reading forever even after the masthead feed itself went
        # stale, with nothing indicating it was outdated.
        source = NmeaGpsSource(stale_after=0.01)
        source.ingest_line(MWV_GOOD)
        self.assertIsNotNone(source.get_wind().relative_angle_off_bow)
        time.sleep(0.02)
        wind = source.get_wind()
        self.assertIsNone(wind.relative_angle_off_bow)
        self.assertIsNone(wind.wind_speed_knots)
        self.assertTrue(wind.low_wind)

    def test_low_wind_flag_reflects_current_reading_not_history(self):
        source = NmeaGpsSource()
        source.ingest_line(MWV_GOOD)
        self.assertFalse(source.get_wind().low_wind)
        source.ingest_line(MWV_LIGHT_WIND)
        self.assertTrue(source.get_wind().low_wind)

    def test_relative_angle_smooths_across_multiple_readings(self):
        source = NmeaGpsSource()
        source.ingest_line(MWV_GOOD)       # 29.8deg
        first = source.get_wind().relative_angle_off_bow
        source.ingest_line(MWV_BEAM_ON)    # 90.0deg
        second = source.get_wind().relative_angle_off_bow
        # Should move toward 90 but not jump there in one tick.
        self.assertGreater(second, first)
        self.assertLess(second, 90.0)

    def test_no_fix_gga_sets_mode_to_1_and_keeps_last_good_position(self):
        source = NmeaGpsSource()
        source.ingest_line(GGA_GOOD)
        source.ingest_line(GGA_NO_FIX)
        fix = source._build_fix()
        self.assertEqual(fix.mode, 1)
        # last known-good lat/lon should not be clobbered by the no-fix sentence
        self.assertAlmostEqual(fix.lat, 42.0)

    def test_garbage_line_is_ignored_without_raising(self):
        source = NmeaGpsSource()
        source.ingest_line(GGA_GOOD)
        source.ingest_line("not a real nmea sentence")
        fix = source._build_fix()
        self.assertEqual(fix.mode, 3)

    def test_empty_line_is_ignored(self):
        source = NmeaGpsSource()
        source.ingest_line("")
        self.assertTrue(source.is_stale())

    def test_hdop_and_vdop_feed_position_precision(self):
        source = NmeaGpsSource()
        source.ingest_line(GGA_GOOD)
        source.ingest_line(GSA_3D)
        fix = source._build_fix()
        x_err, v_err = fix.position_precision()
        self.assertAlmostEqual(x_err, 0.9 * 5.0)
        self.assertAlmostEqual(v_err, 1.6 * 5.0)

    def test_hdop_feeds_speed_error_estimate(self):
        # NMEA has no speed-error sentence at all, so this is a heuristic
        # scaled by HDOP the same way position error is -- but it should at
        # least respond to HDOP rather than being a fixed constant.
        source = NmeaGpsSource()
        source.ingest_line(GGA_GOOD)  # horizontal_dil = 0.9
        fix = source._build_fix()
        self.assertAlmostEqual(fix.error['s'], 0.9 * 0.5)

    def test_becomes_stale_after_timeout_even_with_prior_good_data(self):
        source = NmeaGpsSource(host='127.0.0.1', port=_free_port(), stale_after=0.01)
        source.ingest_line(GGA_GOOD)
        time.sleep(0.02)
        fix = source.get_current()
        self.assertEqual(fix.mode, 0)


class NmeaGpsSourceRealSocketTests(unittest.TestCase):
    """Regression coverage for a real CPython socket-module footgun: reading
    via socket.makefile()/readline() with a short timeout works once, but
    every read after the *first* timeout raises
    OSError("cannot read from timed out object") instead of a normal
    timeout -- silently breaking this after its very first empty read. This
    drives NmeaGpsSource against a real local TCP server that deliberately
    sends slower than the read timeout, forcing several timeout cycles, to
    make sure the raw-recv()-based reader doesn't have that problem.
    """

    def _start_slow_server(self, lines, delay):
        srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv_sock.bind(('127.0.0.1', 0))
        port = srv_sock.getsockname()[1]
        srv_sock.listen(1)

        def run():
            conn, _ = srv_sock.accept()
            with conn:
                for line in lines:
                    try:
                        conn.sendall((line + '\r\n').encode('ascii'))
                    except OSError:
                        return
                    time.sleep(delay)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(srv_sock.close)
        return port

    def test_survives_repeated_read_timeouts_without_getting_stuck(self):
        # 0.2s is NmeaGpsSource's own read timeout (set in connect()); sending
        # slower than that guarantees get_current() hits a timeout on most calls.
        port = self._start_slow_server([GGA_GOOD] * 6, delay=0.35)

        source = NmeaGpsSource(host='127.0.0.1', port=port)
        source.connect()
        self.addCleanup(source.close)

        modes_seen = []
        for _ in range(10):
            fix = source.get_current()
            modes_seen.append(fix.mode)
            time.sleep(0.25)

        self.assertIn(3, modes_seen, "never got a 3D fix -- read-timeout handling regressed")


class NmeaGpsSourceReconnectTests(unittest.TestCase):
    def test_failed_connect_does_not_raise_and_reports_no_fix(self):
        port = _free_port()  # nothing listening here
        source = NmeaGpsSource(host='127.0.0.1', port=port)
        fix = source.get_current()
        self.assertEqual(fix.mode, 0)

    def test_reconnect_attempts_are_throttled(self):
        port = _free_port()  # nothing listening here
        source = NmeaGpsSource(host='127.0.0.1', port=port, reconnect_interval=1.0)

        attempts = []
        real_connect = source.connect

        def counting_connect():
            attempts.append(1)
            real_connect()

        source.connect = counting_connect

        for _ in range(5):
            fix = source.get_current()
            self.assertEqual(fix.mode, 0)

        self.assertEqual(len(attempts), 1,
                          "should only attempt one reconnect within the throttle window, "
                          "not hammer a failed connection every tick")

    def test_reconnects_automatically_once_the_stream_comes_back(self):
        port = _free_port()
        source = NmeaGpsSource(host='127.0.0.1', port=port, reconnect_interval=0.05)
        self.addCleanup(source.close)

        # Nothing listening yet -- should fail quietly, not raise.
        fix = source.get_current()
        self.assertEqual(fix.mode, 0)

        # Bring the "masthead" online after the fact, simulating it coming
        # back up after a dropout, and give the throttle window time to pass.
        srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv_sock.bind(('127.0.0.1', port))
        srv_sock.listen(1)
        self.addCleanup(srv_sock.close)

        def run():
            conn, _ = srv_sock.accept()
            with conn:
                conn.sendall((GGA_GOOD + '\r\n').encode('ascii'))
                time.sleep(1)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        time.sleep(0.1)  # let the throttle window elapse

        fix = None
        for _ in range(20):
            fix = source.get_current()
            if fix.mode == 3:
                break
            time.sleep(0.05)

        self.assertEqual(fix.mode, 3,
                          "should reconnect automatically once the feed is reachable again")


if __name__ == '__main__':
    unittest.main()
