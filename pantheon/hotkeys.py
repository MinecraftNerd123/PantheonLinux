import os
import shlex
import stat
import threading

from pantheon import paths

NAMES = {"Space": "space", "PgUp": "Prior", "PgDn": "Next"}
MODS = {"!": "ALT", "^": "CTRL", "+": "SHIFT", "#": "SUPER"}
MODMASK = {"SHIFT": 1, "CTRL": 4, "ALT": 8, "SUPER": 64}


def parse(key):
    mods = []
    while key and key[0] in MODS:
        mods.append(MODS[key[0]])
        key = key[1:]
    return mods, NAMES.get(key, key)


class Hotkeys:
    def __init__(self, hypr, callback):
        self.hypr, self.callback = hypr, callback
        self.path = os.path.join(paths.runtime_dir(), "pantheon-hotkeys")
        self.active = None
        self.viewer = False
        self.lock = threading.Lock()
        if os.path.exists(self.path) and not stat.S_ISFIFO(os.stat(self.path).st_mode):
            os.unlink(self.path)
        if not os.path.exists(self.path):
            os.mkfifo(self.path, 0o600)
        self.fd = os.open(self.path, os.O_RDWR)
        threading.Thread(target=self._read, name="pantheon-hotkeys", daemon=True).start()

    def _read(self):
        buffer = b""
        while True:
            try:
                chunk = os.read(self.fd, 256)
            except OSError:
                return
            if not chunk:
                continue
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                action = line.decode("ascii", "ignore").strip()
                if action in ("setup", "toggle", "pause", "stop", "copy"):
                    self.callback(action)

    def command(self, action):
        return "sh -c " + shlex.quote('exec 3<>"$0"; echo %s >&3' % action) + " " + shlex.quote(self.path)

    def conflicts(self, keys):
        taken = set()
        try:
            for b in self.hypr.binds():
                if (b.get("description") or "") == "Pantheon":
                    continue
                taken.add((b.get("modmask", 0), str(b.get("key", "")).lower()))
        except Exception:
            return []
        found = []
        for key in keys.values():
            mods, name = parse(key)
            if (sum(MODMASK[m] for m in mods), name.lower()) in taken:
                found.append(key)
        return found

    def update(self, enabled, keys):
        signature = (tuple(sorted(keys.items())) if enabled else None, self.viewer)
        with self.lock:
            if signature == self.active:
                return
            binds = []
            if enabled:
                for name, action in (("resizeBind", "setup"), ("startBind", "toggle"), ("pauseBind", "pause")):
                    mods, key = parse(keys[name])
                    binds.append((mods, key, self.command(action)))
            if self.viewer:
                binds.append((["CTRL", "SHIFT"], "C", self.command("copy")))
            if binds:
                self.hypr.set_binds(binds)
            else:
                self.hypr.clear_binds()
            self.active = signature

    def close(self):
        try:
            self.hypr.clear_binds()
        except Exception:
            pass
        self.active = None
