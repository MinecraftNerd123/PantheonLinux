import re
import time

from pantheon.errors import FlowImageError
from pantheon.framework import base

_ID = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
LABELS = {"panel": "Selected unit panel", "money": "Not enough money", "limit": "Placement limit", "unique": "Unique-unit conflict"}


def now():
    return int(time.monotonic() * 1000)


def config(raw, definition=None):
    base.keys(raw, "panel|money|limit|unique|closeX|closeY|retryMs|observeMs")
    for field in ("panel", "money", "limit", "unique"):
        value = raw.get(field, "")
        if value == "" and field in ("limit", "unique"):
            continue
        if not isinstance(value, str) or not _ID.match(value):
            raise ValueError("Select a captured image for Placement feedback: " + LABELS[field] + ".")
        if definition is not None and (value not in definition["targets"] or definition["targets"][value]["kind"] != "pattern"):
            raise ValueError("Select an existing image for Placement feedback: " + LABELS[field] + ".")
    seen = set()
    for field in ("panel", "money", "limit", "unique"):
        value = raw.get(field, "")
        if value == "":
            continue
        if value in seen:
            raise ValueError("Use different images for each Placement feedback message and the unit panel.")
        seen.add(value)
    base.integer(raw["closeX"], 0, 799, "Close panel X")
    base.integer(raw["closeY"], 0, 599, "Close panel Y")
    base.integer(raw["retryMs"], 250, 5000, "Placement retry interval")
    base.integer(raw["observeMs"], 100, 3000, "Placement response timeout")
    return raw


UNCONFIRMED_ATTEMPTS = 3


def _check(r, deadline):
    r.check()
    if now() >= deadline:
        raise FlowImageError("Placement timed out while waiting for money or confirmation. Increase this Place action's timeout or check its feedback images.")


def _ended(r):
    return any(r.find(t, 0) for t in r.result_targets)


def _message(r, c):
    for field in ("limit", "unique", "money"):
        if c.get(field, "") != "" and r.find(c[field], 0):
            return field
    return ""


def _close(r, c):
    if not r.find(c["panel"], 0):
        return
    r.environment.click(c["closeX"], c["closeY"])
    started = now()
    while r.find(c["panel"], 0):
        if now() - started >= c["observeMs"]:
            raise FlowImageError("Could not close the unit panel during placement feedback handling.")
        r.wait(50)


def _observe(r, c, deadline, messages=True):
    started = now()
    while True:
        _check(r, deadline)
        if _ended(r):
            return "ended"
        if r.find(c["panel"], 0):
            return "placed"
        if messages:
            found = _message(r, c)
            if found:
                return found
        if now() - started >= c["observeMs"]:
            return ""
        r.wait(50)


def place(r, action, c):
    deadline = now() + action["timeoutMs"]
    unconfirmed = 0
    try:
        r.hold([r.play_keys["cancel"]], 30)
        _close(r, c)
        while True:
            _check(r, deadline)
            if _ended(r):
                return -1
            while _message(r, c) != "":
                _check(r, deadline)
                if _ended(r):
                    return -1
                r.wait(50)
            r.hold([r.play_keys["slot-%d" % action["slot"]]], 30)
            r.wait(100)
            r.environment.click(action["x"], action["y"])
            result = _observe(r, c, deadline)
            r.hold([r.play_keys["cancel"]], 30)
            if result == "ended":
                return -1
            if result == "placed":
                return 1
            if result in ("limit", "unique"):
                r.environment.trace("Placement skipped", action["id"], "Placement limit reached" if result == "limit" else "Unique-unit conflict")
                return 0
            r.environment.click(action["x"], action["y"])
            inspected = _observe(r, c, deadline, False)
            if inspected == "placed":
                return 1
            if inspected == "ended":
                return -1
            if result != "money":
                # A dropped click looks like this too; clicking the same spot again is safe because it selects the unit if one landed.
                unconfirmed += 1
                if unconfirmed >= UNCONFIRMED_ATTEMPTS:
                    raise FlowImageError("Placement could not be confirmed and no money or limit message was detected. Check the panel image and saved coordinate.")
                r.environment.trace("Placement retry", action["id"], "Not confirmed; trying again")
                r.wait(c["retryMs"])
                continue
            r.environment.trace("Placement waiting", action["id"], "Not enough money; retrying")
            r.wait(c["retryMs"])
    finally:
        try:
            r.hold([r.play_keys["cancel"]], 30)
        finally:
            _close(r, c)
