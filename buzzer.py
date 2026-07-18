"""USB buzzer/light controller, reusing one persistent serial connection.

Previously this program opened a brand-new serial.Serial() connection for
every single buzzer/light command, with no read/write timeout set. If the
device ever became slow or unresponsive, that blocking open()/write() call
could stall the entire single-threaded alarm loop indefinitely -- no
display update, no way to read menu input -- until the device recovered or
the OS eventually gave up. This showed up as a real freeze: the buzzer
stopped cycling and the screen stopped updating together, exactly what
you'd see if execution were stuck inside one of those calls.

This module opens one connection at startup and reuses it for every
command, and sets a bounded write timeout so an unresponsive device fails
fast (and is treated as temporarily absent) instead of hanging the
program. It does not fully eliminate every possible hang -- pyserial's
timeout/write_timeout bound read/write calls, not the initial device open()
itself, which has no timeout parameter in pyserial. But since the
connection is now opened once rather than on every tick, that residual
risk window is far smaller than before.
"""
import os

import serial

RED_ON = 0x11
RED_OFF = 0x21
RED_BLINK = 0x41

YELLOW_ON = 0x12
YELLOW_OFF = 0x22
YELLOW_BLINK = 0x42

GREEN_ON = 0x14
GREEN_OFF = 0x24
GREEN_BLINK = 0x44

BUZZER_ON = 0x18
BUZZER_OFF = 0x28
BUZZER_BLINK = 0x48

# Bounds how long a stuck/unresponsive device can block a single command.
DEFAULT_TIMEOUT = 1.0


class Buzzer:
    """Reuses one serial connection to the USB buzzer/light, if present."""

    def __init__(self, device, baudrate, timeout=DEFAULT_TIMEOUT):
        self.device = device
        self.baudrate = baudrate
        self.timeout = timeout
        self._serial = None

    def available(self):
        """Cheap existence check -- does not open the device."""
        return os.path.exists(self.device)

    def _ensure_open(self):
        if self._serial is not None and self._serial.is_open:
            return True
        if not self.available():
            return False
        try:
            self._serial = serial.Serial(
                self.device, self.baudrate, timeout=self.timeout, write_timeout=self.timeout)
            return True
        except (serial.SerialException, OSError) as e:
            print("Buzzer: could not open", self.device, "--", e)
            self._serial = None
            return False

    def send(self, cmd):
        """Send one command byte. Never raises -- failures are logged and
        treated as a (temporarily) absent buzzer rather than crashing the
        program or blocking it indefinitely."""
        if not self._ensure_open():
            return
        try:
            self._serial.write(bytes([cmd]))
        except (serial.SerialException, OSError) as e:
            print("Buzzer: write failed --", e)
            self.close()

    def close(self):
        if self._serial is not None:
            try:
                self._serial.close()
            except (serial.SerialException, OSError):
                pass
            self._serial = None

    def buzzer_once(self, duration=0.5):
        from time import sleep
        self.send(RED_ON)
        self.send(BUZZER_ON)
        sleep(duration)
        self.send(BUZZER_OFF)
        self.send(RED_OFF)

    def light_on(self):
        self.send(RED_BLINK)

    def buzzer_on(self):
        self.send(BUZZER_ON)

    def buzzer_off(self):
        self.send(BUZZER_OFF)

    def buzzer_light_off(self):
        self.send(BUZZER_OFF)
        self.send(RED_OFF)
