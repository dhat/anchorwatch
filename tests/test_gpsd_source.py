import time
import unittest
from unittest import mock

import gpsd
from gpsd_source import GpsdSource


class FakeSocket:
    def __init__(self):
        self.timeout_set_to = None

    def settimeout(self, value):
        self.timeout_set_to = value


class GpsdSourceTests(unittest.TestCase):
    def test_connect_failure_does_not_raise_from_get_current(self):
        with mock.patch.object(gpsd, 'connect', side_effect=OSError("connection refused")):
            source = GpsdSource()
            fix = source.get_current()
        self.assertEqual(fix.mode, 0)

    def test_successful_connect_sets_a_read_timeout_on_the_socket(self):
        fake_sock = FakeSocket()
        with mock.patch.object(gpsd, 'connect', return_value=None), \
             mock.patch.object(gpsd, 'gpsd_socket', fake_sock):
            source = GpsdSource(read_timeout=7.0)
            source.connect()
        self.assertEqual(fake_sock.timeout_set_to, 7.0)

    def test_get_current_delegates_to_gpsd_once_connected(self):
        sentinel_fix = object()
        with mock.patch.object(gpsd, 'connect', return_value=None), \
             mock.patch.object(gpsd, 'gpsd_socket', FakeSocket()), \
             mock.patch.object(gpsd, 'get_current', return_value=sentinel_fix):
            source = GpsdSource()
            source.connect()
            fix = source.get_current()
        self.assertIs(fix, sentinel_fix)

    def test_read_failure_marks_down_and_returns_blank_fix_instead_of_raising(self):
        with mock.patch.object(gpsd, 'connect', return_value=None), \
             mock.patch.object(gpsd, 'gpsd_socket', FakeSocket()), \
             mock.patch.object(gpsd, 'get_current', side_effect=OSError("connection reset")):
            source = GpsdSource()
            source.connect()
            fix = source.get_current()
        self.assertEqual(fix.mode, 0)
        self.assertFalse(source._connected)

    def test_reconnect_attempts_are_throttled(self):
        with mock.patch.object(gpsd, 'connect', side_effect=OSError("refused")) as connect_mock:
            source = GpsdSource(reconnect_interval=1.0)
            for _ in range(5):
                fix = source.get_current()
                self.assertEqual(fix.mode, 0)
        self.assertEqual(connect_mock.call_count, 1,
                          "should only attempt one reconnect within the throttle window")

    def test_reconnects_once_gpsd_becomes_reachable_again(self):
        sentinel_fix = object()
        with mock.patch.object(gpsd, 'connect', side_effect=OSError("refused")):
            source = GpsdSource(reconnect_interval=0.05)
            fix = source.get_current()
            self.assertEqual(fix.mode, 0)

        time.sleep(0.1)  # let the throttle window elapse

        with mock.patch.object(gpsd, 'connect', return_value=None), \
             mock.patch.object(gpsd, 'gpsd_socket', FakeSocket()), \
             mock.patch.object(gpsd, 'get_current', return_value=sentinel_fix):
            fix = source.get_current()

        self.assertIs(fix, sentinel_fix)


if __name__ == '__main__':
    unittest.main()
