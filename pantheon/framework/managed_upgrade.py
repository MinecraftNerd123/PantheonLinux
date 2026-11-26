import math
import re
import time

from pantheon.errors import FlowImageError
from pantheon.framework import base

_ID = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
LABELS = {"panel": "Selected unit panel", "affordable": "Affordable upgrade button", "max": "Max upgrade"}


def now():
    return int(time.monotonic() * 1000)


def config(raw, definition=None):
    raw = dict(raw)
    for field in ("pathColor", "pathTolerance", "pathRadius", "pathClearance", "pathAttempts", "placementConfirmMs"):
        raw.pop(field, None)
    base.keys(raw, "panel|affordable|max|closeX|closeY|progress|intervalMs|settleMs|confirmMs|policy")
    for field in ("panel", "affordable", "max"):
        if field not in raw or not isinstance(raw[field], str) or not _ID.match(raw[field]):
            raise ValueError("Select a captured image for Managed upgrades: " + LABELS[field] + ".")
        if definition is not None:
            if raw[field] not in definition["targets"] or definition["targets"][raw[field]]["kind"] != "pattern":
                raise ValueError("Select an existing captured image for Managed upgrades: " + LABELS[field] + ".")
    if definition is not None:
        area = definition["targets"][raw["affordable"]]
        if area["width"] == 800 and area["height"] == 600:
            raise ValueError("Restrict the Affordable upgrade button target to its button area using Search captured area only.")
    if raw["panel"] == raw["affordable"] or raw["panel"] == raw["max"] or raw["max"] == raw["affordable"]:
        raise ValueError("Use different managed-upgrade images for panel, affordable and Max.")
    base.integer(raw["closeX"], 0, 799, "Close panel X")
    base.integer(raw["closeY"], 0, 599, "Close panel Y")
    rect = raw["progress"]
    base.keys(rect, "x|y|width|height")
    base.integer(rect["x"], 0, 799, "Progress X")
    base.integer(rect["y"], 0, 599, "Progress Y")
    base.integer(rect["width"], 1, min(200, 800 - rect["x"]), "Progress width")
    base.integer(rect["height"], 1, min(80, 600 - rect["y"]), "Progress height")
    base.integer(raw["intervalMs"], 500, 10000, "Upgrade interval")
    base.integer(raw["settleMs"], 100, 2000, "Panel settle time")
    base.integer(raw["confirmMs"], 500, 10000, "Upgrade confirmation timeout")
    base.enum(raw["policy"], ["affordable", "save"], "upgrade policy")
    return raw


def difference(a, b):
    if not isinstance(a, list) or not isinstance(b, list) or not a or len(a) != len(b):
        raise FlowImageError("Could not sample the upgrade progress region.")
    changed = 0
    for pixel, other in zip(a, b):
        if (abs(((pixel >> 16) & 255) - ((other >> 16) & 255)) > 32
                or abs(((pixel >> 8) & 255) - ((other >> 8) & 255)) > 32
                or abs((pixel & 255) - (other & 255)) > 32):
            changed += 1
    return changed


def stable(a, b):
    return difference(a, b) <= max(1, len(a) * 1 // 100)


def changed(a, b):
    return difference(a, b) >= max(2, math.ceil(len(a) * 0.02))


class ManagedUpgrade:
    def __init__(self, runner, cfg, live):
        self.runner, self.cfg, self.units, self.next, self.index = runner, cfg, [], 0, 1
        for priority in range(1, 11):
            for ident, state in sorted(live.items()):
                if state["placement"]["managedPriority"] == priority:
                    self.units.append({"id": ident, "state": state, "done": False, "confirmed": 0})

    def close(self):
        r, c = self.runner, self.cfg
        if not r.find(c["panel"], 0):
            return
        r.environment.click(c["closeX"], c["closeY"])
        if not self.wait_panel(False):
            raise FlowImageError("Could not close the unit panel before checking match results.")

    def wait_panel(self, present):
        r, started = self.runner, now()
        while True:
            if bool(r.find(self.cfg["panel"], 0)) == present:
                return True
            remaining = self.cfg["settleMs"] - (now() - started)
            if remaining <= 0:
                return False
            r.wait(min(50, remaining))

    def result_visible(self):
        return any(self.runner.find(t, 0) for t in self.runner.result_targets)

    def tick(self):
        try:
            self.check_unit()
        except FlowImageError:
            if not self.result_visible():
                raise

    def check_unit(self):
        r, c = self.runner, self.cfg
        if not self.units or now() < self.next:
            return
        self.next = now() + c["intervalMs"]
        selected = None
        for _ in range(len(self.units)):
            if self.index > len(self.units):
                self.index = 1
            item = self.units[self.index - 1]
            self.index += 1
            if not item["done"]:
                selected = item
                break
        if not selected:
            return
        p = selected["state"]["placement"]
        try:
            opened = False
            for _ in range(3):
                if self.result_visible():
                    return
                if r.find(c["panel"], 0):
                    opened = True
                    break
                r.environment.click(p["x"], p["y"])
                if self.wait_panel(True):
                    opened = True
                    break
                r.wait(200)
            if not opened:
                if self.result_visible():
                    return
                raise FlowImageError("Managed upgrade could not open the selected unit panel after 3 clicks. Check its placement coordinate and panel image.")
            if r.find(c["max"], 0):
                selected["done"] = True
                self.next = 0
                return
            if not r.find(c["affordable"], 0):
                if c["policy"] == "save":
                    self.index -= 1
                return
            before = r.environment.progress(c["progress"])
            r.hold([r.play_keys["upgrade"]], 40)
            started, confirmed = now(), False
            while True:
                r.wait(33)
                if not r.find(c["panel"], 0):
                    break
                if r.find(c["max"], 0):
                    selected["done"], confirmed = True, True
                    break
                after = r.environment.progress(c["progress"])
                if changed(before, after):
                    r.wait(33)
                    if r.find(c["panel"], 0):
                        settled = r.environment.progress(c["progress"])
                        if stable(after, settled) and changed(before, settled):
                            confirmed = True
                            break
                if now() - started >= c["confirmMs"]:
                    break
            if not confirmed:
                raise FlowImageError("Upgrade was not confirmed. Check the upgrade key and progress capture before retrying.")
            self.next = 0
            selected["confirmed"] += 1
            if p["managedLimit"] and selected["confirmed"] >= p["managedLimit"]:
                selected["done"] = True
            r.environment.trace("Managed upgrade", selected["id"], "Confirmed upgrade %d" % selected["confirmed"])
            if c["policy"] == "save" and not selected["done"]:
                self.index -= 1
        finally:
            self.close()
