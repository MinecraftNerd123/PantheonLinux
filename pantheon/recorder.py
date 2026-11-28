import os
import shutil
import threading
import time

from pantheon import paths
from pantheon.image import Frame
from pantheon.platform import capture

KEEP = 2
MIN_FRAMES = 5
INTERVAL = 3.0


def _half(frame):
    width, height, stride = frame.width // 2, frame.height // 2, frame.width * 3
    out = bytearray(width * height * 3)
    for y in range(height):
        row, start = frame.data[2 * y * stride:(2 * y + 1) * stride], y * width * 3
        for channel in range(3):
            out[start + channel:start + width * 3:3] = row[channel::6][:width]
    return Frame(width, height, bytes(out))


class Recorder:
    """Keeps the log and a low-rate half-size frame sequence of the last KEEP runs for debugging."""

    def __init__(self, name, origin):
        root = paths.data("recordings")
        os.makedirs(root, exist_ok=True)
        old = sorted((d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))), reverse=True)
        # Runs that failed within seconds would otherwise push out the recordings worth reading.
        useful = [d for d in old if sum(n.startswith("frame-") for n in os.listdir(os.path.join(root, d))) >= MIN_FRAMES]
        keep = set(useful[:KEEP - 1]) | {d for d in old[:5] if d not in useful and (not useful or d > useful[0])}
        for folder in old:
            if folder not in keep:
                shutil.rmtree(os.path.join(root, folder), ignore_errors=True)
        self.folder = os.path.join(root, time.strftime("%Y%m%d-%H%M%S") + "-" + "".join(c if c.isalnum() or c in "-_" else "_" for c in name)[:40])
        os.makedirs(self.folder, exist_ok=True)
        self.origin, self.started, self.done = origin, time.monotonic(), threading.Event()
        self.thread = threading.Thread(target=self._frames, name="pantheon-recorder", daemon=True)
        self.thread.start()

    def _grab(self):
        at = self.origin()
        return capture.grab(at[0], at[1], 800, 600) if at else None

    def _save(self, name, frame):
        with open(os.path.join(self.folder, name), "wb") as file:
            file.write(frame.png())

    def _frames(self):
        while not self.done.wait(INTERVAL):
            try:
                frame = self._grab()
                if frame:
                    self._save("frame-%05d.png" % int(time.monotonic() - self.started), _half(frame))
            except Exception:
                pass

    def log(self, line):
        try:
            with open(os.path.join(self.folder, "log.txt"), "a", encoding="utf-8") as file:
                file.write(line + "\n")
        except OSError:
            pass

    def snapshot(self, name):
        try:
            frame = self._grab()
            if frame:
                self._save(name + ".png", frame)
        except Exception:
            pass

    def finish(self, result):
        if self.done.is_set():
            return
        self.done.set()
        self.log("Result: " + result)
