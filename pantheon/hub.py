import os
import re
import time

from pantheon import jsonutil, paths, store
from pantheon.framework.base import enum
from pantheon.packages import MacroPackages
from pantheon.store import Registry

_SHORTCUT = re.compile(r"^(?:[!^+#]{0,4})(?:F(?:[1-9]|1[0-9]|2[0-4])|[A-Z0-9]|Space|Home|End|Insert|Delete|PgUp|PgDn|Up|Down|Left|Right)$")


class MacroHub:
    config_path = paths.data("hub.json")
    history = []
    config = {"accent": "violet", "compact": 0, "developer": 0, "favorites": [], "root": "", "scale": 100, "selected": "", "theme": "default"}

    @staticmethod
    def mode(ident):
        if MacroPackages.has(ident):
            return ident
        raise ValueError("Unknown macro.")

    @classmethod
    def initialize(cls):
        if os.path.exists(cls.config_path):
            try:
                cls.config = cls.validate_config(jsonutil.read(cls.config_path))
            except Exception as err:
                cls.log("Preferences were reset: " + str(err))
        cls.config["root"] = paths.BUNDLED_MACROS
        cls.log("Pantheon Hub is ready.")

    @classmethod
    def validate_config(cls, c):
        if not isinstance(c, dict) or not isinstance(c.get("root"), str) or len(c["root"]) > 1024:
            raise ValueError("Invalid hub preferences.")
        if c.get("accent") not in ("violet", "neutral", "gold"):
            raise ValueError("Unknown accent colour.")
        if c.get("scale") not in (90, 100, 110):
            raise ValueError("Unknown interface size.")
        theme = c.get("theme", "default")
        enum(theme, ["default", "christmas", "midnight", "rose", "ember"], "interface theme")
        p = {"accent": c["accent"], "compact": store.integer(c["compact"], 0, 1, "Sidebar"),
             "developer": store.integer(c.get("developer", 0), 0, 1, "Developer mode"), "favorites": [],
             "root": paths.BUNDLED_MACROS, "scale": c["scale"],
             "selected": cls.mode(c["selected"]) if MacroPackages.has(c.get("selected")) else "", "theme": theme}
        if not isinstance(c.get("favorites"), list) or len(c["favorites"]) > 64:
            raise ValueError("Invalid favourites.")
        for ident in c["favorites"]:
            if MacroPackages.has(ident) and ident not in p["favorites"]:
                p["favorites"].append(ident)
        return p

    @classmethod
    def save_preferences(cls, raw):
        raw["root"] = cls.config["root"]
        clean = cls.validate_config(raw)
        jsonutil.write(cls.config_path, clean)
        cls.config = clean
        return clean

    @classmethod
    def select_workspace(cls, ident):
        from pantheon.engine import HubEngine
        from pantheon.mount import GameMount
        ident = cls.mode(ident)
        if HubEngine.state() in ("running", "paused") and ident != cls.config["selected"]:
            raise RuntimeError("Stop the current macro before switching workspaces.")
        cls.config["selected"] = ident
        GameMount.enabled = True
        jsonutil.write(cls.config_path, cls.config)
        return {"selected": ident}

    @classmethod
    def snapshot(cls):
        from pantheon.engine import HubEngine
        from pantheon.mount import GameMount
        try:
            roblox = 1 if GameMount.address or GameMount.game() else 0
        except Exception:
            roblox = 0
        return {"config": cls.config, "controls": HubControls.read(), "engine": HubEngine.snapshot(), "history": cls.history,
                "macros": MacroPackages.catalog(), "mounted": 1 if GameMount.address and not GameMount.hidden else 0,
                "pinned": 1 if GameMount.enabled else 0, "roblox": roblox, "warnings": MacroPackages.warnings}

    @classmethod
    def focus_roblox(cls):
        from pantheon.mount import GameMount
        from pantheon.platform import hypr
        game = GameMount.game()
        if not game:
            raise RuntimeError("Open Roblox in Sober first, then try again.")
        hypr().focus(game["address"])
        return {"focused": 1}

    @classmethod
    def log(cls, text):
        cls.history.insert(0, {"message": text, "time": time.strftime("%H:%M")})
        del cls.history[30:]


class HubControls:
    defaults = {"pauseBind": "F4", "resizeBind": "F1", "startBind": "F2"}

    @classmethod
    def read(cls):
        return {name: Registry.read(name, fallback) for name, fallback in cls.defaults.items()}

    @classmethod
    def validate(cls, raw):
        clean, seen = {}, set()
        for name in cls.defaults:
            key = raw.get(name) if isinstance(raw, dict) else None
            if not isinstance(key, str) or not _SHORTCUT.match(key):
                raise ValueError("Choose a supported keyboard shortcut for each control.")
            if key in seen:
                raise ValueError("Each control needs a different shortcut.")
            seen.add(key)
            clean[name] = key
        return clean

    @classmethod
    def apply(cls, raw):
        from pantheon.engine import HubEngine
        if HubEngine.busy():
            raise RuntimeError("Stop the macro before changing shortcuts.")
        clean = cls.validate(raw)
        Registry.write(clean, "controls")
        MacroHub.log("Updated macro keyboard shortcuts.")
        return clean
