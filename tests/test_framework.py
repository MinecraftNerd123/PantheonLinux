import copy
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pantheon import findtext, jsonutil
from pantheon.errors import FlowImageError, FlowStop
from pantheon.framework import placement_plan, schema
from pantheon.framework.runner import FlowRunner
from pantheon.framework.schema import ALPHABET
from pantheon.image import Frame

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def image_condition(target):
    return {"checks": [{"state": "present", "target": target}], "operator": "all"}


class FixtureEnvironment:
    def __init__(self):
        self.clicks, self.held, self.visible, self.checks = [], {}, False, 0
        self.fail_after = self.cancel_after = 0
        self.runner, self.released = None, False
        self.moves, self.scrolls, self.found_after, self.max_held = [], [], {}, 0
        self.detect_after_scroll, self.real_time, self.waits, self.key_downs = False, False, 0, {}
        self.results, self.tallies = [], []

    def check(self):
        self.checks += 1
        if self.fail_after and self.checks >= self.fail_after:
            raise RuntimeError("Focus lost.")
        if self.cancel_after and self.checks >= self.cancel_after:
            self.runner.cancel()

    def find(self, target):
        name = target["name"]
        visible = self.visible or (name in self.found_after and len(self.clicks) >= self.found_after[name]) or (self.detect_after_scroll and len(self.scrolls) >= 2)
        if target["kind"] == "point":
            return {"x": target["x"], "y": target["y"]}
        return {"x": 100, "y": 100} if visible else 0

    def click(self, x, y, button="Left"):
        self.clicks.append([x, y, button])

    def move(self, x, y):
        self.moves.append([x, y])

    def wake_pointer(self):
        self.click(400, 300)

    def tally(self, name, value):
        self.tallies.append((name, value))

    def scroll(self, direction, ticks):
        self.scrolls.append([direction, ticks])

    def key(self, key, down):
        if down:
            self.held[key] = True
            self.key_downs[key] = self.key_downs.get(key, 0) + 1
        else:
            self.held.pop(key, None)
        self.max_held = max(self.max_held, len(self.held))

    def sleep(self, ms):
        self.waits += 1
        time.sleep((ms if self.real_time else min(ms, 5)) / 1000)

    def result(self, won):
        self.results.append(won)

    def trace(self, *args):
        pass

    def release(self):
        self.held, self.released = {}, True


