import json
import os


def _normalize(value):
    if value is True:
        return 1
    if value is False:
        return 0
    if value is None:
        return ""
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(value[k]) for k in sorted(value)}
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        result[key] = value
    return {k: result[k] for k in sorted(result)}


def parse(text):
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("utf-8")
    if text.startswith("﻿"):
        text = text[1:]
    try:
        return _normalize(json.loads(text, object_pairs_hook=_pairs))
    except json.JSONDecodeError as err:
        raise ValueError("Invalid JSON: " + err.msg) from None


def stringify(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def read(path):
    with open(path, "r", encoding="utf-8-sig") as file:
        return parse(file.read())


def write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    text = stringify(value)
    with open(temp, "w", encoding="utf-8") as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, path)


def utf8_size(value):
    return len(value.encode("utf-8"))
