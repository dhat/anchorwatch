import os
import unittest
from unittest import mock

import serial
from buzzer import Buzzer


class FakeSerialConn:
    """Stand-in for a serial.Serial connection whose writes can be made to
    fail, so we can test the timeout/error-handling paths without real
    hardware."""

    def __init__(self, *a, **k):
        self.is_open = True
        self.written = []
        self.write_should_raise = None
        self.closed = False

    def write(self, data):
        if self.write_should_raise is not None:
            raise self.write_should_raise
        self.written.append(data)

    def close(self):
        self.closed = True
        self.is_open = False


class BuzzerTests(unittest.TestCase):
    def test_available_is_a_cheap_existence_check_that_does_not_open_anything(self):
        buzzer = Buzzer('/dev/does-not-exist-anywhere', 9600)
        self.assertFalse(buzzer.available())

    def test_send_is_a_no_op_when_device_does_not_exist(self):
        buzzer = Buzzer('/dev/does-not-exist-anywhere', 9600)
        buzzer.send(0x18)  # should not raise
        self.assertIsNone(buzzer._serial)

    def test_opens_connection_once_and_reuses_it_across_multiple_sends(self):
        with mock.patch.object(os.path, 'exists', return_value=True), \
             mock.patch.object(serial, 'Serial', side_effect=FakeSerialConn) as serial_ctor:
            buzzer = Buzzer('/dev/buzzer', 9600)
            buzzer.send(0x18)
            buzzer.send(0x28)
            buzzer.send(0x11)
        serial_ctor.assert_called_once()
        self.assertEqual(len(buzzer._serial.written), 3)

    def test_open_is_called_with_a_bounded_timeout(self):
        with mock.patch.object(os.path, 'exists', return_value=True), \
             mock.patch.object(serial, 'Serial', side_effect=FakeSerialConn) as serial_ctor:
            buzzer = Buzzer('/dev/buzzer', 9600, timeout=2.5)
            buzzer.send(0x18)
        _, kwargs = serial_ctor.call_args
        self.assertEqual(kwargs.get('timeout'), 2.5)
        self.assertEqual(kwargs.get('write_timeout'), 2.5)

    def test_write_failure_does_not_raise_and_closes_the_connection(self):
        with mock.patch.object(os.path, 'exists', return_value=True), \
             mock.patch.object(serial, 'Serial', side_effect=FakeSerialConn):
            buzzer = Buzzer('/dev/buzzer', 9600)
            buzzer.send(0x18)  # opens successfully
            buzzer._serial.write_should_raise = serial.SerialTimeoutException("write timed out")
            buzzer.send(0x28)  # should not raise
        self.assertIsNone(buzzer._serial)

    def test_reopens_automatically_on_next_send_after_a_failure(self):
        with mock.patch.object(os.path, 'exists', return_value=True), \
             mock.patch.object(serial, 'Serial', side_effect=FakeSerialConn) as serial_ctor:
            buzzer = Buzzer('/dev/buzzer', 9600)
            buzzer.send(0x18)
            buzzer._serial.write_should_raise = OSError("device disconnected")
            buzzer.send(0x28)  # fails, closes
            buzzer.send(0x11)  # should reopen and succeed
        self.assertEqual(serial_ctor.call_count, 2)
        self.assertEqual(len(buzzer._serial.written), 1)

    def test_open_failure_is_non_fatal(self):
        with mock.patch.object(os.path, 'exists', return_value=True), \
             mock.patch.object(serial, 'Serial', side_effect=serial.SerialException("no such device")):
            buzzer = Buzzer('/dev/buzzer', 9600)
            buzzer.send(0x18)  # should not raise
        self.assertIsNone(buzzer._serial)

    def test_close_is_safe_to_call_when_never_opened(self):
        buzzer = Buzzer('/dev/does-not-exist-anywhere', 9600)
        buzzer.close()  # should not raise

    def test_buzzer_once_sequences_red_and_buzzer_on_then_off(self):
        with mock.patch.object(os.path, 'exists', return_value=True), \
             mock.patch.object(serial, 'Serial', side_effect=FakeSerialConn), \
             mock.patch('time.sleep'):
            buzzer = Buzzer('/dev/buzzer', 9600)
            buzzer.buzzer_once(duration=0)
        from buzzer import RED_ON, BUZZER_ON, BUZZER_OFF, RED_OFF
        self.assertEqual(
            buzzer._serial.written,
            [bytes([RED_ON]), bytes([BUZZER_ON]), bytes([BUZZER_OFF]), bytes([RED_OFF])])


if __name__ == '__main__':
    unittest.main()
