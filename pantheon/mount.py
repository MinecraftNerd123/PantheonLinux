import threading
import time

from pantheon import findtext, paths
from pantheon.framework import base
from pantheon.platform import capture, hypr
from pantheon import store

HIDE_WORKSPACE = "special:pantheon"


def _workspace(client):
    ws = client.get("workspace") or {}
    return ws.get("name") or str(ws.get("id", ""))


class GameMount:
    lock = threading.RLock()
    address = ""
    original = None
    rect = {"height": 600, "visible": 0, "width": 800, "x": 0, "y": 0}
    enabled = False
    hidden = False
    capturing = False
    host_address = ""
    host_title = "Pantheon"

    @classmethod
    def host(cls):
        h = hypr()
        if cls.host_address:
            c = h.client(cls.host_address)
            if c:
                return c
        c = h.find(paths.APP_ID, cls.host_title)
        cls.host_address = c["address"] if c else ""
        return c

    @classmethod
    def game(cls):
        return hypr().find(paths.GAME_CLASS)

    @classmethod
    def layout(cls, rect):
        for name in ("x", "y", "width", "height"):
            if not base.is_int(rect.get(name)) or abs(rect[name]) > 16000:
                raise ValueError("Invalid game panel bounds.")
        store.integer(rect.get("visible"), 0, 1, "Game panel visibility")
        with cls.lock:
            cls.rect = {k: rect[k] for k in ("height", "visible", "width", "x", "y")}
            cls.refresh()
            return {"mounted": 1 if cls.address and not cls.hidden else 0}

    @classmethod
    def refresh(cls):
        with cls.lock:
            if cls.capturing:
                return
            h = hypr()
            game = h.client(cls.address) if cls.address else None
            if cls.address and not game:
                cls.address, cls.original = "", None
            if not cls.enabled:
                return
            if not cls.address:
                found = cls.game()
                if not found:
                    return
                cls.attach(found)
                game = h.client(cls.address)
                if not game:
                    return
            host = cls.host()
            if not host:
                return
            active = h.active()
            exposed = active in (host["address"], cls.address)
            r = cls.rect
            hw, hh = host["size"]
            visible = bool(r["visible"]) and exposed and r["x"] >= 0 and r["y"] >= 48 and r["x"] + 800 <= hw and r["y"] + 600 <= hh
            if not visible:
                if not exposed:
                    if cls.hidden:
                        h.to_workspace(cls.address, _workspace(host))
                    cls.hidden = False
                elif not cls.hidden:
                    h.to_workspace(cls.address, HIDE_WORKSPACE)
                    cls.hidden = True
                return
            if cls.hidden or _workspace(game) != _workspace(host):
                h.to_workspace(cls.address, _workspace(host))
            if not game.get("floating"):
                h.float(cls.address, True)
            if list(game["size"]) != [800, 600]:
                h.resize(cls.address, 800, 600)
            target = [host["at"][0] + r["x"], host["at"][1] + r["y"]]
            if list(game["at"]) != target:
                h.move(cls.address, target[0], target[1])
            if host.get("floating") and active == host["address"]:
                h.raise_window(cls.address)
            cls.hidden = False

    @classmethod
    def enable(cls):
        with cls.lock:
            cls.enabled = True
            cls.refresh()
            return {"mounted": 1 if cls.address and not cls.hidden else 0}

    @classmethod
    def snapshot(cls, client):
        return {"at": list(client["at"]), "floating": 1 if client.get("floating") else 0, "fullscreen": client.get("fullscreen", 0),
                "fullscreenClient": client.get("fullscreenClient", 0), "size": list(client["size"]), "workspace": _workspace(client)}

    @classmethod
    def attach(cls, client):
        with cls.lock:
            if cls.address == client["address"]:
                return
            if cls.address:
                cls.detach()
            h = hypr()
            cls.original = cls.snapshot(client)
            cls.address = client["address"]
            try:
                if client.get("fullscreen", 0):
                    h.fullscreen_state(cls.address, 0, 0)
                if not client.get("floating"):
                    h.float(cls.address, True)
                h.resize(cls.address, 800, 600)
                cls.enabled = True
            except Exception as err:
                cls.detach()
                raise RuntimeError("Roblox could not be pinned. " + str(err)) from None

    @classmethod
    def restore(cls, address, original):
        h = hypr()
        current = h.client(address)
        if not current or not original:
            return
        if _workspace(current) != original["workspace"] and original["workspace"]:
            h.to_workspace(address, original["workspace"])
        if original["floating"]:
            if not current.get("floating"):
                h.float(address, True)
            h.resize(address, original["size"][0], original["size"][1])
            h.move(address, original["at"][0], original["at"][1])
        elif current.get("floating"):
            h.float(address, False)
        if original["fullscreen"]:
            h.fullscreen_state(address, original["fullscreen"], original["fullscreenClient"])

    @classmethod
    def focus(cls):
        with cls.lock:
            if not cls.address:
                raise RuntimeError("Open Roblox first.")
            h = hypr()
            if cls.hidden:
                host = cls.host()
                if host:
                    h.to_workspace(cls.address, _workspace(host))
            h.focus(cls.address)
            cls.hidden = False

    @classmethod
    def detach(cls):
        with cls.lock:
            address, original = cls.address, cls.original
            try:
                if address and original:
                    cls.restore(address, original)
            finally:
                cls.address, cls.original, cls.hidden = "", None, False

    @classmethod
    def release(cls):
        with cls.lock:
            cls.enabled = False
            cls.detach()
            return {"mounted": 0}


