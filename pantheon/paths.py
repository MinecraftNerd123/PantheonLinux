import os

APP_ID = "io.github.MinecraftNerd123.PantheonLinux"
GAME_CLASS = os.environ.get("PANTHEON_GAME_CLASS", "org.vinegarhq.Sober")
PACKAGE = os.path.dirname(os.path.abspath(__file__))


def _resources():
    return os.environ.get("PANTHEON_RESOURCES") or os.path.dirname(PACKAGE)


def _data():
    override = os.environ.get("PANTHEON_DATA")
    if override:
        return override
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "pantheon")


RESOURCES = _resources()
UI = os.path.join(RESOURCES, "Lib", "ui")
BUNDLED_MACROS = os.path.join(RESOURCES, "macros")
DATA = _data()
FLATPAK = os.path.exists("/.flatpak-info")


def data(*parts):
    return os.path.join(DATA, *parts)


def runtime_dir():
    base = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    if FLATPAK:
        app = os.path.join(base, "app", os.environ.get("FLATPAK_ID", APP_ID))
        os.makedirs(app, exist_ok=True)
        return app
    return base
