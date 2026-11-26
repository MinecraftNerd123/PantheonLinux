import os
import time

from pantheon import jsonutil, paths


def integer(value, low, high, label):
    if not isinstance(value, int) or isinstance(value, bool) or value < low or value > high:
        raise ValueError("%s must be a whole number from %d to %d." % (label, low, high))
    return value


class Registry:
    path = paths.data("settings.json")

    @classmethod
    def _load(cls):
        if not os.path.exists(cls.path):
            return {}
        try:
            data = jsonutil.read(cls.path)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @classmethod
    def read(cls, name, fallback):
        return cls._load().get(name, fallback)

    @classmethod
    def write(cls, values, label):
        current = cls._load()
        before = {}
        for field in values:
            before[field] = {"exists": 1 if field in current else 0, "value": current.get(field, "")}
        stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + str(int(time.monotonic() * 1000))
        backup = paths.data("backups", label + "-" + stamp + ".json")
        jsonutil.write(backup, {"key": "settings.json", "values": before})
        updated = dict(current)
        for field, value in values.items():
            updated[field] = value if isinstance(value, str) else str(value)
        try:
            jsonutil.write(cls.path, updated)
        except Exception as err:
            raise RuntimeError("Settings could not be applied. Previous settings were kept. " + str(err)) from None
        return backup
