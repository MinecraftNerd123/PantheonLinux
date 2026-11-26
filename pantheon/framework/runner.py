import time

from pantheon.errors import FlowImageError, FlowLoopTimeout, FlowStop
from pantheon.framework import components, match_result, placement_feedback, placement_plan, play_controls, schema, settings
from pantheon.framework.managed_upgrade import ManagedUpgrade

NUMERIC_FIELDS = ("x", "y", "durationMs", "timeoutMs", "intervalMs", "count", "ticks", "attempts", "maxScrolls", "sprint")


def now():
    return int(time.monotonic() * 1000)


def _copy(value):
    if isinstance(value, dict):
        return {k: _copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_copy(v) for v in value]
    return value


class FlowRunner:
    def __init__(self, definition, environment, values=None):
        self.definition = schema.validate(definition)
        self.environment = environment
        self.managed, self.result_targets = None, []
        self.cancelled, self.budget, self.started, self.deadlines = False, 100000, 0, []
        self.values = settings.values(definition, values if values is not None else {})
        self.context, self.placement_data, self.play_keys = {}, None, play_controls.defaults()

    def run(self, ident):
        schema.reference(self.definition, ident)
        self.managed, self.result_targets = None, []
        self.started, self.budget, self.cancelled, self.deadlines = now(), 100000, False, []
        try:
            self.check()
            self.execute(ident)
        finally:
            self.environment.release()

    def cancel(self):
        self.cancelled = True

    def check(self):
        if self.cancelled:
            raise FlowStop("Workflow stopped.")
        if now() - self.started > 7200000 or self.budget < 1:
            raise RuntimeError("Workflow execution limit reached.")
        for limit in self.deadlines:
            if now() >= limit["end"]:
                raise FlowLoopTimeout(limit["owner"])
        self.environment.check()
        if self.cancelled:
            raise FlowStop("Workflow stopped.")

    def wait(self, milliseconds):
        while milliseconds > 0:
            self.check()
            amount = min(milliseconds, 50)
            self.environment.sleep(amount)
            milliseconds -= amount
        self.check()

    def find(self, ident, timeout):
        started = now()
        while True:
            self.check()
            found = self.environment.find(self.definition["targets"][ident])
            if found:
                return found
            if now() - started >= timeout:
                return 0
            self.wait(100)

    def execute(self, ident):
        self.execute_steps(self.definition["workflows"][ident]["steps"], ident)

    def condition(self, cond):
        all_mode = cond["operator"] == "all"
        for check in cond["checks"]:
            self.budget -= 1
            self.check()
            if "operator" in check:
                matched = self.condition(check)
            elif "selectedImage" in check:
                spec = settings.spec(self.definition, check["selectedImage"])
                target = settings.option(spec, self.values[check["selectedImage"]])["target"]
                matched = bool(self.find(target, 0))
                if check["state"] == "absent":
                    matched = not matched
            elif "setting" in check:
                matched = settings.match(self.values, check)
            else:
                matched = bool(self.find(check["target"], 0))
                if check["state"] == "absent":
                    matched = not matched
            if all_mode and not matched:
                return False
            if not all_mode and matched:
                return True
        return all_mode

    def wait_condition(self, cond, timeout):
        started = now()
        while True:
            if self.condition(cond):
                return True
            if now() - started >= timeout:
                return False
            self.wait(min(200, timeout - (now() - started)))

    def hold(self, keys, duration):
        pressed = []
        try:
            for key in keys:
                self.check()
                self.environment.key(key, True)
                pressed.append(key)
            self.wait(duration)
        finally:
            for key in reversed(pressed):
                self.environment.key(key, False)

    def push_deadline(self, milliseconds, owner):
        self.deadlines.append({"end": now() + milliseconds, "owner": owner})

    def until(self, step, location):
        matched = False
        self.push_deadline(step["timeoutMs"], location)
        try:
            while True:
                self.budget -= 1
                self.check()
                if self.condition(step["condition"]):
                    self.check()
                    matched = True
                    break
                self.execute_steps(step["steps"], location)
                self.wait(step["intervalMs"])
        except FlowLoopTimeout as err:
            if err.owner != location:
                raise
        finally:
            self.deadlines.pop()
        if not matched and step["failure"] == "error":
            raise FlowImageError("Image loop timed out (" + location + ").")

    def camera(self, step):
        env = self.environment
        env.move(400, 300)
        for _ in range(step["zoomIn"]):
            self.check()
            env.scroll("Up", 1)
            self.wait(50)
        self.wait(200)
        try:
            env.key("RButton", True)
            self.wait(100)
            for i in range(1, 11):
                self.check()
                env.move(400, 300 + step["tilt"] * i // 10)
                self.wait(20)
        finally:
            env.key("RButton", False)
        for _ in range(step["zoomOut"]):
            self.check()
            env.scroll("Down", 1)
            self.wait(50)

    def result_images(self, items, result):
        for step in items:
            if step["action"] in ("outcome", "match-result"):
                for field in ("victory", "defeat"):
                    if step[field] not in result:
                        result[step[field]] = True
            for field in ("steps", "thenSteps", "elseSteps"):
                if field in step:
                    self.result_images(step[field], result)

    def has_placements(self, route):
        return any(a["kind"] == "place" and a.get("enabled", 1) for a in route["teams"][route["team"] - 1]["steps"])

    def placements(self, step):
        if not self.placement_data:
            raise RuntimeError("No placement setup was supplied. Save a setup in Placement setup first.")
        cfg = placement_plan.config(self.definition.get("playback", {}))
        plan = placement_plan.validate(self.placement_data, True, cfg)
        ident = plan["selectedRoute"] if step["route"] == "selected" else step["route"]
        if step["route"] == "setting":
            ident = settings.option(settings.spec(self.definition, step["setting"]), self.values[step["setting"]])["map"]
        if plan.get("useShared", 0):
            ident = "shared"
        selected = shared = None
        for route in plan["routes"]:
            if route["id"] == ident:
                selected = route
            if route["id"] == "shared":
                shared = route
        if (not selected or not self.has_placements(selected)) and step["fallback"] == "shared":
            selected = shared
        if not selected or not self.has_placements(selected):
            raise RuntimeError("No unit placements configured for " + ident + ".")
        team = selected["teams"][selected["team"] - 1]["steps"]
        for action in team:
            if action["kind"] == "start" and action["enabled"] and action["x"] == 0 and action["y"] == 0:
                raise RuntimeError("Set Start Game coordinates in Placement setup, or disable it if the game starts automatically.")
        env = self.environment
        env.trace("Placement setup", selected["name"], "Team %d" % selected["team"])
        live, skipped, results = {}, set(), {}
        for flow in self.definition["workflows"].values():
            self.result_images(flow["steps"], results)
        self.result_targets = sorted(results)
        for action in team:
            self.budget -= 1
            self.check()
            if not action["enabled"]:
                continue
            kind = action["kind"]
            if kind in ("upgrade", "sell", "reconfigure") and action["placement"] in skipped:
                env.trace("Match action skipped", action["id"], "Its placement was skipped")
                continue
            self.wait(action["delayMs"])
            if kind == "wait":
                continue
            if kind == "place":
                if "placementFeedback" in cfg:
                    result = placement_feedback.place(self, action, cfg["placementFeedback"])
                    if result == -1:
                        break
                    if not result:
                        skipped.add(action["id"])
                        continue
                else:
                    self.hold([self.play_keys["slot-%d" % action["slot"]]], 30)
                    self.wait(150)
                    env.click(action["x"], action["y"])
                    self.wait(150)
                    self.hold([self.play_keys["cancel"]], 30)
                live[action["id"]] = {"targeting": 0, "auto": 0, "placement": action}
                if action["targeting"] > 0 or action["autoUpgrade"] > 0:
                    env.click(action["x"], action["y"])
                    self.wait(150)
                    self.configure_placement(live[action["id"]], action, cfg, True)
            elif kind == "start":
                env.click(action["x"], action["y"])
                self.wait(300)
            else:
                if action["placement"] not in live:
                    raise RuntimeError("The linked unit has not been placed, or was already sold.")
                state = live[action["placement"]]
                target = state["placement"]
                env.click(target["x"], target["y"])
                self.wait(150)
                if kind == "reconfigure":
                    self.configure_placement(state, action, cfg)
                elif kind == "sell":
                    self.hold([self.play_keys["sell"]], 30)
                    self.wait(200)
                    del live[action["placement"]]
                else:
                    for _ in range(action["repeat"]):
                        self.hold([self.play_keys["upgrade"]], 30)
                        self.wait(200)
        self.managed = ManagedUpgrade(self, cfg["managedUpgrade"], live) if "managedUpgrade" in cfg else None

    def outcome(self, step, location):
        self.result_targets = [step["victory"], step["defeat"]]
        self.push_deadline(step["timeoutMs"], location)
        won = False
        try:
            if self.managed:
                self.managed.close()
            while True:
                self.check()
                won = self.find(step["victory"], 0)
                lost = not won and self.find(step["defeat"], 0)
                if won or lost:
                    break
                if self.managed:
                    self.managed.tick()
                self.wait(25 if self.managed else 200)
        except FlowLoopTimeout as err:
            if err.owner != location:
                raise
            raise FlowImageError("Match result was not detected before the timeout.") from None
        finally:
            self.deadlines.pop()
        self.managed = None
        self.environment.result(bool(won))
        self.environment.trace("Match result", "Victory" if won else "Defeat", "Recorded")
        if step["action"] == "match-result":
            match_result.handle(self, step, bool(won), location)
        else:
            self.execute_steps(step["thenSteps"] if won else step["elseSteps"], location)

    def configure_placement(self, state, action, cfg, placing=False):
        if placing or action["changeTargeting"]:
            desired, count = action["targeting"], len(cfg["targeting"])
            presses = (desired - state["targeting"] + count) % count
            for _ in range(presses):
                self.hold([self.play_keys["targeting"]], 30)
                self.wait(150)
                state["targeting"] = (state["targeting"] + 1) % count
        desired = action["autoUpgrade"]
        if desired < 0:
            return
        if not cfg["autoUpgrade"]:
            if desired > 0:
                raise RuntimeError("This macro does not support auto upgrade.")
            return
        count = cfg["autoUpgradeLevels"] + 1
        presses = (desired - state["auto"] + count) % count
        for _ in range(presses):
            self.hold([self.play_keys["auto-upgrade"]], 30)
            self.wait(150)
            state["auto"] = (state["auto"] + 1) % count

    def execute_steps(self, items, context):
        env = self.environment
        for original in items:
            step = dict(original)
            for field in NUMERIC_FIELDS:
                if field in step and isinstance(step[field], dict):
                    step[field] = self.values[step[field]["setting"]]
            self.budget -= 1
            self.check()
            location = context + " / " + step["id"]
            name = step.get("name", "")
            env.trace(context, step["id"] if name == "" else name, step["action"])
            action = step["action"]
            if action == "camera":
                self.camera(step)
            elif action == "placements":
                self.placements(step)
            elif action == "stop":
                raise FlowStop("Macro stopped by its sequence.")
            elif action == "delay":
                self.wait(step["durationMs"])
            elif action == "key":
                self.hold([step["key"]], step["durationMs"])
            elif action == "press":
                for i in range(1, step["count"] + 1):
                    self.hold([step["key"]], 30)
                    if i < step["count"]:
                        self.wait(step["intervalMs"])
            elif action == "walk":
                keys = list(step["keys"])
                if step["sprint"]:
                    keys.insert(0, step["sprintKey"])
                self.hold(keys, step["durationMs"])
            elif action == "click-point":
                env.click(step["x"], step["y"], step["button"])
            elif action == "move":
                env.move(step["x"], step["y"])
            elif action == "scroll":
                for _ in range(step["count"]):
                    self.check()
                    env.scroll(step["direction"], step["ticks"])
                    self.wait(step["intervalMs"])
            elif action in ("click", "wait", "click-setting"):
                if action == "click-setting":
                    setting = step["setting"]
                    value = self.context.get(setting, self.values[setting])
                    if isinstance(value, list):
                        raise RuntimeError("Use 'For each selected item' around a list-setting click.")
                    step["target"] = settings.option(settings.spec(self.definition, setting), value)["target"]
                found = self.wait_condition(step["condition"], step["timeoutMs"]) if "condition" in step else self.find(step["target"], step["timeoutMs"])
                if not found and step["missing"] == "error":
                    raise FlowImageError("Image check failed: " + str(step.get("target", "condition")) + " (" + location + ").")
                if found and action != "wait":
                    self.check()
                    if "button" in step:
                        env.click(found["x"], found["y"], step["button"])
                    else:
                        env.click(found["x"], found["y"])
            elif action == "call":
                self.execute(step["workflow"])
            elif action == "for-setting":
                setting = step["setting"]
                existed, previous = setting in self.context, self.context.get(setting, "")
                try:
                    for value in self.values[setting]:
                        self.budget -= 1
                        self.check()
                        self.context[setting] = value
                        self.execute_steps(step["steps"], location)
                finally:
                    if existed:
                        self.context[setting] = previous
                    else:
                        self.context.pop(setting, None)
            elif action == "repeat":
                for _ in range(step["count"]):
                    if "steps" in step:
                        self.execute_steps(step["steps"], location)
                    else:
                        self.execute(step["workflow"])
            elif action in ("ocr-input", "click-wait", "scroll-option", "dismiss", "setting-call"):
                components.execute(self, step, location)
            elif action in ("outcome", "match-result"):
                self.outcome(step, location)
            elif action == "if":
                if "condition" in step:
                    self.execute_steps(step["thenSteps"] if self.condition(step["condition"]) else step["elseSteps"], location)
                else:
                    branch = step["then"] if self.find(step["target"], 0) else step["otherwise"]
                    if branch != "":
                        self.execute(branch)
            elif action == "retry":
                matched = False
                for attempt in range(1, step["attempts"] + 1):
                    self.budget -= 1
                    self.check()
                    try:
                        self.execute_steps(step["steps"], location)
                        matched = self.wait_condition(step["condition"], step["timeoutMs"])
                    except FlowImageError:
                        matched = False
                    if matched:
                        break
                    if attempt < step["attempts"]:
                        self.wait(step["intervalMs"])
                if not matched and step["failure"] == "error":
                    raise FlowImageError("Retry limit reached (" + location + ").")
            elif action == "until":
                self.until(step, location)
