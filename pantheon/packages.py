import os
import re
import uuid

from pantheon import jsonutil, paths, version
from pantheon.framework import play_controls, schema, settings
from pantheon.framework.base import integer, keys, enum, trim

_ID = re.compile(r"^macro-[a-z0-9][a-z0-9-]{0,40}$")


class MacroPackages:
    root = paths.data("macros")
    bundled = paths.BUNDLED_MACROS
    cached = None
    warnings = []
    developer = staticmethod(lambda: False)
    busy = staticmethod(lambda: False)
    clipboard = staticmethod(lambda text: None)
    save_dialog = staticmethod(lambda name, title, filters: "")
    confirm = staticmethod(lambda text, title: False)

    @staticmethod
    def valid_id(ident):
        return isinstance(ident, str) and bool(_ID.match(ident))

    @classmethod
    def path(cls, ident):
        if not cls.valid_id(ident):
            raise ValueError("Invalid macro identifier.")
        return os.path.join(cls.root, ident + ".json")

    @classmethod
    def has(cls, ident):
        return cls.valid_id(ident) and (os.path.exists(cls.path(ident)) or os.path.exists(os.path.join(cls.bundled, ident + ".json")))

    @classmethod
    def read(cls, path):
        if os.path.getsize(path) > 500000:
            raise RuntimeError("Macro configuration exceeds 500 KB.")
        with open(path, "r", encoding="utf-8-sig") as file:
            return cls.parse_json(file.read())

    @classmethod
    def validate(cls, raw):
        keys(raw, "format|version|id|definition|minPantheonVersion")
        if "minPantheonVersion" in raw:
            version.require(raw["minPantheonVersion"])
        if raw["format"] != "pantheon-macro" or not cls.valid_id(raw["id"]):
            raise ValueError("Unsupported Pantheon macro configuration.")
        integer(raw["version"], 1, 1, "Macro format version")
        play_controls.upgrade(raw["definition"])
        schema.validate(raw["definition"])
        if trim(raw["definition"]["name"]) == "":
            raise ValueError("Give the macro a name.")
        if "entry" not in raw["definition"]:
            raise ValueError("Choose a starting sequence for the macro.")
        return raw

    @classmethod
    def load(cls, ident):
        path = cls.path(ident)
        if os.path.exists(path):
            saved = cls.read(path)
            package = cls.validate(saved["package"])
            revision = integer(saved["revision"], 1, 1000000, "Macro revision")
        else:
            package = cls.validate(cls.read(os.path.join(cls.bundled, ident + ".json")))
            revision = 0
        if package["id"] != ident:
            raise RuntimeError("Macro identity does not match its file.")
        return {"definition": package["definition"], "package": ident, "revision": revision, "source": "local" if revision else "bundled"}

    @classmethod
    def catalog(cls, force=False):
        if cls.cached is not None and not force:
            return cls.cached
        found, result = set(), []
        cls.warnings = []
        for folder in (cls.bundled, cls.root):
            if not os.path.isdir(folder):
                continue
            for name in os.listdir(folder):
                if name.startswith("macro-") and name.endswith(".json") and cls.valid_id(name[:-5]):
                    found.add(name[:-5])
        for ident in sorted(found):
            if len(result) >= 64:
                cls.warnings.append("Only the first 64 authored macros were loaded.")
                break
            try:
                loaded = cls.load(ident)
                result.append({"custom": 1, "icon": loaded["definition"].get("icon", "pantheon"), "id": ident, "installed": 1,
                               "name": loaded["definition"]["name"], "opened": 0, "seconds": 0})
            except Exception as err:
                cls.warnings.append("Could not load " + ident + ": " + str(err))
        cls.cached = result
        return result

    @classmethod
    def write(cls, ident, definition, revision):
        package = cls.validate({"definition": definition, "format": "pantheon-macro", "id": ident, "minPantheonVersion": version.CURRENT, "version": 1})
        raw = {"package": package, "revision": revision}
        if jsonutil.utf8_size(jsonutil.stringify(raw)) > 500000:
            raise RuntimeError("Macro configuration exceeds 500 KB.")
        jsonutil.write(cls.path(ident), raw)
        cls.cached = None
        return cls.load(ident)

    @classmethod
    def require_developer(cls):
        if not cls.developer():
            raise RuntimeError("Enable developer mode to author macro configurations.")

    @classmethod
    def new(cls):
        cls.require_developer()
        if len(cls.catalog()) >= 64:
            raise RuntimeError("A workspace supports up to 64 authored macros.")
        index = len(cls.catalog()) + 1
        ident = "macro-" + uuid.uuid4().hex
        definition = {"client": {"height": 600, "width": 800}, "entry": "main", "game": "roblox-td", "icon": "pantheon",
                      "mode": "custom", "name": "New macro %d" % index, "runMode": "once", "settings": {}, "targets": {},
                      "version": 1, "workflows": {"main": {"name": "Main sequence", "steps": []}}}
        return cls.write(ident, definition, 1)

    @classmethod
    def settings_path(cls, ident):
        return os.path.join(cls.root, "settings", ident + ".json")

    @classmethod
    def save(cls, ident, definition, revision):
        cls.require_developer()
        integer(revision, 0, 1000000, "Editor revision")
        if cls.busy():
            raise RuntimeError("Stop the macro before changing its definition.")
        current = cls.load(ident)
        if revision != current["revision"]:
            raise RuntimeError("The macro changed elsewhere. Reload before saving.")
        schema.validate(definition)
        path = cls.settings_path(ident)
        values = cls.read(path) if os.path.exists(path) else {}
        clean, warnings = {}, []
        for key, spec in settings.specs(definition).items():
            try:
                clean[key] = settings.value(spec, values.get(key, spec["default"]))
            except Exception:
                clean[key] = spec["default"]
                warnings.append("Reset setting to its default: " + spec["label"])
        result = cls.write(ident, definition, revision + 1)
        if os.path.exists(path):
            jsonutil.write(path, clean)
        result["warnings"] = warnings
        return result

    @classmethod
    def parse(cls, text):
        return cls.validate(cls.parse_json(text))

    @staticmethod
    def parse_json(text):
        if not isinstance(text, str) or jsonutil.utf8_size(text) > 500000:
            raise ValueError("Macro text exceeds 500 KB.")
        quoted = escaped = False
        depth = nodes = 0
        for c in text:
            if quoted:
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == '"':
                    quoted = False
            elif c == '"':
                quoted = True
            elif c in "{[":
                depth += 1
                nodes += 1
                if depth > 64 or nodes > 16384:
                    raise ValueError("Macro JSON nesting or size limit exceeded.")
            elif c in "}]":
                depth -= 1
                if depth < 0:
                    raise ValueError("Invalid macro JSON.")
        if quoted or depth != 0:
            raise ValueError("Invalid macro JSON.")
        return jsonutil.parse(text)

    @classmethod
    def preview(cls, text):
        p = cls.parse(text)
        d = p["definition"]
        actions = {}
        for flow in d["workflows"].values():
            cls.count_actions(flow["steps"], actions)
        return {"actions": {k: actions[k] for k in sorted(actions)}, "entry": d["entry"], "exists": 1 if cls.has(p["id"]) else 0,
                "game": d["game"], "icon": d.get("icon", "pantheon"), "id": p["id"], "name": d["name"],
                "runMode": d.get("runMode", "once"), "sequences": len(d["workflows"]), "settings": len(settings.specs(d)),
                "targets": len(d["targets"])}

    @classmethod
    def count_actions(cls, items, actions):
        for step in items:
            actions[step["action"]] = actions.get(step["action"], 0) + 1
            for field in ("steps", "thenSteps", "elseSteps"):
                if field in step:
                    cls.count_actions(step[field], actions)

    @classmethod
    def install(cls, text):
        if cls.busy():
            raise RuntimeError("Stop the macro before importing another configuration.")
        p = cls.parse(text)
        if cls.has(p["id"]):
            raise RuntimeError("A macro with this identity is already installed. Existing macros are not overwritten by imports.")
        if len(cls.catalog()) >= 64:
            raise RuntimeError("A workspace supports up to 64 authored macros.")
        return cls.write(p["id"], p["definition"], 1)

    @classmethod
    def export(cls, ident):
        d = cls.load(ident)["definition"]
        cls.clipboard(jsonutil.stringify({"definition": d, "format": "pantheon-macro", "id": ident, "minPantheonVersion": version.CURRENT, "version": 1}))
        return {"copied": 1}

    @classmethod
    def export_draft(cls, raw):
        cls.require_developer()
        keys(raw, "id|definition|format")
        p = cls.validate({"definition": raw["definition"], "format": "pantheon-macro", "id": raw["id"], "minPantheonVersion": version.CURRENT, "version": 1})
        text = jsonutil.stringify(p)
        if jsonutil.utf8_size(text) > 500000:
            raise RuntimeError("Macro configuration exceeds 500 KB.")
        fmt = raw.get("format", "text")
        enum(fmt, ["text", "json"], "export format")
        if fmt == "text":
            cls.clipboard(text)
            return {"copied": 1}
        path = cls.save_dialog(p["id"] + ".json", "Export macro", [("JSON configuration", ["*.json"])])
        if not path:
            return {"cancelled": 1}
        if not path.lower().endswith(".json"):
            path += ".json"
            if os.path.exists(path) and not cls.confirm("This JSON file already exists. Replace it?", "Export macro"):
                return {"cancelled": 1}
        with open(path, "w", encoding="utf-8") as file:
            file.write(text)
        return {"saved": 1}

    @classmethod
    def values(cls, ident):
        definition, path = cls.load(ident)["definition"], cls.settings_path(ident)
        return settings.values(definition, cls.read(path) if os.path.exists(path) else {})

    @classmethod
    def save_values(cls, ident, values):
        if cls.busy():
            raise RuntimeError("Stop the macro before saving settings.")
        clean = settings.values(cls.load(ident)["definition"], values)
        jsonutil.write(cls.settings_path(ident), clean)
        return clean