class GameCapture:
    active = None
    busy = staticmethod(lambda: False)

    @classmethod
    def frame(cls, probe=None, prepare=None):
        with GameMount.lock:
            if GameMount.capturing:
                raise RuntimeError("A Roblox capture is already in progress.")
            if cls.busy():
                raise RuntimeError("Stop the macro before capturing Roblox.")
            h = hypr()
            client = h.client(GameMount.address) if GameMount.address else None
            client = client or GameMount.game()
            if not client:
                raise RuntimeError("Open Roblox before capturing a screenshot. Pinning is optional.")
            address = client["address"]
            previous = h.active()
            GameMount.capturing = True
            cls.active = {"address": address, "original": GameMount.snapshot(client)}
        try:
            host = GameMount.host()
            if client.get("fullscreen", 0):
                h.fullscreen_state(address, 0, 0)
            workspace = _workspace(host) if host else None
            if workspace and _workspace(client) != workspace:
                h.to_workspace(address, workspace)
            if not client.get("floating"):
                h.float(address, True)
            monitor = cls.monitor(client, host)
            h.resize(address, 800, 600)
            if monitor["width"] < 800 or monitor["height"] < 600:
                raise RuntimeError("Roblox needs room for an 800 x 600 client area. Increase the display resolution or lower the monitor scale.")
            h.move(address, monitor["x"] + (monitor["width"] - 800) // 2, monitor["y"] + (monitor["height"] - 600) // 2)
            h.focus(address)
            deadline = time.monotonic() + 2
            while h.active() != address:
                if time.monotonic() > deadline:
                    raise RuntimeError("Could not bring Roblox forward. Close any open game dialogs and try again.")
                time.sleep(0.05)
            time.sleep(0.5)
            current = h.client(address)
            for _ in range(3):
                if current and list(current["size"]) == [800, 600]:
                    break
                h.resize(address, 800, 600)
                time.sleep(0.18)
                current = h.client(address)
            if not current or list(current["size"]) != [800, 600]:
                size = current["size"] if current else [0, 0]
                raise RuntimeError("Roblox client is %d x %d; capture requires 800 x 600. Leave fullscreen and try again." % tuple(size))
            if prepare:
                prepare(address)
                current = h.client(address) or current
            time.sleep(0.05)
            frame = capture.grab(current["at"][0], current["at"][1], 800, 600)
            if findtext.dark(frame):
                raise RuntimeError("Roblox returned a black frame. Wait until the game is visible and capture again.")
            if probe:
                probe(address, current, frame)
            return frame
        finally:
            try:
                cls.restore_active()
                if previous and previous != address and h.client(previous):
                    h.focus(previous)
            finally:
                with GameMount.lock:
                    GameMount.capturing = False
                try:
                    GameMount.refresh()
                except Exception:
                    pass

    @classmethod
    def monitor(cls, client, host):
        monitors = hypr().monitors()
        wanted = client.get("monitor", -1)
        if host and host.get("monitor", -1) >= 0:
            wanted = host["monitor"]
        for m in monitors:
            if m.get("id") == wanted:
                return cls.logical(m)
        return cls.logical(monitors[0])

    @staticmethod
    def logical(m):
        scale = m.get("scale", 1) or 1
        width, height = m["width"], m["height"]
        if m.get("transform", 0) % 2:
            width, height = height, width
        return {"x": m["x"], "y": m["y"], "width": int(width / scale), "height": int(height / scale)}

    @classmethod
    def restore_active(cls, closing=False):
        r, cls.active = cls.active, None
        if not r:
            return
        if not closing and GameMount.enabled and GameMount.address == r["address"]:
            return
        GameMount.restore(r["address"], r["original"])
