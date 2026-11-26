import os
import re

from pantheon import jsonutil, paths
from pantheon.framework import base

FIELDS = "slot-1|slot-2|slot-3|slot-4|slot-5|slot-6|upgrade|sell|cancel|targeting|auto-upgrade"
NAMED = ["Backspace", "Delete", "Insert", "Home", "End", "PgUp", "PgDn", "Space", "Tab", "Enter", "Escape", "Up", "Down", "Left", "Right", "Shift", "Control"]


def defaults():
    return {"auto-upgrade": "K", "cancel": "Q", "sell": "X", "slot-1": "1", "slot-2": "2", "slot-3": "3", "slot-4": "4",
            "slot-5": "5", "slot-6": "6", "targeting": "T", "upgrade": "R"}


def key(value):
    if not isinstance(value, str):
        raise ValueError("Invalid in-game key.")
    value = re.sub(r"^key-", "", value)
    if re.match(r"^[a-zA-Z0-9]$", value):
        return value.upper()
    if re.match(r"^[fF]([1-9]|1[0-9]|2[0-4])$", value):
        return value.upper()
    for name in NAMED:
        if value.lower() == name.lower():
            return name
    raise ValueError("Unsupported in-game key: " + value)


def control(ident):
    if ident not in defaults():
        raise ValueError("Choose a supported in-game action.")
    return ident


def validate(raw):
    base.keys(raw, FIELDS)
    return {ident: key(raw.get(ident, fallback)) for ident, fallback in defaults().items()}


def path():
    return paths.data("ingame-controls.json")


def load():
    return validate(jsonutil.read(path())) if os.path.exists(path()) else defaults()


def save(raw):
    clean = validate(raw)
    jsonutil.write(path(), clean)
    return clean


def upgrade(definition):
    from pantheon.framework import settings
    controls = definition.get("controls", {})
    for action, binding in list(controls.items()):
        if not isinstance(binding, dict) or "setting" not in binding:
            continue
        all_specs = settings.specs(definition)
        ident = binding["setting"]
        if ident not in all_specs or all_specs[ident]["type"] != "select":
            continue
        spec = all_specs[ident]
        control(action)
        for option in spec["options"]:
            key(option["value"])
        all_specs[ident] = {"control": action, "default": key(spec["default"]), "label": spec["label"], "type": "key"}
        del controls[action]
    return definition


def definition_check(definition):
    from pantheon.framework import settings
    seen = set()
    for ident, spec in settings.specs(definition).items():
        if spec["type"] == "key" and "control" in spec:
            if spec["control"] in seen:
                raise ValueError("Each in-game action can have only one key override setting.")
            seen.add(spec["control"])
    controls = definition.get("controls", {})
    base.keys(controls, FIELDS)
    for ident, binding in controls.items():
        if isinstance(binding, dict):
            base.keys(binding, "setting")
            spec = settings.spec(definition, binding["setting"])
            if spec["type"] == "key":
                key(spec["default"])
            elif spec["type"] != "select":
                raise ValueError("Key overrides require a dropdown setting.")
            if spec["type"] == "select":
                for option in spec["options"]:
                    key(option["value"])
        else:
            key(binding)


def resolve(definition, values, fallback):
    from pantheon.framework import settings
    clean = validate(fallback)
    for ident, binding in definition.get("controls", {}).items():
        clean[ident] = key(values[binding["setting"]] if isinstance(binding, dict) else binding)
    seen = set()
    for setting, spec in settings.specs(definition).items():
        if spec["type"] != "key" or "control" not in spec:
            continue
        action = control(spec["control"])
        if action in seen:
            raise ValueError("More than one key setting overrides " + action + ".")
        seen.add(action)
        clean[action] = key(values[setting])
    return clean
