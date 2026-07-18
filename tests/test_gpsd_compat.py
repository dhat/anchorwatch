import unittest

import gpsd
import gpsd_compat


# Shaped after the real poll response captured from gpsd 3.25 talking to an
# NMEA0183 read-only driver that sends GSA (uSat) but not GSV (no
# per-satellite array, no nSat).
PACKET_NO_SATELLITE_ARRAY = {
    "class": "POLL",
    "active": True,
    "tpv": [{
        "class": "TPV", "mode": 3, "lat": 42.0, "lon": -70.0,
        "time": "2026-07-18T19:07:08.000Z", "alt": 8.6,
    }],
    "sky": [{
        "class": "SKY", "uSat": 9,
        "gdop": 1.0, "hdop": 1.0, "pdop": 1.0, "tdop": 1.0,
        "vdop": 1.0, "xdop": 1.0, "ydop": 1.0,
    }],
}

PACKET_WITH_SATELLITE_ARRAY = {
    "class": "POLL",
    "active": True,
    "tpv": [{
        "class": "TPV", "mode": 3, "lat": 42.0, "lon": -70.0,
        "time": "2026-07-18T19:07:08.000Z", "alt": 8.6,
    }],
    "sky": [{
        "class": "SKY",
        "satellites": [
            {"used": True}, {"used": True}, {"used": False},
        ],
    }],
}


class GpsdSatelliteFallbackTests(unittest.TestCase):
    def setUp(self):
        self._original_from_json = gpsd.GpsResponse.from_json

    def tearDown(self):
        gpsd.GpsResponse.from_json = self._original_from_json

    def test_unpatched_library_reports_zero_when_satellite_array_missing(self):
        # Documents the upstream bug this module works around.
        result = gpsd.GpsResponse.from_json(PACKET_NO_SATELLITE_ARRAY)
        self.assertEqual(result.sats, 0)
        self.assertEqual(result.sats_valid, 0)

    def test_patch_falls_back_to_usat_when_satellite_array_missing(self):
        gpsd_compat.patch_satellite_counts()
        result = gpsd.GpsResponse.from_json(PACKET_NO_SATELLITE_ARRAY)
        self.assertEqual(result.sats_valid, 9)
        self.assertEqual(result.sats, 9)  # nSat absent too, so falls back to uSat

    def test_patch_leaves_normal_satellite_array_counting_untouched(self):
        gpsd_compat.patch_satellite_counts()
        result = gpsd.GpsResponse.from_json(PACKET_WITH_SATELLITE_ARRAY)
        self.assertEqual(result.sats, 3)
        self.assertEqual(result.sats_valid, 2)

    def test_patch_is_idempotent(self):
        gpsd_compat.patch_satellite_counts()
        gpsd_compat.patch_satellite_counts()
        result = gpsd.GpsResponse.from_json(PACKET_NO_SATELLITE_ARRAY)
        self.assertEqual(result.sats_valid, 9)


if __name__ == '__main__':
    unittest.main()
