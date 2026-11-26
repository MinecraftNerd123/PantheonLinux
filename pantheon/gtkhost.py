import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from pantheon.platform import capture, hypr
from pantheon.platform.hyprland import _lua

PICKER_TITLE = "Pantheon capture"
VIEWER_TITLE = "Pantheon coordinates"
_rules_ready = False


def on_main(fn, *args):
    if threading.current_thread() is threading.main_thread():
        return fn(*args)
    done, box = threading.Event(), {}

    def run():
        try:
            box["value"] = fn(*args)
        except Exception as err:
            box["error"] = err
        done.set()
        return False

    GLib.idle_add(run)
    done.wait()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def wait_main(start, timeout=None):
    done, box = threading.Event(), {}

    def finish(value=None, error=None):
        box["value"], box["error"] = value, error
        done.set()

    GLib.idle_add(lambda: (start(finish), False)[1])
    if not done.wait(timeout):
        raise RuntimeError("The dialog timed out.")
    if box.get("error"):
        raise box["error"]
    return box.get("value")


def ensure_rules():
    global _rules_ready
    if _rules_ready:
        return
    h = hypr()
    try:
        if h.lua:
            for title, focus in ((PICKER_TITLE, False), (VIEWER_TITLE, True)):
                spec = "match={title=%s}, float=true, pin=true, no_anim=true, border_size=0, rounding=0, no_shadow=true" % _lua("^(" + title + ")$")
                if focus:
                    spec += ", no_initial_focus=true"
                h.eval("hl.window_rule({%s})" % spec, "add window rules")
        else:
            for title, focus in ((PICKER_TITLE, False), (VIEWER_TITLE, True)):
                rules = ["float", "pin", "noanim", "noborder", "rounding 0", "noshadow"] + (["noinitialfocus"] if focus else [])
                for rule in rules:
                    h.request("keyword windowrulev2 %s,title:^(%s)$" % (rule, title))
    except Exception:
        pass
    _rules_ready = True


class Host:
    def __init__(self, window):
        self.window = window

    def clipboard(self, text):
        def run():
            provider = Gdk.ContentProvider.new_for_bytes("text/plain;charset=utf-8", GLib.Bytes.new(text.encode("utf-8")))
            self.window.get_clipboard().set_content(provider)
        on_main(run)

    def _filters(self, filters):
        store = Gio.ListStore.new(Gtk.FileFilter)
        for name, patterns in filters:
            f = Gtk.FileFilter()
            f.set_name(name)
            for p in patterns:
                f.add_pattern(p)
            store.append(f)
        return store

    def open_file(self, title, filters):
        def start(finish):
            dialog = Gtk.FileDialog(title=title, modal=True)
            dialog.set_filters(self._filters(filters))

            def done(d, result):
                try:
                    file = d.open_finish(result)
                    finish(file.get_path() if file else "")
                except GLib.Error:
                    finish("")
            dialog.open(self.window, None, done)
        return wait_main(start, 300)

    def save_file(self, name, title, filters):
        def start(finish):
            dialog = Gtk.FileDialog(title=title, modal=True, initial_name=name)
            dialog.set_filters(self._filters(filters))

            def done(d, result):
                try:
                    file = d.save_finish(result)
                    finish(file.get_path() if file else "")
                except GLib.Error:
                    finish("")
            dialog.save(self.window, None, done)
        return wait_main(start, 300)

    def confirm(self, text, title):
        def start(finish):
            dialog = Gtk.AlertDialog(message=title, detail=text, modal=True)
            dialog.set_buttons(["No", "Yes"])
            dialog.set_cancel_button(0)
            dialog.set_default_button(0)

            def done(d, result):
                try:
                    finish(d.choose_finish(result) == 1)
                except GLib.Error:
                    finish(False)
            dialog.choose(self.window, None, done)
        if threading.current_thread() is threading.main_thread():
            raise RuntimeError("Confirmation must not block the interface thread.")
        return wait_main(start, 300)

    def open_uri(self, uri):
        on_main(lambda: Gtk.UriLauncher.new(uri).launch(self.window, None, None))

    def pick(self, client, frame, point):
        ensure_rules()
        done, box = threading.Event(), {}
        on_main(lambda: Picker(client, frame, point, lambda result: (box.__setitem__("value", result), done.set())))
        deadline = time.monotonic() + 90
        while not done.wait(0.25):
            if time.monotonic() > deadline or not hypr().client(client["address"]):
                on_main(lambda: Picker.current and Picker.current.finish(None))
                done.wait(2)
                break
        return box.get("value")


