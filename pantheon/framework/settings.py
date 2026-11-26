from pantheon.framework import base, play_controls


def specs(definition):
    return definition.get("settings", {})


def spec(definition, ident):
    base.identifier(ident)
    all_specs = specs(definition)
    if ident not in all_specs:
        raise ValueError("Unknown macro setting: " + ident)
    return all_specs[ident]


def option(setting, value):
    for item in setting["options"]:
        if item["value"] == value:
            return item
    raise ValueError("Unknown setting option: " + str(value))


def value(setting, raw):
    kind = setting["type"]
    if kind in ("toggle", "checkbox"):
        base.integer(raw, 0, 1, "Toggle value")
    elif kind == "number":
        base.integer(raw, setting["min"], setting["max"], "Setting value")
    elif kind == "select":
        option(setting, raw)
    elif kind == "key":
        return play_controls.key(raw)
    elif kind in ("multiselect", "priority"):
        if not isinstance(raw, list) or len(raw) > len(setting["options"]):
            raise ValueError("Invalid setting selections.")
        seen = set()
        for item in raw:
            option(setting, item)
            if item in seen:
                raise ValueError("Duplicate setting selection.")
            seen.add(item)
    else:
        raise ValueError("Unsupported macro setting type.")
    return raw


def validate(definition):
    all_specs = specs(definition)
    if not isinstance(all_specs, dict) or len(all_specs) > 32:
        raise ValueError("A macro supports up to 32 settings.")
    for ident, setting in all_specs.items():
        base.identifier(ident)
        base.keys(setting, "label|type|default|min|max|options|control")
        base.text(setting["label"], 80, "setting label")
        base.enum(setting["type"], ["toggle", "checkbox", "number", "select", "multiselect", "priority", "key"], "setting control")
        if setting["type"] == "key" and "control" not in setting:
            raise ValueError("Choose an in-game action for this key override.")
        if "control" in setting:
            if setting["type"] != "key":
                raise ValueError("Only key settings can override an in-game control.")
            play_controls.control(setting["control"])
        if base.trim(setting["label"]) == "":
            raise ValueError("Macro settings need a visible label.")
        if setting["type"] == "number":
            base.integer(setting["min"], 0, 1000000, "Setting minimum")
            base.integer(setting["max"], setting["min"], 1000000, "Setting maximum")
        elif "min" in setting or "max" in setting:
            raise ValueError("Only number settings have numeric bounds.")
        if setting["type"] in ("select", "multiselect", "priority"):
            options = setting["options"]
            if not isinstance(options, list) or len(options) < 1 or len(options) > 32:
                raise ValueError("Choice settings need one to 32 options.")
            seen = set()
            for item in options:
                base.keys(item, "value|label|target|map")
                base.identifier(item["value"])
                base.text(item["label"], 80, "option label")
                if base.trim(item["label"]) == "":
                    raise ValueError("Setting options need a visible label.")
                if item["value"] in seen:
                    raise ValueError("Duplicate setting option.")
                seen.add(item["value"])
                if item.get("map", "") != "" and item["map"] not in definition.get("maps", {}):
                    raise ValueError("Setting option refers to an unknown placement map.")
                if item.get("target", "") != "":
                    base.target(definition, item["target"])
        elif "options" in setting:
            raise ValueError("This setting does not support options.")
        value(setting, setting["default"])


def values(definition, raw):
    if not isinstance(raw, dict):
        raise ValueError("Invalid macro settings.")
    all_specs = specs(definition)
    for ident in raw:
        if ident not in all_specs:
            raise ValueError("Unknown saved setting: " + ident)
    return {ident: value(setting, raw.get(ident, setting["default"])) for ident, setting in all_specs.items()}


def check(definition, item):
    base.keys(item, "setting|comparison|value")
    setting = spec(definition, item["setting"])
    op = item["comparison"]
    if setting["type"] == "key":
        item["value"] = play_controls.key(item["value"])
    base.enum(op, ["equals", "not-equals", "greater", "less", "contains", "not-contains"], "setting comparison")
    if setting["type"] in ("priority", "multiselect"):
        if op not in ("contains", "not-contains"):
            raise ValueError("List settings support contains / does not contain.")
        option(setting, item["value"])
    else:
        if op not in ("equals", "not-equals") and not (setting["type"] == "number" and op in ("greater", "less")):
            raise ValueError("Unsupported setting comparison.")
        value(setting, item["value"])


def match(current, item):
    actual, expected = current[item["setting"]], item["value"]
    op = item["comparison"]
    if op == "equals":
        return actual == expected
    if op == "not-equals":
        return actual != expected
    if op == "greater":
        return actual > expected
    if op == "less":
        return actual < expected
    found = expected in actual
    return found if op == "contains" else not found


def parameter(definition, raw, low, high, label):
    if isinstance(raw, dict):
        base.keys(raw, "setting")
        setting = spec(definition, raw["setting"])
        if setting["type"] == "number":
            lo, hi = setting["min"], setting["max"]
        elif low == 0 and high == 1 and setting["type"] in ("toggle", "checkbox"):
            lo, hi = 0, 1
        else:
            raise ValueError(label + " needs a numeric setting.")
        if lo < low or hi > high:
            raise ValueError("%s requires a setting bounded from %d to %d." % (label, low, high))
    else:
        base.integer(raw, low, high, label)
