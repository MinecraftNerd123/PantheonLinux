import re

_ID = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
_CONTROL = re.compile(r"[\x00-\x1f]")


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def trim(value):
    return value.strip(" \t")


def keys(raw, allowed):
    if not isinstance(raw, dict):
        raise ValueError("Expected a definition object.")
    fields = allowed.split("|")
    for key in raw:
        if key == "name" and "action" in raw and "id" in raw:
            text(raw["name"], 80, "step name")
            continue
        if key not in fields:
            raise ValueError("Unknown definition field: " + key)


def integer(value, low, high, label):
    if not is_int(value) or value < low or value > high:
        raise ValueError("%s must be an integer from %d to %d." % (label, low, high))
    return value


def text(value, max_length, label):
    if not isinstance(value, str) or len(value) > max_length or _CONTROL.search(value):
        raise ValueError("Invalid " + label + ".")
    return value


def identifier(value):
    if not isinstance(value, str) or not _ID.match(value):
        raise ValueError("Use lowercase letters, digits and hyphens for identifiers.")
    return value


def enum(value, choices, label):
    if isinstance(value, str) and value in choices:
        return value
    raise ValueError("Unsupported " + label + ".")


def target(raw, ident):
    identifier(ident)
    if ident not in raw["targets"]:
        raise ValueError("Missing target: " + ident)


def reference(raw, ident):
    identifier(ident)
    if ident not in raw["workflows"]:
        raise ValueError("Missing workflow: " + ident)


def text_equals(a, b):
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return a == b
