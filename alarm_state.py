"""Alarm decision state machine for the anchor watch loop.

This is a faithful extraction of the per-fix decision logic that used to live
inline in anchorwatchnew.py's main loop. It owns no I/O (no printing, no
gpsd/serial calls) so the drag-alarm decision -- the safety-critical part of
this program -- can be unit tested without a real GPS or buzzer attached.

Callers feed each new gpsd fix into AlarmState.update(...) and get back a
FixUpdateResult describing which noteworthy events happened this tick
(invalid fix, stale time, alarm triggered/cleared, etc). The caller is
responsible for turning those events into prints/sounds/hardware calls.
"""
from dataclasses import dataclass
import math

from geo import calc_distance, calc_bearing

FEET_PER_METER = 3.28084


@dataclass
class FixUpdateResult:
    invalid_fix: bool = False       # fix.mode != 3 (and not ignoring fix quality)
    invalid_fix_is_new: bool = False  # first invalid fix in a new bad streak
    bad_distance: bool = False      # distance was nan, or speed jump exceeded maxaccel
    stale_time: bool = False        # gpsd time did not advance since last tick
    stale_time_is_new: bool = False   # first stale-time tick in a new bad streak
    iseq_reset: bool = False        # iseq just dropped back to 0 (recovered from a bad streak)
    bad_speed: bool = False         # speed was nan
    low_sats: bool = False          # fewer than min_sats satellites used
    alarm_triggered: bool = False   # aset flipped False -> True this tick
    alarm_cleared: bool = False     # aset flipped True -> False this tick


class AlarmState:
    """Tracks smoothed distance/speed/track and the anchor-drag alarm flag."""

    def __init__(self, thresholdspeed, maxaccel, min_sats, ignore_fix_flag=False,
                 wind_speed_threshold_kt=10.0, wind_heading_threshold_deg=45.0):
        self.thresholdspeed = thresholdspeed
        self.maxaccel = maxaccel
        self.min_sats = min_sats
        self.ignore_fix_flag = ignore_fix_flag
        # Third alarm condition, independent of distance/speed: wind over
        # this speed AND the boat lying more than this many degrees off the
        # bow from it at the same time. Wind speed is left in knots (not
        # converted to/from m/s like boat speed) since WindInfo already
        # reports it natively in knots -- there's no internal m/s
        # representation for wind to begin with.
        self.wind_speed_threshold_kt = wind_speed_threshold_kt
        self.wind_heading_threshold_deg = wind_heading_threshold_deg

        self.icount = 0          # cumulative count of invalid/bad data ticks
        self.iseq = 0            # consecutive bad-data ticks right now
        self.mdist = 0.0         # max smoothed distance from ref
        self.mrawdist = 0.0      # max raw (unsmoothed) distance from ref
        self.avgdist = 0.0       # smoothed distance from ref
        self.pos_error = 0.0     # smoothed position error, in feet
        self.maxerror = 0.0      # max smoothed position error seen
        self.avgspeed = 0.0      # smoothed speed, m/s
        self.maxspeed = 0.0      # max smoothed speed seen
        self.mrawspeed = 0.0     # max raw speed seen
        self.track = 0.0
        self.avgtrack = 0.0
        self.distance = 0.0      # current raw distance from ref
        self.bearing = 0.0       # current bearing from ref
        self.speed = 0.0         # current raw speed
        self.effective_radius = 0.0  # adist shrunk by pos_error, floored at 0
        self.aset = False        # is the drag alarm currently active
        self.triggered_by_distance = False  # avgdist alone exceeded effective_radius this tick
        self.triggered_by_speed = False      # avgspeed alone exceeded thresholdspeed this tick
        self.triggered_by_heading = False    # wind speed AND relative heading both over threshold
        self.utc = None          # last-seen gpsd fix time, to detect a stalled feed

    def update(self, fix, reflat, reflon, adist, adata=False,
               wind_speed_knots=None, wind_angle_off_bow=None):
        """Feed one gpsd fix through the alarm decision logic.

        adist is the user-configured alarm radius in feet; adata is an
        externally-driven "data source is stalled" override (e.g. from a
        logger process healthcheck) that forces the alarm on.

        wind_speed_knots/wind_angle_off_bow (from nmea_gps_source.WindInfo)
        drive the heading-based trigger -- pass None for either (e.g. no
        masthead feed, or wind data stale) to leave it untriggerable rather
        than guessing.
        """
        result = FixUpdateResult()

        if fix.mode != 3 and not self.ignore_fix_flag:
            result.invalid_fix = True
            result.invalid_fix_is_new = (self.iseq == 0)
            self.iseq += 1
            self.icount += 1
            return result

        lat = float(fix.lat)
        lon = float(fix.lon)
        self.speed = fix.hspeed
        track = fix.track
        precision = fix.position_precision()
        self.pos_error = self.pos_error * 0.8 + 0.2 * precision[0] * FEET_PER_METER
        if self.pos_error > self.maxerror:
            self.maxerror = self.pos_error

        self.distance = calc_distance(reflat, reflon, lat, lon)
        self.bearing = calc_bearing(lat, lon, reflat, reflon)

        if math.isnan(self.distance) or self.speed > self.avgspeed + self.maxaccel:
            result.bad_distance = True
            self.distance = 0.0
            self.icount += 1
            self.iseq += 1
        else:
            if self.utc == fix.time:
                result.stale_time = True
                result.stale_time_is_new = (self.iseq == 0)
                self.icount += 1
                self.iseq += 1
            else:
                self.utc = fix.time
                if self.iseq > 0:
                    result.iseq_reset = True
                self.iseq = 0

            self.avgdist = self.avgdist * 0.8 + 0.2 * self.distance
            if self.avgdist > self.mdist:
                self.mdist = self.avgdist
            if self.distance > self.mrawdist:
                self.mrawdist = self.distance

            if math.isnan(self.speed):
                result.bad_speed = True
                self.speed = 0.0
                self.icount += 1
            else:
                self.avgspeed = self.avgspeed * 0.8 + 0.2 * self.speed
                if self.avgspeed > self.maxspeed:
                    self.maxspeed = self.avgspeed
                if self.speed > self.mrawspeed:
                    self.mrawspeed = self.speed

            if self.min_sats > fix.sats_valid:
                result.low_sats = True
                self.icount += 1

        if not math.isnan(track):
            self.avgtrack = self.avgtrack * 0.8 + 0.2 * track
            self.track = track
        else:
            self.track = self.avgtrack

        # adist shrinks by however much position uncertainty we currently
        # have, so the alarm gets more cautious as GPS accuracy drops -- but
        # if pos_error ever exceeds adist that would go negative, meaning
        # any nonnegative avgdist "exceeds" it and the alarm fires
        # regardless of actual position. Floor it at 0 instead: worst case,
        # the alarm becomes maximally sensitive (triggers on any measurable
        # distance from center), not permanently stuck on.
        self.effective_radius = max(0.0, adist - self.pos_error)

        self.triggered_by_distance = self.avgdist > self.effective_radius
        self.triggered_by_speed = self.avgspeed > self.thresholdspeed
        self.triggered_by_heading = bool(
            wind_speed_knots is not None
            and wind_angle_off_bow is not None
            and wind_speed_knots > self.wind_speed_threshold_kt
            and wind_angle_off_bow > self.wind_heading_threshold_deg
        )

        was_set = self.aset
        self.aset = bool(
            adata or self.triggered_by_distance or self.triggered_by_speed or self.triggered_by_heading
        )
        result.alarm_triggered = self.aset and not was_set
        result.alarm_cleared = was_set and not self.aset

        return result
