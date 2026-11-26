import math
import time

from pantheon import findtext, ocr, paths
from pantheon.errors import FlowImageError
from pantheon.framework import base
from pantheon.platform import capture
from pantheon.platform.uinput import device

FRAME_TTL = 0.015


class RobloxEnvironment:
    def __init__(self, hypr, address, log, result=None, gate=None):
        self.hypr, self.address, self.log, self.result_callback, self.gate = hypr, address, log, result, gate
        self.held, self.paused_keys = {}, []
        self.input = device()
        self.left = self.top = 0
        self._frame, self._frame_time = None, 0.0

    def _client(self):
        active = self.hypr.query("activewindow")
        if isinstance(active, dict) and active.get("address") == self.address:
            return active, True
        return self.hypr.client(self.address), False

    def check(self):
        if self.gate:
            self.gate()
        client, focused = self._client()
        if not client or client.get("class") != paths.GAME_CLASS:
            raise RuntimeError("The workflow's Roblox client is unavailable.")
        if not focused:
            raise RuntimeError("Workflow stopped because Roblox lost focus.")
        if list(client["size"]) != [800, 600]:
            raise RuntimeError("The workflow requires an 800 x 600 Roblox client.")
        self.left, self.top = client["at"]

    def _invalidate(self):
        self._frame = None

    def frame(self, fresh=False):
        now = time.monotonic()
        if fresh or self._frame is None or now - self._frame_time > FRAME_TTL:
            self._frame = capture.grab(self.left, self.top, 800, 600)
            self._frame_time = time.monotonic()
        return self._frame

    def find(self, target):
        self.check()
        if target["kind"] == "point":
            return {"x": target["x"] + target["offsetX"], "y": target["y"] + target["offsetY"]}
        error1 = target["error1"] / 100 if target["error1"] else 0.000000001
        error0 = target["error0"] / 100 if target["error0"] else 0.000000001
        found = findtext.find(self.frame(), target["x"], target["y"], target["x"] + target["width"] - 1,
                              target["y"] + target["height"] - 1, error1, error0, target["pattern"], 1)
        if not found:
            return 0
        return {"x": found[0]["x"] + target["offsetX"], "y": found[0]["y"] + target["offsetY"]}

    def read_text(self, step):
        self.check()
        region = self.frame(True).crop(step["readX"], step["readY"], step["width"], step["height"])
        text = ocr.read(region, 2)
        self.check()
        return text

    def type_text(self, text, clear):
        self.check()
        self._invalidate()
        if clear:
            try:
                self.key("Control", True)
                self.key("A", True)
            finally:
                self.key("A", False)
                self.key("Control", False)
        for character in text:
            self.check()
            self.input.type_character(character)

    def move(self, x, y):
        self.check()
        base.integer(x, 0, 799, "Mouse X")
        base.integer(y, 0, 599, "Mouse Y")
        self._invalidate()
        self.hypr.move_cursor(self.left + x, self.top + y)
        self.check()

    def click(self, x, y, button="Left"):
        if button not in ("Left", "Right"):
            raise RuntimeError("Unsupported mouse button.")
        key = "LButton" if button == "Left" else "RButton"
        try:
            self.move(x, y)
            nudge = 1 if x < 799 else -1
            self.input.relative(nudge, 0)
            self.hypr.move_cursor(self.left + x, self.top + y)
            self.check()
            self.held[key] = True
            self.input.key(key, True)
            time.sleep(0.012)
            self.input.key(key, False)
            self._invalidate()
            self.sleep(50)
            self.check()
        finally:
            self.key(key, False)

    def scroll(self, direction, ticks):
        self.check()
        if direction not in ("Up", "Down"):
            raise RuntimeError("Unsupported scroll direction.")
        base.integer(ticks, 1, 10, "Scroll amount")
        x, y = self.hypr.cursor()
        if x < self.left or x >= self.left + 800 or y < self.top or y >= self.top + 600:
            raise RuntimeError("Move the mouse inside Roblox before scrolling.")
        self._invalidate()
        for _ in range(ticks):
            self.input.wheel(1 if direction == "Up" else -1)
            time.sleep(0.01)

    def key(self, key, down):
        if down:
            self.check()
            self.held[key] = True
            self._invalidate()
            self.input.key(key, True)
        elif key in self.held:
            try:
                self.input.key(key, False)
            finally:
                self.held.pop(key, None)

    def progress(self, rect):
        self.check()
        frame = self.frame(True)
        stride_x = max(1, math.ceil(rect["width"] / 64))
        stride_y = max(1, math.ceil(rect["height"] / 16))
        result = []
        for row in range(math.ceil(rect["height"] / stride_y)):
            y = rect["y"] + row * stride_y
            for col in range(math.ceil(rect["width"] / stride_x)):
                result.append(frame.pixel(rect["x"] + col * stride_x, y))
        if not result:
            raise FlowImageError("Could not capture the upgrade progress region.")
        return result

    def sleep(self, milliseconds):
        time.sleep(milliseconds / 1000)

    def result(self, won):
        if self.result_callback:
            self.result_callback(won)

    def trace(self, flow, step, action):
        self.log("Workflow " + str(flow) + " / " + str(step) + " · " + str(action))

    def suspend(self):
        self.paused_keys = list(self.held)
        self.release()

    def resume(self):
        try:
            for key in self.paused_keys:
                self.key(key, True)
        except Exception:
            self.release()
            raise
        finally:
            self.paused_keys = []

    def release(self):
        for key in list(self.held):
            try:
                self.input.key(key, False)
            except Exception:
                pass
        self.held = {}
