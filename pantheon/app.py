import concurrent.futures
import mimetypes
import os
import sys
import threading
import time
import traceback

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gdk, Gio, GLib, Gtk, WebKit

from pantheon import jsonutil, paths, store
from pantheon.desktop import Desktop
from pantheon.errors import message

PAGE = "pantheon://app/index.html"
MODAL = {"importPlacementFrame", "developerExport", "developerSelect", "developerPickPoint", "placementPickPoint",
         "macroExport", "developerCapture", "capturePlacement", "alignPlacement", "developerTest", "testWebhook",
         "updateCheck", "dispatchWebhook"}


class Pantheon:
    def __init__(self, app):
        from pantheon import gtkhost
        from pantheon.platform import hypr
        self.app = app
        self.dirty = False
        self.recording = False
        self.closing = False
        self.last_press = None
        self.worker = concurrent.futures.ThreadPoolExecutor(1, "pantheon-host")
        self.modal = concurrent.futures.ThreadPoolExecutor(2, "pantheon-modal")
        self.window = Gtk.ApplicationWindow(application=app, title="Pantheon", decorated=False)
        self.window.set_default_size(1380, 900)
        self.window.set_size_request(1100, 780)
        self.window.connect("close-request", self.close_request)
        self.host = gtkhost.Host(self.window)
        self.viewer = gtkhost.Viewer(self.viewer_state)
        Desktop.clipboard = self.host.clipboard
        Desktop.open_file = self.host.open_file
        Desktop.save_file = self.host.save_file
        Desktop.confirm = self.host.confirm
        Desktop.open_uri = self.host.open_uri
        Desktop.pick = self.host.pick
        Desktop.viewer = self.viewer.set
        Desktop.report = lambda text: self.event_error(text)
        self.setup_modules()
        self.webview = self.create_webview()
        self.window.set_child(self.webview)
        self.window.present()
        self.hypr = hypr()
        from pantheon.hotkeys import Hotkeys
        self.hotkeys = Hotkeys(self.hypr, self.hotkey)
        self.controls = None
        threading.Thread(target=self.place_window, name="pantheon-place", daemon=True).start()
        threading.Thread(target=self.maintain, name="pantheon-mount", daemon=True).start()

    def place_window(self):
        from pantheon.mount import GameCapture, GameMount
        if os.environ.get("PANTHEON_TILED"):
            return
        for _ in range(80):
            host = GameMount.host()
            if host:
                break
            time.sleep(0.05)
        else:
            return
        try:
            monitor = GameCapture.monitor(host, None)
            busy = {w["id"] for w in self.hypr.query("workspaces") if w.get("hasfullscreen")}
            if host.get("workspace", {}).get("id") in busy:
                for m in self.hypr.monitors():
                    workspace = m.get("activeWorkspace") or {}
                    if workspace.get("id") not in busy:
                        self.hypr.to_workspace(host["address"], workspace.get("name") or str(workspace["id"]))
                        monitor = GameCapture.logical(m)
                        break
            width, height = min(1380, monitor["width"] - 40), min(900, monitor["height"] - 40)
            width, height = max(width, min(1100, monitor["width"])), max(height, min(780, monitor["height"]))
            if not host.get("floating"):
                self.hypr.float(host["address"], True)
            self.hypr.resize(host["address"], width, height)
            self.hypr.move(host["address"], monitor["x"] + (monitor["width"] - width) // 2, monitor["y"] + (monitor["height"] - height) // 2)
        except Exception as err:
            self.event_error("Could not position the Pantheon window: " + message(err))

    def setup_modules(self):
        from pantheon.engine import HubEngine
        from pantheon.hub import MacroHub
        from pantheon.mount import GameCapture
        from pantheon.packages import MacroPackages
        from pantheon.run_settings import RunSettings
        MacroPackages.developer = staticmethod(lambda: bool(MacroHub.config.get("developer", 0)))
        MacroPackages.busy = staticmethod(HubEngine.busy)
        MacroPackages.clipboard = staticmethod(lambda text: Desktop.clipboard(text))
        MacroPackages.save_dialog = staticmethod(lambda name, title, filters: Desktop.save_file(name, title, filters))
        MacroPackages.confirm = staticmethod(lambda text, title: Desktop.confirm(text, title))
        GameCapture.busy = staticmethod(HubEngine.busy)
        RunSettings.busy_state = staticmethod(HubEngine.state)
        HubEngine.log_hub = staticmethod(MacroHub.log)
        MacroHub.initialize()

    def create_webview(self):
        context = WebKit.WebContext.get_default()
        context.register_uri_scheme("pantheon", self.serve)
        context.get_security_manager().register_uri_scheme_as_secure("pantheon")
        manager = WebKit.UserContentManager()
        with open(os.path.join(paths.PACKAGE, "bridge.js"), "r", encoding="utf-8") as file:
            script = WebKit.UserScript.new(file.read(), WebKit.UserContentInjectedFrames.TOP_FRAME,
                                           WebKit.UserScriptInjectionTime.START, [PAGE + "*", "pantheon://app/*"], None)
        manager.add_script(script)
        manager.register_script_message_handler("pantheon", None)
        manager.connect("script-message-received::pantheon", self.received)
        webview = WebKit.WebView(web_context=context, user_content_manager=manager)
        settings = webview.get_settings()
        settings.set_enable_developer_extras(bool(os.environ.get("PANTHEON_INSPECTOR")))
        settings.set_javascript_can_open_windows_automatically(False)
        settings.set_enable_back_forward_navigation_gestures(False)
        webview.set_background_color(Gdk.RGBA(0x17 / 255, 0x17 / 255, 0x17 / 255, 1))
        webview.connect("decide-policy", self.policy)
        webview.connect("context-menu", lambda *_: not os.environ.get("PANTHEON_INSPECTOR"))
        webview.connect("create", lambda *_: None)
        press = Gtk.GestureClick(button=0)
        press.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        press.connect("pressed", self.pressed)
        webview.add_controller(press)
        webview.load_uri(PAGE)
        return webview

    def pressed(self, gesture, n, x, y):
        event = gesture.get_current_event()
        self.last_press = (gesture.get_current_button(), x, y, event.get_time() if event else Gdk.CURRENT_TIME, gesture.get_device())

    def serve(self, request):
        path = request.get_path() or "/index.html"
        root = os.path.realpath(paths.UI)
        target = os.path.realpath(os.path.join(root, path.lstrip("/")))
        if not request.get_uri().startswith("pantheon://app/") or not target.startswith(root + os.sep) or not os.path.isfile(target):
            request.finish_error(GLib.Error.new_literal(Gio.io_error_quark(), "Not found", Gio.IOErrorEnum.NOT_FOUND))
            return
        with open(target, "rb") as file:
            data = file.read()
        mime = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if target.endswith(".js"):
            mime = "text/javascript"
        stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data))
        response = WebKit.URISchemeResponse.new(stream, len(data))
        response.set_content_type(mime)
        response.set_http_headers(self.headers())
        request.finish_with_response(response)

    @staticmethod
    def headers():
        from gi.repository import Soup
        headers = Soup.MessageHeaders.new(Soup.MessageHeadersType.RESPONSE)
        headers.append("Cache-Control", "no-store")
        return headers

    def policy(self, webview, decision, kind):
        if kind == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_navigation_action().get_request().get_uri()
            if uri.split("#")[0] != PAGE:
                decision.ignore()
                return True
        elif kind == WebKit.PolicyDecisionType.NEW_WINDOW_ACTION:
            decision.ignore()
            return True
        return False

    def post(self, value):
        text = jsonutil.stringify(value)

        def run():
            self.webview.evaluate_javascript("window.__pantheonDeliver(" + text + ")", -1, None, None, None, None, None)
            return False
        GLib.idle_add(run)

    def event_error(self, text):
        self.post({"event": "error", "message": text})

    def received(self, manager, value):
        text = value.to_string() if hasattr(value, "to_string") else str(value)
        mid = ""
        try:
            if len(text) > 2000000:
                raise ValueError("Message is too large.")
            m = jsonutil.parse(text)
            if not isinstance(m, dict) or not isinstance(m.get("id"), str) or len(m["id"]) > 64:
                raise ValueError("Invalid message.")
            mid = m["id"]
            action = m.get("action")
            if action == "__drag":
                self.begin_move()
                return
            if action == "__maximize":
                self.toggle_maximize()
                return
            if action == "window":
                result = self.window_action(m.get("data"))
                self.post({"data": result, "id": mid, "ok": 1})
                return
            pool = self.modal if action in MODAL else self.worker
            pool.submit(self.handle, mid, action, m)
        except Exception as err:
            self.post({"error": message(err), "id": mid, "ok": 0})

    def handle(self, mid, action, m):
        try:
            result = self.dispatch(action, m)
            self.post({"data": result, "id": mid, "ok": 1})
        except Exception as err:
            if os.environ.get("PANTHEON_DEBUG"):
                traceback.print_exc()
            self.post({"error": message(err), "id": mid, "ok": 0})

    def dispatch(self, action, m):
        from pantheon.developer import DeveloperTools
        from pantheon.engine import HubEngine
        from pantheon.framework import base, play_controls, settings
        from pantheon.hub import HubControls, MacroHub
        from pantheon.mount import GameMount
        from pantheon.packages import MacroPackages
        from pantheon.placements import PlacementStore
        from pantheon.run_settings import RunSettings
        from pantheon.updates import PantheonUpdates
        data, mode = m.get("data"), m.get("mode")
        if action == "updateCheck":
            return PantheonUpdates.check()
        if action == "updateInstall":
            return PantheonUpdates.install()
        if action == "updateReleaseNotes":
            return PantheonUpdates.open_release_notes()
        if action == "snapshot":
            return MacroHub.snapshot()
        if action == "loadRunSettings":
            return RunSettings.load(mode)
        if action == "saveRunSettings":
            return RunSettings.save(mode, data)
        if action == "testWebhook":
            return RunSettings.test_webhook()
        if action == "dispatchWebhook":
            return RunSettings.dispatch(m.get("event", ""), m.get("details", ""), True)
        if action == "preferences":
            result = MacroHub.save_preferences(data)
            if not result["developer"]:
                DeveloperTools.stop()
            return result
        if action == "developerCoordinates":
            return DeveloperTools.coordinates(data)
        if action == "developerCapture":
            return DeveloperTools.capture()
        if action == "developerSelect":
            return DeveloperTools.capture(True)
        if action == "developerPickPoint":
            return DeveloperTools.pick_point()
        if action == "frameworkLoad":
            DeveloperTools.require()
            return MacroPackages.load(data)
        if action == "frameworkSave":
            base.keys(data, "package|definition|revision")
            return MacroPackages.save(data["package"], data["definition"], data["revision"])
        if action == "frameworkCatalog":
            DeveloperTools.require()
            return MacroPackages.catalog()
        if action == "frameworkNew":
            return MacroPackages.new()
        if action == "macroImportPreview":
            return MacroPackages.preview(data)
        if action == "macroInstall":
            return MacroPackages.install(data)
        if action == "macroExport":
            return MacroPackages.export_draft(data) if isinstance(data, dict) else MacroPackages.export(data)
        if action == "macroCatalogRefresh":
            return MacroPackages.catalog(True)
        if action == "macroSettingsLoad":
            definition = MacroPackages.load(data)["definition"]
            return {"specs": settings.specs(definition), "values": MacroPackages.values(data)}
        if action == "macroSettingsSave":
            return MacroPackages.save_values(mode, data)
        if action == "developerExport":
            return DeveloperTools.export(data)
        if action == "developerCopy":
            return DeveloperTools.copy(data)
        if action == "developerCopyPattern":
            return DeveloperTools.copy_pattern(data)
        if action == "developerTest":
            return DeveloperTools.test(data)
        if action == "joinDiscord":
            Desktop.open_uri("https://discord.gg/egqhwdXs6R")
            return {"opened": 1}
        if action in ("launch", "selectWorkspace"):
            return MacroHub.select_workspace(data)
        if action == "mountLayout":
            return GameMount.layout(data)
        if action == "mount":
            return GameMount.enable()
        if action == "detach":
            try:
                HubEngine.stop()
            finally:
                result = GameMount.release()
            return result
        if action == "startEngine":
            try:
                return self.start_engine(data)
            except Exception:
                HubEngine.stop()
                raise
        if action == "pauseEngine":
            return HubEngine.pause()
        if action == "stopEngine":
            return HubEngine.stop()
        if action == "focusRoblox":
            return MacroHub.focus_roblox()
        if action == "placementPickPoint":
            MacroHub.mode(mode)
            return DeveloperTools.pick_point(False)
        if action == "loadPlacements":
            return PlacementStore.load(mode)
        if action == "savePlacements":
            return PlacementStore.save(mode, data)
        if action == "placementFrame":
            return PlacementStore.frame(mode, data)
        if action == "alignPlacement":
            return PlacementStore.align(mode)
        if action == "capturePlacement":
            return PlacementStore.capture(mode, data)
        if action == "importPlacementFrame":
            return PlacementStore.import_frame(mode, data)
        if action == "playControlsLoad":
            return play_controls.load()
        if action == "playControlsSave":
            if HubEngine.busy():
                raise RuntimeError("Stop the macro before changing in-game controls.")
            return play_controls.save(data)
        if action == "applyControls":
            result = HubControls.apply(data)
            self.controls = None
            return result
        if action == "recordingKey":
            self.recording = bool(store.integer(data, 0, 1, "Key recording"))
            return {"updated": 1}
        if action == "dirty":
            self.dirty = bool(store.integer(data, 0, 1, "Draft state"))
            return {"updated": 1}
        raise ValueError("Unknown hub action.")

    def start_engine(self, ident):
        from pantheon.engine import HubEngine
        from pantheon.hub import MacroHub
        from pantheon.packages import MacroPackages
        from pantheon.placements import PlacementStore
        ident = MacroHub.mode(ident)
        return HubEngine.start(ident, MacroPackages.load(ident), MacroPackages.values(ident), PlacementStore.load(ident)["profile"])

    def surface(self):
        native = self.window.get_native()
        return native.get_surface() if native else None

    def begin_move(self):
        surface, press = self.surface(), self.last_press
        if surface and press:
            button, x, y, stamp, device = press
            surface.begin_move(device, button or 1, x, y, stamp)

    def toggle_maximize(self):
        if self.window.is_maximized():
            self.window.unmaximize()
        else:
            self.window.maximize()

    def window_action(self, action):
        if action == "minimize":
            self.window.minimize()
        elif action == "maximize":
            self.toggle_maximize()
        elif action == "resize":
            surface, press = self.surface(), self.last_press
            if surface and press:
                button, x, y, stamp, device = press
                surface.begin_resize(Gdk.SurfaceEdge.SOUTH_EAST, device, button or 1, x, y, stamp)
        elif action == "close":
            GLib.idle_add(lambda: (self.window.close(), False)[1])
        else:
            raise ValueError("Unknown window action.")
        return {"updated": 1}

    def close_request(self, window):
        if self.closing:
            return False
        if self.dirty:
            def ask():
                dialog = Gtk.AlertDialog(message="Pantheon", detail="Close without saving your changes?", modal=True)
                dialog.set_buttons(["No", "Yes"])
                dialog.set_cancel_button(0)

                def done(d, result):
                    try:
                        if d.choose_finish(result) == 1:
                            self.shutdown()
                    except GLib.Error:
                        pass
                dialog.choose(self.window, None, done)
            ask()
            return True
        self.shutdown()
        return True

    def shutdown(self):
        self.closing = True
        try:
            self.cleanup()
        finally:
            self.window.destroy()
            self.app.quit()

    def cleanup(self):
        from pantheon.developer import DeveloperTools
        from pantheon.engine import HubEngine
        from pantheon.mount import GameCapture, GameMount
        from pantheon.platform.uinput import device
        for step in (DeveloperTools.stop, HubEngine.stop, lambda: GameCapture.restore_active(True), GameMount.release,
                     self.hotkeys.close, device().close):
            try:
                step()
            except Exception:
                pass

    def viewer_state(self, enabled):
        self.hotkeys.viewer = enabled
        self.controls = None

    def hotkey(self, action):
        if action == "copy":
            self.host.clipboard(self.viewer.text)
            return
        self.worker.submit(self.run_hotkey, action)

    def run_hotkey(self, action):
        from pantheon.engine import HubEngine
        from pantheon.hub import MacroHub
        from pantheon.mount import GameMount
        try:
            if action == "setup":
                GameMount.enable()
                GameMount.focus()
            elif action == "toggle":
                if HubEngine.state() in ("running", "paused"):
                    HubEngine.stop()
                    return
                if self.dirty:
                    raise RuntimeError("Save your changes before starting with a shortcut.")
                self.start_engine(MacroHub.config["selected"])
            elif action == "stop":
                HubEngine.stop()
            elif action == "pause":
                HubEngine.pause()
        except Exception as err:
            if action == "toggle":
                HubEngine.stop()
            self.event_error(message(err))

    def maintain(self):
        from pantheon.hub import HubControls
        from pantheon.mount import GameMount
        failures = 0
        while not self.closing:
            try:
                GameMount.refresh()
                failures = 0
            except Exception as err:
                failures += 1
                try:
                    GameMount.release()
                except Exception:
                    pass
                self.event_error(message(err))
                if failures > 3:
                    time.sleep(2)
            try:
                if self.controls is None:
                    self.controls = HubControls.read()
                host = GameMount.host_address
                active = self.hypr.active() if host else ""
                enabled = (not self.recording and not GameMount.capturing and bool(GameMount.rect["visible"])
                           and active != "" and active in (host, GameMount.address))
                self.hotkeys.update(enabled, self.controls)
            except Exception:
                pass
            time.sleep(0.15)


def main(argv):
    if len(argv) > 1 and argv[1] == "--check":
        import pantheon.framework.runner
        import pantheon.placements
        import pantheon.developer
        import pantheon.updates
        print("Pantheon and dependencies parsed successfully.")
        return 0
    GLib.set_prgname(paths.APP_ID)
    GLib.set_application_name("Pantheon")
    app = Gtk.Application(application_id=paths.APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
    holder = {}

    def activate(application):
        if "main" in holder:
            holder["main"].window.present()
            return
        try:
            holder["main"] = Pantheon(application)
        except Exception as err:
            traceback.print_exc()
            dialog = Gtk.AlertDialog(message="Pantheon could not open.", detail=message(err))
            window = Gtk.ApplicationWindow(application=application, title="Pantheon")
            window.present()
            dialog.choose(window, None, lambda *_: application.quit())

    app.connect("activate", activate)
    return app.run([argv[0]])
