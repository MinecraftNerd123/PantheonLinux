import base64
import os
import re
import time

from pantheon import image, jsonutil, paths
from pantheon.desktop import Desktop
from pantheon.engine import HubEngine
from pantheon.framework import placement_plan
from pantheon.framework.environment import RobloxEnvironment
from pantheon.framework.runner import FlowRunner
from pantheon.hub import MacroHub
from pantheon.mount import GameCapture
from pantheon.packages import MacroPackages
from pantheon.platform import hypr


class PlacementStore:
    root = paths.data("placements")

    @staticmethod
    def step():
        return {"delayMs": 0, "id": "start-game", "kind": "start", "repeat": 1, "slot": 1, "timeoutMs": 30000, "x": 0, "y": 0}

    @classmethod
    def route(cls, ident, name):
        return {"id": ident, "name": name, "team": 1, "teams": [{"steps": [cls.step()]} for _ in range(8)]}

    @classmethod
    def defaults(cls):
        return {"routes": [cls.route("shared", "Shared setup")], "selectedRoute": "shared", "version": 1}

    @classmethod
    def folder(cls, mode):
        return os.path.join(cls.root, MacroPackages.load(MacroHub.mode(mode))["definition"]["game"])

    @classmethod
    def load(cls, mode):
        path = os.path.join(cls.folder(mode), "plan.json")
        if os.path.exists(path) and os.path.getsize(path) > 2000000:
            raise RuntimeError("Placement setup exceeds 2 MB.")
        p = placement_plan.validate(jsonutil.read(path)) if os.path.exists(path) else cls.defaults()
        definition = MacroPackages.load(mode)["definition"]
        for ident, spec in definition.get("maps", {}).items():
            found = False
            for route in p["routes"]:
                if route["id"] == ident:
                    found = True
                    route["parent"] = spec.get("parent", "")
            if not found:
                route = cls.route(ident, spec["name"])
                route["parent"] = spec.get("parent", "")
                p["routes"].append(route)
        frames = {}
        for r in p["routes"]:
            name = r["id"] if r.get("parent", "") == "" else r["parent"]
            frames[r["id"]] = 1 if os.path.exists(os.path.join(cls.folder(mode), name + ".png")) else 0
        return {"frames": frames, "playback": placement_plan.config(definition.get("playback", {})), "profile": p}

    @classmethod
    def save(cls, mode, raw):
        if HubEngine.busy():
            raise RuntimeError("Stop the macro before saving placement changes.")
        clean = placement_plan.validate(raw, True, MacroPackages.load(mode)["definition"].get("playback", {}))
        if jsonutil.utf8_size(jsonutil.stringify(clean)) > 2000000:
            raise RuntimeError("Placement setup exceeds 2 MB.")
        jsonutil.write(os.path.join(cls.folder(mode), "plan.json"), clean)
        return {"saved": 1}

    @classmethod
    def image_id(cls, mode, ident):
        placement_plan.route_id(ident)
        for route in cls.load(mode)["profile"]["routes"]:
            if route["id"] == ident:
                return ident if route.get("parent", "") == "" else route["parent"]
        return ident

    @classmethod
    def frame(cls, mode, ident):
        path = os.path.join(cls.folder(mode), cls.image_id(mode, ident) + ".png")
        if not os.path.exists(path):
            return {"image": ""}
        if os.path.getsize(path) > 5000000:
            raise RuntimeError("Screenshot exceeds the supported size.")
        with open(path, "rb") as file:
            return {"image": "data:image/png;base64," + base64.b64encode(file.read()).decode("ascii")}

    @classmethod
    def write_frame(cls, mode, ident, frame):
        if frame.width != 800 or frame.height != 600:
            raise RuntimeError("The spawn screenshot must be 800 x 600 pixels.")
        folder = cls.folder(mode)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, cls.image_id(mode, ident) + ".png")
        temp = path + ".capture.png"
        with open(temp, "wb") as file:
            file.write(frame.png())
        os.replace(temp, path)
        return cls.frame(mode, ident)

    @classmethod
    def capture(cls, mode, ident):
        return cls.write_frame(mode, ident, GameCapture.frame())

    @classmethod
    def camera_step(cls, items):
        for step in items:
            if step["action"] == "camera":
                return step
            for field in ("steps", "thenSteps", "elseSteps"):
                if field in step:
                    found = cls.camera_step(step[field])
                    if found:
                        return found
        return None

    @classmethod
    def align(cls, mode):
        if HubEngine.busy():
            raise RuntimeError("Stop the macro before aligning Roblox.")
        definition = MacroPackages.load(MacroHub.mode(mode))["definition"]
        camera = {"action": "camera", "id": "align-camera", "tilt": 299, "zoomIn": 20, "zoomOut": 20}
        for flow in definition["workflows"].values():
            found = cls.camera_step(flow["steps"])
            if found:
                camera = found
                break
        values = MacroPackages.values(mode)

        def prepare(address):
            environment = RobloxEnvironment(hypr(), address, MacroHub.log)
            runner = FlowRunner(definition, environment, values)
            runner.started = int(time.monotonic() * 1000)
            try:
                runner.execute_steps([camera], "Align Roblox")
            finally:
                environment.release()

        GameCapture.frame(prepare=prepare)
        return {"aligned": 1}

    @classmethod
    def import_frame(cls, mode, ident):
        if HubEngine.busy():
            raise RuntimeError("Stop the macro before importing a screenshot.")
        path = Desktop.open_file("Import spawn screenshot (800 x 600)", [("Images", ["*.png", "*.jpg", "*.jpeg", "*.bmp"])])
        if not path:
            return {"cancelled": 1}
        try:
            frame = image.load_file(path)
        except Exception:
            raise RuntimeError("The image could not be opened.") from None
        return cls.write_frame(mode, ident, frame)