class FrameworkTests(unittest.TestCase):
    def setUp(self):
        self.definition = jsonutil.read(os.path.join(ROOT, "tests", "data", "flow-fixture.json"))
        self.example = copy.deepcopy(self.definition)
        self.example["workflows"]["example"] = {"name": "Enter stage example", "steps": [
            {"action": "retry", "attempts": 3, "condition": image_condition("popup-close"), "failure": "error", "id": "retry-entry",
             "intervalMs": 100, "timeoutMs": 100, "steps": [
                 {"action": "click-point", "button": "Left", "id": "click-one", "x": 10, "y": 20},
                 {"action": "click-point", "button": "Right", "id": "click-two", "x": 30, "y": 40},
                 {"action": "walk", "durationMs": 30, "id": "walk", "keys": ["W", "D"], "sprint": 1, "sprintKey": "Shift"}]},
            {"action": "move", "id": "move", "x": 600, "y": 300},
            {"action": "scroll", "count": 3, "direction": "Down", "id": "scroll", "intervalMs": 0, "ticks": 2},
            {"action": "click-point", "button": "Left", "id": "select", "x": 100, "y": 200},
            {"action": "click-point", "button": "Left", "id": "start", "x": 400, "y": 500},
            {"action": "wait", "condition": image_condition("close-a"), "id": "loaded", "missing": "error", "timeoutMs": 3600000}]}
        result = {"action": "outcome", "defeat": "close-a", "elseSteps": [{"action": "move", "id": "lose", "x": 30, "y": 40}],
                  "id": "result", "thenSteps": [{"action": "move", "id": "win", "x": 10, "y": 20}], "timeoutMs": 100, "victory": "popup-close"}
        self.example["workflows"]["result"] = {"name": "Match result", "steps": [result]}

    def run_flow(self, flow, env, definition=None):
        runner = FlowRunner(definition or self.example, env)
        env.runner = runner
        runner.run(flow)
        return runner

    def test_bundled_macros_validate(self):
        from pantheon.packages import MacroPackages
        for name in os.listdir(os.path.join(ROOT, "macros")):
            if name.endswith(".json"):
                with open(os.path.join(ROOT, "macros", name), encoding="utf-8") as file:
                    package = MacroPackages.parse(file.read())
                self.assertEqual(package["id"] + ".json", name)

    def test_entry_sequence(self):
        env = FixtureEnvironment()
        env.found_after = {"Popup close": 4, "Close button A": 6}
        self.run_flow("example", env)
        self.assertEqual(len(env.clicks), 6, "entry sequence retries only until detection succeeds")
        self.assertEqual(env.clicks[1][2], "Right")
        self.assertEqual(env.max_held, 3)
        self.assertEqual(len(env.held), 0)
        self.assertEqual(env.moves[0][0], 600)
        self.assertEqual(len(env.scrolls), 3)

    def test_outcome(self):
        env = FixtureEnvironment()
        env.found_after = {"Popup close": 0}
        self.run_flow("result", env)
        self.assertEqual((env.moves[0][0], env.results), (10, [True]))
        env = FixtureEnvironment()
        env.found_after = {"Close button A": 0}
        self.run_flow("result", env)
        self.assertEqual((env.moves[0][0], env.results), (30, [False]))
        env = FixtureEnvironment()
        with self.assertRaises(FlowImageError):
            self.run_flow("result", env)
        self.assertEqual(env.results, [])

    def test_conditions(self):
        combo = {"checks": [{"state": "present", "target": "popup-close"}, {"checks": [{"state": "present", "target": "close-a"},
                 {"state": "absent", "target": "close-b"}], "operator": "any"}], "operator": "all"}
        self.example["workflows"]["logic"] = {"name": "Logic", "steps": [{"action": "if", "condition": combo, "elseSteps": [], "id": "branch",
                                              "thenSteps": [{"action": "click-point", "button": "Right", "id": "yes", "x": 25, "y": 35}]}]}
        env = FixtureEnvironment()
        env.found_after = {"Popup close": 0}
        self.run_flow("logic", env)
        self.assertEqual(len(env.clicks), 1)
        self.assertEqual(env.clicks[0][0], 25)

    def test_until_loops(self):
        self.example["workflows"]["finish"] = {"name": "Finish loop", "steps": [{"action": "until", "condition": image_condition("popup-close"),
            "failure": "error", "id": "finish", "intervalMs": 100, "steps": [{"action": "scroll", "count": 1, "direction": "Up", "id": "poll-action",
            "intervalMs": 0, "ticks": 1}], "timeoutMs": 1000}]}
        env = FixtureEnvironment()
        env.detect_after_scroll = True
        self.run_flow("finish", env)
        self.assertEqual(len(env.scrolls), 2)
        self.example["workflows"]["short-loop"] = {"name": "Short loop", "steps": [
            {"action": "until", "condition": image_condition("popup-close"), "failure": "continue", "id": "deadline", "intervalMs": 100,
             "steps": [{"action": "walk", "durationMs": 1000, "id": "walk", "keys": ["W", "D"], "sprint": 1, "sprintKey": "Shift"}], "timeoutMs": 100},
            {"action": "move", "id": "continued", "x": 1, "y": 2}]}
        env = FixtureEnvironment()
        env.real_time = True
        started = time.monotonic()
        self.run_flow("short-loop", env)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(len(env.held), 0)
        self.assertEqual(len(env.moves), 1)

    def test_until_runs_managed_upgrades(self):
        class Managed:
            ticks = closed = 0
            def tick(self): Managed.ticks += 1
            def close(self): Managed.closed += 1
        self.example["workflows"]["wave"] = {"name": "Wave", "steps": [{"action": "until", "condition": image_condition("popup-close"),
            "failure": "error", "id": "wave", "intervalMs": 100, "steps": [{"action": "scroll", "count": 1, "direction": "Up", "id": "s",
            "intervalMs": 0, "ticks": 1}], "timeoutMs": 5000}]}
        env = FixtureEnvironment()
        env.detect_after_scroll = True
        runner = FlowRunner(self.example, env)
        runner.managed = Managed()
        runner.started = int(time.monotonic() * 1000)
        runner.execute("wave")
        self.assertGreater(Managed.ticks, 0)
        self.assertEqual(Managed.closed, 1)

    def test_retry_failure_continues(self):
        self.example["workflows"]["retry-failure"] = {"name": "Retry failure", "steps": [
            {"action": "retry", "attempts": 2, "condition": image_condition("popup-close"), "failure": "continue", "id": "retry", "intervalMs": 100,
             "steps": [{"action": "wait", "condition": image_condition("popup-close"), "id": "check", "missing": "error", "timeoutMs": 100}], "timeoutMs": 100},
            {"action": "move", "id": "continued", "x": 2, "y": 3}]}
        env = FixtureEnvironment()
        self.run_flow("retry-failure", env)
        self.assertEqual(len(env.moves), 1)
        self.assertGreaterEqual(env.waits, 2)

    def test_cancel_releases_keys(self):
        self.example["workflows"]["hold"] = {"name": "Hold", "steps": [{"action": "key", "durationMs": 5000, "id": "hold", "key": "W"}]}
        env = FixtureEnvironment()
        env.cancel_after = 3
        with self.assertRaises(FlowStop):
            self.run_flow("hold", env)
        self.assertEqual(env.held, {})
        self.assertTrue(env.released)

    def test_rotate_step(self):
        drags = []
        self.example["workflows"]["turn"] = {"name": "Turn", "steps": [{"action": "rotate", "dx": 60, "dy": 0, "id": "turn"}]}
        env = FixtureEnvironment()
        env.drag = lambda dx, dy: drags.append((dx, dy))
        self.run_flow("turn", env)
        self.assertEqual(drags, [(60, 0)])
        bad = copy.deepcopy(self.example)
        bad["workflows"]["turn"]["steps"][0]["dx"] = 0
        with self.assertRaises(ValueError):
            schema.validate(bad)

    def test_if_number_needs_three_agreeing_reads(self):
        number = {"action": "if-number", "id": "wave", "x": 150, "y": 52, "width": 120, "height": 32, "filter": "none", "min": 30,
                  "thenSteps": [{"action": "click-point", "button": "Left", "id": "hit", "x": 1, "y": 1}], "elseSteps": []}
        self.example["workflows"]["wave"] = {"name": "Wave", "steps": [number]}
        for reads, hits in (([30, 31, 30], 1), ([143, 12, 30], 0), ([None, 30, 30], 0)):
            env = FixtureEnvironment()
            queue = list(reads)
            env.read_number = lambda *rect: queue.pop(0)
            self.run_flow("wave", env)
            self.assertEqual(len(env.clicks), hits)
        bad = copy.deepcopy(self.example)
        bad["workflows"]["wave"]["steps"][0]["width"] = 700
        with self.assertRaises(ValueError):
            schema.validate(bad)

    def test_tally_and_count_result(self):
        self.example["workflows"]["end"] = {"name": "End", "steps": [
            {"action": "tally", "id": "gems", "x": 112, "y": 80, "width": 86, "height": 26, "filter": "light", "counter": "Gems"},
            {"action": "count-result", "id": "won", "result": "win"}]}
        for reads, expected in (([242, 242, 242], [("Gems", 242)]), ([242, 24, 242], [("Gems", 242)]), ([1, 2, 3], [])):
            env = FixtureEnvironment()
            queue = list(reads)
            env.read_number = lambda *args: queue.pop(0)
            self.run_flow("end", env)
            self.assertEqual(env.tallies, expected)
            self.assertEqual(env.results, [True])
        bad = copy.deepcopy(self.example)
        bad["workflows"]["end"]["steps"][1]["result"] = "draw"
        with self.assertRaises(ValueError):
            schema.validate(bad)

    def test_placement_retries_unconfirmed_clicks(self):
        from pantheon.framework import placement_feedback

        class Runner:
            play_keys, result_targets = {"cancel": "Q", "slot-4": "4"}, []

            def __init__(self, panel_after):
                self.clicks, self.closed, self.panel_after = 0, False, panel_after
                outer = self

                class Env:
                    def click(self, x, y):
                        if (x, y) == (1, 1):
                            outer.closed = True
                        else:
                            outer.clicks += 1

                    def trace(self, *args):
                        pass
                self.environment = Env()

            def check(self): pass
            def hold(self, keys, ms): pass
            def wait(self, ms): pass

            def find(self, target, timeout):
                return target == "panel" and self.clicks >= self.panel_after and not self.closed

        config = {"panel": "panel", "money": "money", "limit": "", "unique": "", "closeX": 1, "closeY": 1, "retryMs": 250, "observeMs": 100}
        action = {"timeoutMs": 10000, "slot": 4, "id": "demon", "x": 10, "y": 10}
        runner = Runner(3)
        self.assertEqual(placement_feedback.place(runner, action, config), 1)
        self.assertEqual(runner.clicks, 3)
        runner = Runner(99)
        with self.assertRaises(FlowImageError):
            placement_feedback.place(runner, action, config)
        self.assertEqual(runner.clicks, 2 * placement_feedback.UNCONFIRMED_ATTEMPTS)

    def test_recorder_half_frame(self):
        from pantheon.recorder import _half
        frame = Frame(4, 2, bytes(range(24)))
        self.assertEqual(_half(frame).data, bytes([0, 1, 2, 6, 7, 8]))

    def test_engine_recovers_in_repeat_mode(self):
        from pantheon import engine
        calls = []

        class FakeRecorder:
            def __init__(self, *args): pass
            log = snapshot = finish = lambda self, *args: None

        def workflow(definition, values, placements, controls, address, ident):
            calls.append(ident)
            if ident == "main" and calls.count("main") < 3:
                raise FlowImageError("boom")
            if calls.count("main") >= 3:
                raise FlowStop("Workflow stopped.")

        saved = engine.Recorder, engine.HubEngine._workflow
        engine.Recorder, engine.HubEngine._workflow = FakeRecorder, classmethod(lambda cls, *a: workflow(*a))
        try:
            definition = {"name": "Fake", "entry": "main", "runMode": "repeat", "workflows": {"main": {}, "recover": {}}}
            engine.HubEngine.thread = object()
            engine.HubEngine._run(definition, {}, None, {}, "0x1")
        finally:
            engine.Recorder, engine.HubEngine._workflow = saved
            engine.HubEngine.thread = None
        self.assertEqual(calls, ["main", "recover", "main", "recover", "main"])

    def test_schema_rejects_bad_input(self):
        bad = copy.deepcopy(self.definition)
        bad["workflows"]["enter-map"]["steps"].append({"action": "eval", "id": "x"})
        with self.assertRaises(ValueError):
            schema.validate(bad)
        bad = copy.deepcopy(self.definition)
        bad["unexpected"] = 1
        with self.assertRaises(ValueError):
            schema.validate(bad)
        bad = copy.deepcopy(self.definition)
        bad["workflows"]["loop"] = {"name": "Loop", "steps": [{"action": "call", "id": "c", "workflow": "loop"}]}
        with self.assertRaises(ValueError):
            schema.validate(bad)

    def test_placement_plan_links(self):
        start = {"delayMs": 0, "id": "start-game", "kind": "start", "repeat": 1, "slot": 1, "timeoutMs": 30000, "x": 5, "y": 5}
        place = dict(start, id="p1", kind="place", slot=2, x=100, y=120)
        upgrade = dict(start, id="u1", kind="upgrade", slot=2, x=100, y=120)
        teams = [{"steps": [start]} for _ in range(8)]
        teams[0] = {"steps": [start, place, upgrade]}
        plan = placement_plan.validate({"routes": [{"id": "shared", "name": "Shared", "team": 1, "teams": teams}], "selectedRoute": "shared", "version": 1}, True)
        self.assertEqual(plan["routes"][0]["teams"][0]["steps"][2]["placement"], "p1")
        teams[0] = {"steps": [start, upgrade, place]}
        with self.assertRaises(ValueError):
            placement_plan.validate({"routes": [{"id": "shared", "name": "Shared", "team": 1, "teams": teams}], "selectedRoute": "shared", "version": 1}, True)