def _place(title, x, y, width=None, height=None):
    h = hypr()
    for _ in range(40):
        c = next((item for item in h.clients() if item.get("title") == title), None)
        if c:
            if not c.get("floating"):
                h.float(c["address"], True)
            if width:
                h.resize(c["address"], width, height)
            h.move(c["address"], x, y)
            return c["address"]
        time.sleep(0.025)
    return ""


class Picker:
    current = None

    def __init__(self, client, frame, point, callback):
        Picker.current = self
        self.point, self.callback, self.client = point, callback, client
        self.start = self.end = None
        self.finished = False
        self.window = Gtk.Window(title=PICKER_TITLE, decorated=False, resizable=False)
        self.window.set_default_size(800, 600)
        texture = Gdk.MemoryTexture.new(frame.width, frame.height, Gdk.MemoryFormat.R8G8B8, GLib.Bytes.new(frame.data), frame.width * 3)
        overlay = Gtk.Overlay()
        picture = Gtk.Picture.new_for_paintable(texture)
        picture.set_can_shrink(False)
        picture.set_size_request(800, 600)
        overlay.set_child(picture)
        self.area = Gtk.DrawingArea()
        self.area.set_draw_func(self.draw)
        overlay.add_overlay(self.area)
        self.hud = Gtk.Label(label="SELECT COORDINATES   ·   Left click selects   ·   Escape cancels" if point else
                             "CAPTURE IMAGE   ·   Drag a rectangle around the image   ·   Escape cancels")
        self.hud.add_css_class("pantheon-hud")
        self.hud.set_valign(Gtk.Align.START)
        self.hud.set_halign(Gtk.Align.FILL)
        self.hud.set_can_target(False)
        overlay.add_overlay(self.hud)
        self.window.set_child(overlay)
        css = Gtk.CssProvider()
        css.load_from_data(b".pantheon-hud{background:rgba(41,36,63,0.92);color:#fff;font-size:15px;padding:12px 14px;}", -1)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.area.set_cursor(Gdk.Cursor.new_from_name("crosshair" if point else "cell"))
        click = Gtk.GestureClick(button=1)
        click.connect("pressed", self.pressed)
        click.connect("released", self.released)
        self.area.add_controller(click)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self.motion)
        self.area.add_controller(motion)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.key)
        self.window.add_controller(keys)
        self.window.connect("close-request", lambda *_: (self.finish(None), True)[1])
        self.window.present()
        x, y = client["at"]
        threading.Thread(target=self._position, args=(x, y), daemon=True).start()

    def _position(self, x, y):
        address = _place(PICKER_TITLE, x, y, 800, 600)
        if address:
            try:
                hypr().focus(address)
            except Exception:
                pass

    @staticmethod
    def clamp(x, y):
        return max(0, min(799, int(x))), max(0, min(599, int(y)))

    def label(self, text):
        self.hud.set_label(text)

    def motion(self, controller, x, y):
        px, py = self.clamp(x, y)
        self.hud.set_valign(Gtk.Align.END if py < 80 else Gtk.Align.START)
        if self.point:
            self.label("X: %d   Y: %d   ·   Left click selects   ·   Escape cancels" % (px, py))
        elif self.start:
            self.end = (px, py)
            r = self.rect()
            self.label("%d, %d · %d x %d · Escape cancels" % (r["x"], r["y"], r["width"], r["height"]))
            self.area.queue_draw()

    def pressed(self, gesture, n, x, y):
        if self.point:
            px, py = self.clamp(x, y)
            self.finish({"x": px, "y": py})
            return
        self.start = self.end = self.clamp(x, y)
        self.area.queue_draw()

    def released(self, gesture, n, x, y):
        if self.point or not self.start:
            return
        self.end = self.clamp(x, y)
        self.finish(self.rect())

    def rect(self):
        (ax, ay), (bx, by) = self.start, self.end
        return {"height": abs(ay - by) + 1, "width": abs(ax - bx) + 1, "x": min(ax, bx), "y": min(ay, by)}

    def draw(self, area, cr, width, height):
        if self.point or not self.start or not self.end:
            return
        r = self.rect()
        cr.set_source_rgba(0x91 / 255, 0x89 / 255, 0xfa / 255, 0.35)
        cr.rectangle(r["x"], r["y"], r["width"], r["height"])
        cr.fill_preserve()
        cr.set_source_rgba(0x91 / 255, 0x89 / 255, 0xfa / 255, 1)
        cr.set_line_width(1)
        cr.stroke()

    def key(self, controller, keyval, keycode, state):
        if keyval == Gdk.KEY_Escape:
            self.finish(None)
            return True
        return False

    def finish(self, result):
        if self.finished:
            return
        self.finished = True
        Picker.current = None
        self.window.destroy()
        self.callback(result)


