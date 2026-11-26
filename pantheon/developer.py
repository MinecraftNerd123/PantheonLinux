import os
import re

from pantheon import findtext, image, paths, store
from pantheon.desktop import Desktop
from pantheon.framework.schema import bits_from_base64
from pantheon.hub import MacroHub
from pantheon.mount import GameCapture

_PATTERN = re.compile(r"^\|<>\*(\d{1,3})\$(\d{1,3})\.([0-9+/A-Za-z]+)$")


class DeveloperTools:
    frame_path = paths.data("developer", "capture.png")
    viewing = False
    selection = None
    matches = []
    last_frame = None

    @staticmethod
    def require():
        if not MacroHub.config.get("developer", 0):
            raise RuntimeError("Enable developer mode in Settings first.")

    @classmethod
    def coordinates(cls, enabled):
        cls.require()
        store.integer(enabled, 0, 1, "Coordinate viewer")
        if enabled:
            cls.viewing = True
            Desktop.viewer(True)
        else:
            cls.stop()
        return {"enabled": enabled}

    @classmethod
    def stop(cls):
        if cls.viewing:
            Desktop.viewer(False)
        cls.viewing = False

    @classmethod
    def _save(cls, frame):
        os.makedirs(os.path.dirname(cls.frame_path), exist_ok=True)
        with open(cls.frame_path, "wb") as file:
            file.write(frame.png())
        cls.last_frame = frame

    @classmethod
    def capture(cls, select=False):
        cls.require()
        cls.selection = None
        probe = None
        if select:
            def probe(address, client, frame):
                cls.selection = Desktop.pick(client, frame, False)
        frame = GameCapture.frame(probe)
        if select and not cls.selection:
            return {"cancelled": 1}
        cls._save(frame)
        result = cls.frame()
        if select:
            result["region"] = cls.selection
        return result

    @classmethod
    def pick_point(cls, require_developer=True):
        if require_developer:
            cls.require()
        cls.selection = None

        def probe(address, client, frame):
            cls.selection = Desktop.pick(client, frame, True)

        GameCapture.frame(probe)
        return cls.selection if cls.selection else {"cancelled": 1}

    @classmethod
    def frame(cls):
        with open(cls.frame_path, "rb") as file:
            import base64
            return {"image": "data:image/png;base64," + base64.b64encode(file.read()).decode("ascii")}

    @staticmethod
    def region(raw):
        if not isinstance(raw, dict):
            raise ValueError("Select an image region first.")
        x, y = store.integer(raw["x"], 0, 799, "X"), store.integer(raw["y"], 0, 599, "Y")
        w, h = store.integer(raw["width"], 1, 800 - x, "Width"), store.integer(raw["height"], 1, 600 - y, "Height")
        return {"height": h, "width": w, "x": x, "y": y}

    @classmethod
    def copy(cls, raw):
        cls.require()
        r = cls.region(raw)
        Desktop.clipboard("x := %d, y := %d\nw := %d, h := %d\nleft := %d, top := %d, right := %d, bottom := %d\nclickX := %d, clickY := %d" % (
            r["x"], r["y"], r["width"], r["height"], r["x"], r["y"], r["x"] + r["width"] - 1, r["y"] + r["height"] - 1,
            r["x"] + r["width"] // 2, r["y"] + r["height"] // 2))
        return {"copied": 1}

    @staticmethod
    def pattern(raw):
        match = _PATTERN.match(raw) if isinstance(raw, str) and len(raw) <= 80100 else None
        if not match:
            raise ValueError("Invalid FindText grayscale pattern.")
        threshold, width = int(match.group(1)), int(match.group(2))
        if threshold > 255 or width < 1 or width > 800:
            raise ValueError("Invalid FindText dimensions or threshold.")
        bits = re.sub(r"10*$", "", bits_from_base64(match.group(3)))
        if len(bits) < width or len(bits) % width or len(bits) // width > 600:
            raise ValueError("Invalid FindText pattern height.")
        return raw

    @classmethod
    def copy_pattern(cls, raw):
        cls.require()
        Desktop.clipboard(cls.pattern(raw))
        return {"copied": 1}

    @classmethod
    def test(cls, raw):
        cls.require()
        pattern = cls.pattern(raw["pattern"])
        tolerance = store.integer(raw["tolerance"], 0, 20, "Mismatch percentage") / 100
        region = cls.region(raw.get("region", {"height": 600, "width": 800, "x": 0, "y": 0}))
        cls.matches = []

        def probe(address, client, frame):
            rate = tolerance if tolerance else 0.000000001
            found = findtext.find(frame, region["x"], region["y"], region["x"] + region["width"] - 1,
                                  region["y"] + region["height"] - 1, rate, rate, pattern, 100)
            cls.matches = [{"x": m["x"], "y": m["y"]} for m in found[:100]]

        GameCapture.frame(probe)
        return {"matches": cls.matches}

    @classmethod
    def export(cls, raw):
        cls.require()
        r = cls.region(raw)
        if not os.path.exists(cls.frame_path):
            raise RuntimeError("Capture Roblox before exporting an image region.")
        path = Desktop.save_file("detection.png", "Save detection image", [("PNG image", ["*.png"])])
        if not path:
            return {"cancelled": 1}
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            frame = image.load_file(cls.frame_path)
        except Exception:
            raise RuntimeError("Could not open the developer capture.") from None
        crop = frame.crop(r["x"], r["y"], r["width"], r["height"])
        with open(path, "wb") as file:
            file.write(crop.png())
        return {"saved": 1}
