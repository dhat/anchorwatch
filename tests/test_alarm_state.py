import math
import unittest

from alarm_state import AlarmState


class FakeFix:
    """Stand-in for a gpsd fix object, exposing just what AlarmState reads."""

    def __init__(self, lat, lon, hspeed=0.0, track=0.0, mode=3,
                 sats_valid=8, precision=(5.0, 8.0), time="t0"):
        self.lat = lat
        self.lon = lon
        self.hspeed = hspeed
        self.track = track
        self.mode = mode
        self.sats_valid = sats_valid
        self._precision = precision
        self.time = time

    def position_precision(self):
        return self._precision


REF_LAT, REF_LON = 42.0, -70.0


class AlarmStateTests(unittest.TestCase):
    def make_state(self, **kwargs):
        defaults = dict(thresholdspeed=1.6, maxaccel=5.0, min_sats=4)
        defaults.update(kwargs)
        return AlarmState(**defaults)

    def test_stationary_fix_at_ref_does_not_trigger_alarm(self):
        state = self.make_state()
        result = state.update(FakeFix(REF_LAT, REF_LON, time="t1"), REF_LAT, REF_LON, adist=50)
        self.assertFalse(state.aset)
        self.assertFalse(result.alarm_triggered)
        self.assertEqual(state.icount, 0)
        self.assertFalse(state.triggered_by_distance)
        self.assertFalse(state.triggered_by_speed)

    def test_drifting_past_radius_triggers_alarm(self):
        state = self.make_state()
        # ~0.001 deg lat is roughly 365 feet -- comfortably past a 50ft radius
        fix = FakeFix(REF_LAT + 0.001, REF_LON, time="t1")
        result = state.update(fix, REF_LAT, REF_LON, adist=50)
        self.assertTrue(state.aset)
        self.assertTrue(result.alarm_triggered)
        self.assertTrue(state.triggered_by_distance)
        self.assertFalse(state.triggered_by_speed)

    def test_alarm_clears_once_back_inside_radius(self):
        state = self.make_state()
        far_fix = FakeFix(REF_LAT + 0.001, REF_LON, time="t1")
        state.update(far_fix, REF_LAT, REF_LON, adist=50)
        self.assertTrue(state.aset)

        # Smoothed avgdist decays by 0.8 each tick, so it takes a few ticks
        # back at the ref point before avgdist falls back under the radius.
        # alarm_cleared is only True on the specific tick the flag flips, so
        # watch every tick rather than just the final one.
        near_fix = FakeFix(REF_LAT, REF_LON, time="t1")
        saw_cleared_event = False
        for i in range(30):
            near_fix.time = f"t{i + 2}"
            result = state.update(near_fix, REF_LAT, REF_LON, adist=50)
            saw_cleared_event = saw_cleared_event or result.alarm_cleared
        self.assertFalse(state.aset)
        self.assertTrue(saw_cleared_event)

    def test_speed_over_threshold_triggers_alarm_even_within_radius(self):
        state = self.make_state()
        # avgspeed is an EMA, so it takes a few ticks of sustained speed to
        # climb past thresholdspeed (1.6 m/s) even though each raw reading
        # is well above it.
        fix = FakeFix(REF_LAT, REF_LON, hspeed=5.0, time="t0")
        for i in range(10):
            fix.time = f"t{i + 1}"
            state.update(fix, REF_LAT, REF_LON, adist=500)
        self.assertTrue(state.aset)
        self.assertTrue(state.triggered_by_speed)
        self.assertFalse(state.triggered_by_distance)

    def test_invalid_fix_mode_counts_as_bad_data_and_does_not_crash(self):
        state = self.make_state()
        fix = FakeFix(REF_LAT, REF_LON, mode=1, time="t1")
        result = state.update(fix, REF_LAT, REF_LON, adist=50)
        self.assertTrue(result.invalid_fix)
        self.assertTrue(result.invalid_fix_is_new)
        self.assertEqual(state.icount, 1)
        self.assertEqual(state.iseq, 1)

    def test_invalid_fix_only_flagged_as_new_on_first_of_a_streak(self):
        state = self.make_state()
        fix = FakeFix(REF_LAT, REF_LON, mode=1, time="t1")
        first = state.update(fix, REF_LAT, REF_LON, adist=50)
        second = state.update(fix, REF_LAT, REF_LON, adist=50)
        self.assertTrue(first.invalid_fix_is_new)
        self.assertFalse(second.invalid_fix_is_new)
        self.assertEqual(state.iseq, 2)

    def test_ignore_fix_flag_lets_bad_mode_through(self):
        state = self.make_state(ignore_fix_flag=True)
        fix = FakeFix(REF_LAT, REF_LON, mode=0, time="t1")
        result = state.update(fix, REF_LAT, REF_LON, adist=50)
        self.assertFalse(result.invalid_fix)
        self.assertEqual(state.icount, 0)

    def test_stalled_gps_time_is_flagged_as_stale(self):
        state = self.make_state()
        fix = FakeFix(REF_LAT, REF_LON, time="same")
        state.update(fix, REF_LAT, REF_LON, adist=50)
        result = state.update(fix, REF_LAT, REF_LON, adist=50)
        self.assertTrue(result.stale_time)
        self.assertEqual(state.icount, 1)

    def test_iseq_reset_reported_after_recovering_from_bad_streak(self):
        state = self.make_state()
        bad_fix = FakeFix(REF_LAT, REF_LON, mode=1, time="t1")
        state.update(bad_fix, REF_LAT, REF_LON, adist=50)
        state.update(bad_fix, REF_LAT, REF_LON, adist=50)
        self.assertEqual(state.iseq, 2)

        good_fix = FakeFix(REF_LAT, REF_LON, time="t2")
        result = state.update(good_fix, REF_LAT, REF_LON, adist=50)
        self.assertTrue(result.iseq_reset)
        self.assertEqual(state.iseq, 0)

    def test_sudden_acceleration_spike_rejected_as_bad_distance(self):
        state = self.make_state(maxaccel=5.0)
        fix = FakeFix(REF_LAT + 0.01, REF_LON, hspeed=50.0, time="t1")
        result = state.update(fix, REF_LAT, REF_LON, adist=50)
        self.assertTrue(result.bad_distance)
        self.assertEqual(state.distance, 0.0)

    def test_nan_speed_is_flagged_and_zeroed(self):
        state = self.make_state()
        fix = FakeFix(REF_LAT, REF_LON, hspeed=float("nan"), time="t1")
        result = state.update(fix, REF_LAT, REF_LON, adist=50)
        self.assertTrue(result.bad_speed)
        self.assertEqual(state.speed, 0.0)

    def test_low_satellite_count_is_flagged(self):
        state = self.make_state(min_sats=6)
        fix = FakeFix(REF_LAT, REF_LON, sats_valid=3, time="t1")
        result = state.update(fix, REF_LAT, REF_LON, adist=50)
        self.assertTrue(result.low_sats)

    def test_nan_track_falls_back_to_smoothed_average(self):
        state = self.make_state()
        state.update(FakeFix(REF_LAT, REF_LON, track=90.0, time="t1"), REF_LAT, REF_LON, adist=50)
        state.update(FakeFix(REF_LAT, REF_LON, track=float("nan"), time="t2"), REF_LAT, REF_LON, adist=50)
        self.assertEqual(state.track, state.avgtrack)
        self.assertFalse(math.isnan(state.track))

    def test_high_position_error_does_not_force_a_false_alarm_at_center(self):
        # Regression test: adist - pos_error is the effective alarm radius,
        # shrinking as GPS accuracy drops. If pos_error alone exceeds a
        # small adist, that threshold used to go negative, meaning even a
        # boat sitting exactly at the reference point (avgdist=0) would
        # "exceed" it and the alarm would fire regardless of actual
        # position. It should floor at 0 instead.
        state = self.make_state()
        fix = FakeFix(REF_LAT, REF_LON, precision=(20.0, 30.0), time="t0")
        for i in range(10):
            fix.time = f"t{i + 1}"
            state.update(fix, REF_LAT, REF_LON, adist=10)
        self.assertGreater(state.pos_error, 10)  # confirms this scenario is actually exercised
        self.assertEqual(state.effective_radius, 0.0)
        self.assertEqual(state.avgdist, 0.0)
        self.assertFalse(state.aset)

    def test_effective_radius_matches_display_formula_when_not_clamped(self):
        state = self.make_state()
        fix = FakeFix(REF_LAT, REF_LON, precision=(1.0, 1.0), time="t1")
        state.update(fix, REF_LAT, REF_LON, adist=100)
        self.assertAlmostEqual(state.effective_radius, 100 - state.pos_error)

    def test_forced_adata_triggers_alarm_regardless_of_position(self):
        state = self.make_state()
        fix = FakeFix(REF_LAT, REF_LON, time="t1")
        result = state.update(fix, REF_LAT, REF_LON, adist=500, adata=True)
        self.assertTrue(state.aset)
        self.assertTrue(result.alarm_triggered)


if __name__ == '__main__':
    unittest.main()