class Viewer:
    def __init__(self, copy_state):
        self.window = None
        self.running = False
        self.text = ""
        self.copy_state = copy_state

    def set(self, enabled):
        if enabled and not self.running:
            ensure_rules()
            self.running = True
            on_main(self._open)
            threading.Thread(target=self._loop, name="pantheon-viewer", daemon=True).start()
        elif not enabled and self.running:
            self.running = False
            on_main(self._close)
        self.copy_state(self.running)

    def _open(self):
        self.window = Gtk.Window(title=VIEWER_TITLE, decorated=False, resizable=False)
        self.window.set_default_size(280, 96)
        self.label = Gtk.Label(label="")
        self.label.add_css_class("pantheon-viewer")
        self.label.set_xalign(0)
        self.window.set_child(self.label)
        self.window.set_can_target(False)
        css = Gtk.CssProvider()
        css.load_from_data(b".pantheon-viewer{background:rgba(23,23,23,0.94);color:#f4f4f5;font:14px monospace;padding:10px 12px;}", -1)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window.present()

    def _close(self):
        if self.window:
            self.window.destroy()
            self.window = None

    def _loop(self):
        from pantheon.mount import GameMount
        from pantheon import paths
        h = hypr()
        address, last = "", None
        while self.running:
            try:
                if GameMount.capturing:
                    time.sleep(0.08)
                    continue
                if not address:
                    address = _place(VIEWER_TITLE, 0, 0)
                x, y = h.cursor()
                text = "Screen: %d, %d" % (x, y)
                game = GameMount.game()
                if game and not game.get("hidden"):
                    gx, gy = game["at"]
                    w, ht = game["size"]
                    text += "\nRoblox client: %d, %d  (%d x %d)" % (x - gx, y - gy, w, ht)
                elif game:
                    text += "\nRoblox client: hidden"
                try:
                    pixel = capture.grab(x, y, 1, 1).pixel(0, 0)
                    text += "\nRGB: 0x%06X" % pixel
                except Exception:
                    pass
                self.text = text
                GLib.idle_add(lambda t=text + "\nCtrl+Shift+C: copy": self.window and self.label.set_label(t))
                if address and (x, y) != last:
                    h.move(address, x + 20, y + 24)
                    last = (x, y)
            except Exception:
                pass
            time.sleep(0.08)
