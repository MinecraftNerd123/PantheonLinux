import ctypes
import fcntl
import os
import struct
import threading
import time

EV_SYN, EV_KEY, EV_REL = 0x00, 0x01, 0x02
SYN_REPORT = 0
REL_X, REL_Y, REL_WHEEL, REL_WHEEL_HI_RES = 0x00, 0x01, 0x08, 0x0B
BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = 0x110, 0x111, 0x112
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_RELBIT = 0x40045564, 0x40045565, 0x40045566
UI_DEV_SETUP, UI_DEV_CREATE, UI_DEV_DESTROY = 0x405C5503, 0x5501, 0x5502

KEYS = {
    "Escape": 1, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10, "0": 11, "-": 12, "=": 13,
    "Backspace": 14, "Tab": 15, "Q": 16, "W": 17, "E": 18, "R": 19, "T": 20, "Y": 21, "U": 22, "I": 23, "O": 24, "P": 25,
    "[": 26, "]": 27, "Enter": 28, "Control": 29, "A": 30, "S": 31, "D": 32, "F": 33, "G": 34, "H": 35, "J": 36, "K": 37,
    "L": 38, ";": 39, "'": 40, "`": 41, "Shift": 42, "\\": 43, "Z": 44, "X": 45, "C": 46, "V": 47, "B": 48, "N": 49,
    "M": 50, ",": 51, ".": 52, "/": 53, "Alt": 56, "Space": 57, "F1": 59, "F2": 60, "F3": 61, "F4": 62, "F5": 63, "F6": 64,
    "F7": 65, "F8": 66, "F9": 67, "F10": 68, "F11": 87, "F12": 88, "Home": 102, "Up": 103, "PgUp": 104, "Left": 105,
    "Right": 106, "End": 107, "Down": 108, "PgDn": 109, "Insert": 110, "Delete": 111, "F13": 183, "F14": 184, "F15": 185,
    "F16": 186, "F17": 187, "F18": 188, "F19": 189, "F20": 190, "F21": 191, "F22": 192, "F23": 193, "F24": 194,
    "LButton": BTN_LEFT, "RButton": BTN_RIGHT, "MButton": BTN_MIDDLE,
}
SHIFTED = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0", "_": "-",
           "+": "=", "{": "[", "}": "]", ":": ";", '"': "'", "~": "`", "|": "\\", "<": ",", ">": ".", "?": "/"}


class InputUnavailable(RuntimeError):
    pass


class VirtualInput:
    def __init__(self):
        self.fd = None
        self.lock = threading.Lock()

    def open(self):
        with self.lock:
            if self.fd is not None:
                return
            try:
                fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
            except OSError as err:
                raise InputUnavailable("Pantheon cannot send input: /dev/uinput is not writable (" + err.strerror +
                                       "). Add your user to the 'input' group or install the Pantheon udev rule.") from None
            try:
                for ev in (EV_KEY, EV_REL, EV_SYN):
                    fcntl.ioctl(fd, UI_SET_EVBIT, ev)
                for code in sorted(set(KEYS.values())):
                    fcntl.ioctl(fd, UI_SET_KEYBIT, code)
                for code in (REL_X, REL_Y, REL_WHEEL, REL_WHEEL_HI_RES):
                    fcntl.ioctl(fd, UI_SET_RELBIT, code)
                name = b"Pantheon virtual input"
                setup = struct.pack("HHHH80sI", 0x03, 0x1209, 0x5054, 1, name, 0)
                fcntl.ioctl(fd, UI_DEV_SETUP, setup)
                fcntl.ioctl(fd, UI_DEV_CREATE)
            except OSError as err:
                os.close(fd)
                raise InputUnavailable("Could not create the virtual input device: " + err.strerror) from None
            self.fd = fd
        time.sleep(0.4)

    def close(self):
        with self.lock:
            if self.fd is None:
                return
            try:
                fcntl.ioctl(self.fd, UI_DEV_DESTROY)
            except OSError:
                pass
            os.close(self.fd)
            self.fd = None

    def _emit(self, events):
        self.open()
        now = time.time()
        sec, usec = int(now), int((now % 1) * 1000000)
        payload = b"".join(struct.pack("llHHi", sec, usec, t, c, v) for t, c, v in events)
        payload += struct.pack("llHHi", sec, usec, EV_SYN, SYN_REPORT, 0)
        with self.lock:
            os.write(self.fd, payload)

    def key(self, name, down):
        code = KEYS.get(name)
        if code is None:
            raise ValueError("Unsupported key: " + name)
        self._emit([(EV_KEY, code, 1 if down else 0)])

    def relative(self, dx, dy):
        events = []
        if dx:
            events.append((EV_REL, REL_X, dx))
        if dy:
            events.append((EV_REL, REL_Y, dy))
        if events:
            self._emit(events)

    def wheel(self, ticks):
        self._emit([(EV_REL, REL_WHEEL, ticks), (EV_REL, REL_WHEEL_HI_RES, ticks * 120)])

    def type_character(self, char):
        shift = False
        if char == " ":
            name = "Space"
        elif char.isalpha() and char.isascii():
            name, shift = char.upper(), char.isupper()
        elif char in SHIFTED:
            name, shift = SHIFTED[char], True
        elif char in KEYS:
            name = char
        else:
            raise ValueError("Cannot type character: " + repr(char))
        try:
            if shift:
                self.key("Shift", True)
            self.key(name, True)
            time.sleep(0.008)
            self.key(name, False)
        finally:
            if shift:
                self.key("Shift", False)
        time.sleep(0.008)


_DEVICE = VirtualInput()


def device():
    return _DEVICE