class FindTextTests(unittest.TestCase):
    @staticmethod
    def encode(frame, threshold):
        bits = "".join("1" if frame.data[i * 3] * 38 + frame.data[i * 3 + 1] * 75 + frame.data[i * 3 + 2] * 15 < (threshold + 1) << 7 else "0"
                       for i in range(frame.width * frame.height))
        bits += "1"
        bits += "0" * ((6 - len(bits) % 6) % 6)
        return "|<>*%d$%d." % (threshold, frame.width) + "".join(ALPHABET[int(bits[i:i + 6], 2)] for i in range(0, len(bits), 6))

    def test_round_trip_and_overlap(self):
        width, height = 120, 80
        data = bytearray([240] * (width * height * 3))
        for x0, y0 in ((10, 10), (70, 40)):
            for y in range(y0, y0 + 12):
                for x in range(x0, x0 + 20):
                    if (x - x0) % 3 == 0 or y == y0:
                        i = (y * width + x) * 3
                        data[i:i + 3] = b"\x10\x10\x10"
        frame = Frame(width, height, bytes(data))
        pattern = self.encode(frame.crop(10, 10, 20, 12), 128)
        schema.pattern(pattern)
        found = findtext.find(frame, 0, 0, width - 1, height - 1, 1e-9, 1e-9, pattern)
        self.assertEqual([(m["x"], m["y"]) for m in found], [(20, 16), (80, 46)])
        found = findtext.find(frame, 40, 0, width - 1, height - 1, 1e-9, 1e-9, pattern)
        self.assertEqual([(m["x"], m["y"]) for m in found], [(80, 46)])

    def test_tolerance(self):
        width, height = 40, 30
        data = bytearray([255] * (width * height * 3))
        for y in range(5, 15):
            for x in range(5, 15):
                i = (y * width + x) * 3
                data[i:i + 3] = b"\x00\x00\x00"
        frame = Frame(width, height, bytes(data))
        pattern = self.encode(frame.crop(5, 5, 10, 10), 100)
        data[(7 * width + 7) * 3:(7 * width + 7) * 3 + 3] = b"\xff\xff\xff"
        damaged = Frame(width, height, bytes(data))
        self.assertEqual(findtext.find(damaged, 0, 0, width - 1, height - 1, 1e-9, 1e-9, pattern), [])
        self.assertEqual(len(findtext.find(damaged, 0, 0, width - 1, height - 1, 0.05, 0.05, pattern)), 1)


class JsonTests(unittest.TestCase):
    def test_ahk_semantics(self):
        self.assertEqual(jsonutil.parse('{"b":true,"a":null,"c":[false]}'), {"a": "", "b": 1, "c": [0]})
        self.assertEqual(list(jsonutil.parse('{"z":1,"a":2}')), ["a", "z"])


if __name__ == "__main__":
    unittest.main()
