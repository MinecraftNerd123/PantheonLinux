import collections
import os
import threading
import time
import uuid

from pantheon import jsonutil, paths
from pantheon.errors import FlowStop, GameClosed, message
from pantheon.framework import placement_plan, play_controls, schema
from pantheon.framework.environment import RobloxEnvironment
from pantheon.framework.runner import FlowRunner
from pantheon.mount import GameMount
from pantheon.platform import hypr
from pantheon.platform.uinput import device
from pantheon.recorder import Recorder

RELEASE_KEYS = ["W", "A", "S", "D", "Space", "Shift", "Control", "LButton", "RButton"]
MAX_FAILURES = 5


class HubEngine:
    state_value = "stopped"
    thread = None
    runner = None
    environment = None
    recorder = None
    mode = ""
    folder = ""
    started_at = 0.0
    elapsed = 0
    wins = losses = 0
    counters = {}
    logs = collections.deque(maxlen=200)
    paused = threading.Event()
    cancelled = threading.Event()
    lock = threading.RLock()
    log_hub = staticmethod(lambda text: None)

    @classmethod
    def state(cls):
        if cls.thread is None:
            return "stopped"
        return cls.state_value

    @classmethod
    def busy(cls):
        return cls.state() not in ("stopped", "ready", "error")

    @classmethod
    def log(cls, text):
        line = time.strftime("%H:%M:%S") + "  " + text
        cls.logs.append(line)
        if cls.recorder:
            cls.recorder.log(line)
        if cls.folder:
            try:
                with open(os.path.join(cls.folder, "log.txt"), "a", encoding="utf-8") as file:
                    file.write(line + "\n")
            except OSError:
                pass

    @classmethod
    def start(cls, ident, load, values, placements):
        with cls.lock:
            if not GameMount.address:
                GameMount.enable()
            if not GameMount.rect["visible"]:
                raise RuntimeError("Open the macro dashboard before starting.")
            if cls.state() in ("running", "paused"):
                raise RuntimeError("Stop the current run before starting another.")
            cls.stop()
            if not GameMount.address:
                raise RuntimeError("Open Roblox in Sober before starting.")
            token = uuid.uuid4().hex
            cls.folder = paths.data("sessions", token)
            os.makedirs(cls.folder, exist_ok=True)
            cls.mode = ident
            definition = load["definition"]
            controls = play_controls.resolve(definition, values, play_controls.load())
            for name, value in (("framework.json", definition), ("settings-values.json", values),
                                ("placements.json", placements), ("play-controls.json", controls)):
                jsonutil.write(os.path.join(cls.folder, name), value)
            definition = schema.validate(jsonutil.parse(jsonutil.stringify(definition)))
            if "main" not in definition["workflows"] and "entry" not in definition:
                raise RuntimeError("No validated macro configuration is available.")
            device().open()
            cls.logs.clear()
            cls.wins = cls.losses = 0
            cls.counters = {}
            cls.paused.clear()
            cls.cancelled.clear()
            cls.state_value = "starting"
            args = (definition, jsonutil.parse(jsonutil.stringify(values)), placements, controls, GameMount.address)
            cls.thread = threading.Thread(target=cls._run, args=args, name="pantheon-engine", daemon=True)
            GameMount.focus()
            deadline = time.monotonic() + 2
            while hypr().active() != GameMount.address:
                if time.monotonic() > deadline:
                    cls.state_value = "stopped"
                    cls.thread = None
                    raise RuntimeError("Could not focus Sober. Close any open dialogs and try again.")
                time.sleep(0.05)
            cls.thread.start()
            cls.started_at, cls.elapsed = time.monotonic(), 0
            cls.log_hub(ident + " started.")
            return {"state": "running"}

    @classmethod
    def _gate(cls):
        while cls.paused.is_set() and not cls.cancelled.is_set():
            time.sleep(0.05)
        if cls.cancelled.is_set():
            raise FlowStop("Workflow stopped.")

    @classmethod
    def _result(cls, won):
        if won:
            cls.wins += 1
        else:
            cls.losses += 1
        cls.log("Victory detected." if won else "Defeat detected.")

    @classmethod
    def _tally(cls, name, value):
        cls.counters[name] = cls.counters.get(name, 0) + value
        cls.log("%s +%d (total %d)." % (name, value, cls.counters[name]))

    @classmethod
    def _workflow(cls, definition, values, placements, controls, address, ident):
        environment = RobloxEnvironment(hypr(), address, cls.log, cls._result, cls._gate)
        environment.tally_callback = cls._tally
        runner = FlowRunner(definition, environment, values)
        if placements:
            runner.placement_data = placement_plan.validate(placements)
        runner.play_keys = play_controls.validate(controls)
        cls.environment, cls.runner = environment, runner
        try:
            runner.run(ident)
        finally:
            cls.runner = None

    @classmethod
    def _origin(cls):
        environment = cls.environment
        return (environment.left, environment.top) if environment and environment.left else None

    @classmethod
    def _attempt(cls, definition, values, placements, controls, address, repeat, failures):
        cls.recorder = Recorder(definition["name"], cls._origin)
        try:
            cls._workflow(definition, values, placements, controls, address, definition["entry"])
            cls.recorder.finish("completed")
            return 0
        except FlowStop:
            cls.recorder.finish("stopped")
            raise
        except GameClosed as err:
            cls.recorder.finish("error: " + message(err))
            raise
        except Exception as err:
            cls.recorder.snapshot("error")
            failures += 1
            if not repeat or failures >= MAX_FAILURES:
                cls.recorder.finish("error: " + message(err))
                raise
            cls.log("Error: " + message(err))
            cls.log("Recovering (%d of %d failures in a row)." % (failures, MAX_FAILURES))
            for _ in range(60):
                cls._gate()
                time.sleep(0.05)
            if "recover" in definition["workflows"]:
                try:
                    cls._workflow(definition, values, placements, controls, address, "recover")
                except (FlowStop, GameClosed):
                    raise
                except Exception as again:
                    cls.log("Recovery failed: " + message(again))
            cls.recorder.finish("error: " + message(err) + " (recovered)")
            return failures
        finally:
            cls.recorder.finish("stopped")
            cls.recorder = None

    @classmethod
    def _run(cls, definition, values, placements, controls, address):
        cls.state_value = "running"
        failed = False
        try:
            cls.log("Running data macro: " + definition["name"])
            repeat, failures = definition.get("runMode", "once") == "repeat", 0
            while True:
                failures = cls._attempt(definition, values, placements, controls, address, repeat, failures)
                if not repeat:
                    break
                for _ in range(5):
                    cls._gate()
                    time.sleep(0.05)
            cls.log("Main sequence completed.")
        except FlowStop as err:
            cls.log(str(err))
        except Exception as err:
            failed = True
            cls.log("Error: " + message(err))
            cls.state_value = "error"
        finally:
            if cls.environment:
                cls.environment.release()
            if not failed:
                cls.state_value = "ready"

    @classmethod
    def pause(cls):
        with cls.lock:
            state = cls.state()
            if state not in ("running", "paused"):
                raise RuntimeError("No macro is running.")
            if state == "paused":
                if not GameMount.address:
                    raise RuntimeError("The mounted Roblox window is unavailable.")
                GameMount.focus()
                if cls.environment:
                    cls.environment.resume()
                cls.state_value = "running"
                cls.paused.clear()
                return {"state": "running"}
            cls.paused.set()
            if cls.environment:
                cls.environment.suspend()
            cls.state_value = "paused"
            return {"state": "paused"}

    @classmethod
    def stop(cls):
        with cls.lock:
            if cls.started_at:
                cls.elapsed = int(time.monotonic() - cls.started_at)
                cls.started_at = 0
            thread = cls.thread
            if thread is not None and thread.is_alive():
                cls.cancelled.set()
                cls.paused.clear()
                if cls.runner:
                    cls.runner.cancel()
                thread.join(2)
            if cls.environment:
                cls.environment.release()
            cls.thread = None
            cls.environment = None
            cls.state_value = "stopped"
            if GameMount.address:
                for key in RELEASE_KEYS:
                    try:
                        device().key(key, False)
                    except Exception:
                        break
            return {"state": "stopped"}

    @classmethod
    def snapshot(cls):
        if cls.started_at and not cls.busy():
            cls.elapsed = int(time.monotonic() - cls.started_at)
            cls.started_at = 0
        active = 1 if cls.busy() else 0
        seconds = int(time.monotonic() - cls.started_at) if cls.started_at and active else cls.elapsed
        return {"active": active, "logs": list(cls.logs)[-20:], "losses": cls.losses, "counters": dict(cls.counters), "mode": cls.mode, "seconds": seconds,
                "state": cls.state(), "wins": cls.wins}
