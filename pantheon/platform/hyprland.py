import json
import os
import socket
import threading


class HyprlandUnavailable(RuntimeError):
    pass


def _lua(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


class Hyprland:
    def __init__(self):
        self.path = self._socket()
        self._lua_mode = None
        self._lock = threading.Lock()
        self._legacy_binds = []

    @staticmethod
    def _socket():
        runtime = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
        base = os.path.join(runtime, "hypr")
        signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        if signature:
            path = os.path.join(base, signature, ".socket.sock")
            if os.path.exists(path):
                return path
        try:
            entries = sorted(os.listdir(base), key=lambda e: os.path.getmtime(os.path.join(base, e)), reverse=True)
        except OSError:
            entries = []
        for entry in entries:
            path = os.path.join(base, entry, ".socket.sock")
            if os.path.exists(path):
                return path
        raise HyprlandUnavailable("Pantheon requires Hyprland. Its IPC socket was not found.")

    def request(self, command):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(3)
            try:
                sock.connect(self.path)
            except OSError as err:
                raise HyprlandUnavailable("Could not reach Hyprland: " + str(err)) from None
            sock.sendall(command.encode("utf-8"))
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        return b"".join(chunks).decode("utf-8", "replace")

    def query(self, command):
        text = self.request("j/" + command)
        try:
            return json.loads(text)
        except ValueError:
            raise HyprlandUnavailable("Unexpected Hyprland response to " + command + ": " + text[:200]) from None

    @property
    def lua(self):
        if self._lua_mode is None:
            self._lua_mode = self.request("eval return 1").strip() == "ok"
        return self._lua_mode

    def _check(self, response, what):
        text = response.strip()
        if text != "ok" and not text.startswith("ok"):
            raise RuntimeError("Hyprland could not " + what + ": " + text[:300])

    def eval(self, code, what="run a command"):
        self._check(self.request("eval " + code), what)

    def dispatch(self, legacy, lua, what):
        if self.lua:
            self.eval("hl.dispatch(" + lua + ")", what)
        else:
            self._check(self.request("dispatch " + legacy), what)

    def clients(self):
        return self.query("clients")

    def client(self, address):
        for c in self.clients():
            if c.get("address") == address:
                return c
        return None

    def find(self, cls, title=None):
        found = []
        for c in self.clients():
            if c.get("class") != cls or not c.get("mapped", True):
                continue
            if title is not None and c.get("title") != title:
                continue
            found.append(c)
        found.sort(key=lambda c: (c.get("hidden", False), -(c["size"][0] * c["size"][1])))
        return found[0] if found else None

    def active(self):
        data = self.query("activewindow")
        return data.get("address", "") if isinstance(data, dict) else ""

    def cursor(self):
        data = self.query("cursorpos")
        return int(data["x"]), int(data["y"])

    def monitors(self):
        return self.query("monitors")

    def float(self, address, enabled=True):
        self.dispatch(("setfloating " if enabled else "settiled ") + "address:" + address,
                      "hl.dsp.window.float({action=%s, window=%s})" % (_lua("enable" if enabled else "disable"), _lua("address:" + address)),
                      "change floating state")

    def move(self, address, x, y):
        self.dispatch("movewindowpixel exact %d %d,address:%s" % (x, y, address),
                      "hl.dsp.window.move({x=%d, y=%d, window=%s})" % (x, y, _lua("address:" + address)), "move the window")

    def resize(self, address, width, height):
        self.dispatch("resizewindowpixel exact %d %d,address:%s" % (width, height, address),
                      "hl.dsp.window.resize({x=%d, y=%d, window=%s})" % (width, height, _lua("address:" + address)), "resize the window")

    def focus(self, address):
        self.dispatch("focuswindow address:" + address, "hl.dsp.focus({window=%s})" % _lua("address:" + address), "focus the window")

    def to_workspace(self, address, workspace):
        self.dispatch("movetoworkspacesilent %s,address:%s" % (workspace, address),
                      "hl.dsp.window.move({workspace=%s, follow=false, window=%s})" % (_lua(workspace), _lua("address:" + address)),
                      "move the window to a workspace")

    def fullscreen_state(self, address, internal, client):
        if not self.lua:
            self.focus(address)
        self.dispatch("fullscreenstate %d %d" % (internal, client),
                      "hl.dsp.window.fullscreen_state({internal=%d, client=%d, window=%s})" % (internal, client, _lua("address:" + address)),
                      "change fullscreen state")

    def raise_window(self, address):
        self.dispatch("alterzorder top,address:" + address,
                      "hl.dsp.window.alter_zorder({mode=\"top\", window=%s})" % _lua("address:" + address), "raise the window")

    def move_cursor(self, x, y):
        self.dispatch("movecursor %d %d" % (x, y), "hl.dsp.cursor.move({x=%d, y=%d})" % (x, y), "move the cursor")

    def binds(self):
        return self.query("binds")

    def set_binds(self, binds):
        with self._lock:
            self.clear_binds()
            if self.lua:
                code = ["pantheon_binds = pantheon_binds or {}"]
                for mods, key, command in binds:
                    combo = " + ".join(mods + [key])
                    code.append("table.insert(pantheon_binds, hl.bind(%s, hl.dsp.exec_cmd(%s), {description=%s}))"
                                % (_lua(combo), _lua(command), _lua("Pantheon")))
                self.eval("; ".join(code), "register shortcuts")
            else:
                for mods, key, command in binds:
                    self._check(self.request("keyword bind %s,%s,exec,%s" % (" ".join(mods), key, command)), "register shortcuts")
                    self._legacy_binds.append((mods, key))

    def clear_binds(self):
        if self.lua:
            self.eval("for _, b in ipairs(pantheon_binds or {}) do b:remove() end pantheon_binds = {}", "remove shortcuts")
        else:
            for mods, key in self._legacy_binds:
                self.request("keyword unbind %s,%s" % (" ".join(mods), key))
            self._legacy_binds = []
