import math
import unittest

from geo import calc_distance, calc_bearing, decdeg2dms


class GeoTests(unittest.TestCase):
    def test_distance_to_self_is_zero(self):
        self.assertAlmostEqual(calc_distance(42.0, -70.0, 42.0, -70.0), 0.0)

    def test_distance_one_degree_latitude_is_about_60_nm(self):
        feet = calc_distance(0.0, 0.0, 1.0, 0.0)
        nm = feet / 6076.12
        self.assertAlmostEqual(nm, 60.0, delta=1.0)

    def test_bearing_due_north(self):
        bearing = calc_bearing(0.0, 0.0, 1.0, 0.0)
        self.assertAlmostEqual(bearing, 0.0, delta=0.01)

    def test_bearing_due_east(self):
        bearing = calc_bearing(0.0, 0.0, 0.0, 1.0)
        self.assertAlmostEqual(bearing, 90.0, delta=0.01)

    def test_bearing_due_south(self):
        bearing = calc_bearing(1.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(bearing, 180.0, delta=0.01)

    def test_bearing_due_west(self):
        bearing = calc_bearing(0.0, 1.0, 0.0, 0.0)
        self.assertAlmostEqual(bearing, 270.0, delta=0.01)

    def test_bearing_stays_within_0_360(self):
        bearing = calc_bearing(10.0, 10.0, 5.0, -5.0)
        self.assertGreaterEqual(bearing, 0.0)
        self.assertLess(bearing, 360.0)

    def test_decdeg2dms_positive(self):
        degrees, minutes, seconds = decdeg2dms(42.5)
        self.assertEqual(degrees, 42)
        self.assertEqual(minutes, 30)
        self.assertAlmostEqual(seconds, 0.0, delta=1e-6)

    def test_decdeg2dms_negative_keeps_sign_on_degrees(self):
        degrees, minutes, seconds = decdeg2dms(-70.25)
        self.assertEqual(degrees, -70)
        self.assertEqual(minutes, 15)


if __name__ == '__main__':
    unittest.main()
