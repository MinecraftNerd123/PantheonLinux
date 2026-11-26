import re

from pantheon.framework import base, managed_upgrade, placement_feedback, placement_plan, play_controls, settings
from pantheon.framework.base import enum, identifier, integer, keys, reference, target, text

ACTIONS = ["click-point", "click", "click-setting", "move", "walk", "scroll", "wait", "delay", "press", "key", "call", "repeat",
           "for-setting", "if", "retry", "until", "stop", "camera", "placements", "outcome", "click-wait", "scroll-option",
           "dismiss", "setting-call", "ocr-input", "match-result"]
ICONS = ["pantheon", "dungeons", "gems", "gold", "limit", "summer", "progressive", "raids", "challenges", "winter"]
ALPHABET = "0123456789+/ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_PART = re.compile(r"^<[^<>]{0,64}>\*(\d{1,3})\$(\d{1,3})\.([0-9+/A-Za-z]+)$")
_KEY = re.compile(r"^(?:[A-Z0-9]|Space|Tab|Enter|Escape|Up|Down|Left|Right|Shift|Control)$")


def bits_from_base64(data):
    out = []
    for char in data:
        n = ALPHABET.index(char)
        out.append(format(n, "06b"))
    return "".join(out)


def pattern(value):
    text(value, 100000, "FindText capture")
    if value == "" or len(value) > 100000:
        raise ValueError("A FindText capture is required.")
    count = 0
    for part in value.split("|"):
        if part == "" and count == 0:
            continue
        count += 1
        match = _PART.match(part)
        if count > 8 or not match:
            raise ValueError("Use grayscale FindText captures in framework targets.")
        if int(match.group(1)) > 255 or int(match.group(2)) < 1 or int(match.group(2)) > 800:
            raise ValueError("Invalid FindText threshold or width.")
        bits = bits_from_base64(match.group(3))
        if not re.search(r"10*$", bits):
            raise ValueError("Invalid FindText padding.")
        bits = re.sub(r"10*$", "", bits)
        width = int(match.group(2))
        if not bits or len(bits) % width or len(bits) // width > 600:
            raise ValueError("Invalid FindText capture height.")
    return value


def validate(raw):
    keys(raw, "version|game|mode|name|client|targets|workflows|settings|entry|runMode|icon|maps|controls|playback")
    if "icon" in raw:
        enum(raw["icon"], ICONS, "macro icon")
    if "runMode" in raw:
        enum(raw["runMode"], ["once", "repeat"], "run mode")
    integer(raw["version"], 1, 1, "Definition version")
    identifier(raw["game"])
    identifier(raw["mode"])
    text(raw["name"], 100, "definition name")
    keys(raw["client"], "width|height")
    integer(raw["client"]["width"], 800, 800, "Client width")
    integer(raw["client"]["height"], 600, 600, "Client height")
    if (not isinstance(raw["targets"], dict) or len(raw["targets"]) > 128 or not isinstance(raw["workflows"], dict)
            or len(raw["workflows"]) < 1 or len(raw["workflows"]) > 32):
        raise ValueError("Definition has too many targets or workflows.")
    for ident, t in raw["targets"].items():
        identifier(ident)
        keys(t, "name|kind|pattern|x|y|width|height|error1|error0|offsetX|offsetY")
        text(t["name"], 80, "target name")
        enum(t["kind"], ["point", "pattern"], "target type")
        text(t["pattern"], 100000, "FindText capture")
        if t["kind"] == "pattern":
            if t["pattern"] == "":
                raise ValueError("Capture an image for target: " + t["name"])
            pattern(t["pattern"])
        elif t["pattern"] != "":
            raise ValueError("Coordinate targets cannot contain a capture.")
        integer(t["x"], 0, 799, "Target X")
        integer(t["y"], 0, 599, "Target Y")
        integer(t["width"], 1, 800 - t["x"], "Target width")
        integer(t["height"], 1, 600 - t["y"], "Target height")
        integer(t["error1"], 0, 20, "Foreground mismatch")
        integer(t["error0"], 0, 20, "Background mismatch")
        integer(t["offsetX"], -799, 799, "Click offset X")
        integer(t["offsetY"], -599, 599, "Click offset Y")
    maps = raw.get("maps", {})
    if not isinstance(maps, dict) or len(maps) > 48:
        raise ValueError("A macro supports up to 48 maps.")
    for ident, spec in maps.items():
        identifier(ident)
        keys(spec, "name|parent")
        text(spec["name"], 80, "map name")
        if ident in ("shared", "selected") or base.trim(spec["name"]) == "":
            raise ValueError("Choose a unique map name and identifier.")
    for ident, spec in maps.items():
        parent = spec.get("parent", "")
        if parent != "":
            identifier(parent)
            if parent == ident or parent not in maps or maps[parent].get("parent", "") != "":
                raise ValueError("Map children must belong to a top-level map.")
    playback = placement_plan.config(raw.get("playback", {}))
    if "managedUpgrade" in playback:
        managed_upgrade.config(playback["managedUpgrade"], raw)
    if "placementFeedback" in playback:
        placement_feedback.config(playback["placementFeedback"], raw)
    settings.validate(raw)
    play_controls.definition_check(raw)
    if "entry" in raw:
        reference(raw, raw["entry"])
    total = [0]
    for ident, flow in raw["workflows"].items():
        identifier(ident)
        keys(flow, "name|steps")
        text(flow["name"], 80, "workflow name")
        steps(raw, flow["steps"], total, 0)
    done = {}
    for ident in raw["workflows"]:
        visit(raw, ident, set(), 0, done)
    return raw


def point(raw, definition=None):
    if definition is not None:
        param(definition, raw["x"], 0, 799, "X")
        param(definition, raw["y"], 0, 599, "Y")
    else:
        integer(raw["x"], 0, 799, "X")
        integer(raw["y"], 0, 599, "Y")


def param(raw, value, low, high, label):
    settings.parameter(raw, value, low, high, label)


def maximum(raw, value):
    return settings.spec(raw, value["setting"]).get("max", 1) if isinstance(value, dict) else value


def failure(value):
    enum(value, ["error", "continue"], "failure behaviour")


def condition(raw, cond, depth=0, nodes=None):
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if nodes[0] > 64:
        raise ValueError("An image condition supports up to 64 checks and groups.")
    if depth > 3:
        raise ValueError("Image conditions can have up to four group levels.")
    keys(cond, "operator|checks")
    enum(cond["operator"], ["all", "any"], "condition operator")
    if not isinstance(cond["checks"], list) or len(cond["checks"]) < 1 or len(cond["checks"]) > 8:
        raise ValueError("An image group needs between one and eight checks.")
    for check in cond["checks"]:
        if isinstance(check, dict) and "operator" in check:
            condition(raw, check, depth + 1, nodes)
        elif isinstance(check, dict) and "selectedImage" in check:
            keys(check, "selectedImage|state")
            enum(check["state"], ["present", "absent"], "image check")
            spec = settings.spec(raw, check["selectedImage"])
            if spec["type"] != "select":
                raise ValueError("Selected image checks require a dropdown setting.")
            for option in spec["options"]:
                target(raw, option.get("target", ""))
                if raw["targets"][option["target"]]["kind"] != "pattern":
                    raise ValueError("Every dropdown option must map to a FindText image.")
        elif isinstance(check, dict) and "setting" in check:
            settings.check(raw, check)
        else:
            keys(check, "target|state")
            target(raw, check["target"])
            enum(check["state"], ["present", "absent"], "image check")
            if raw["targets"][check["target"]]["kind"] != "pattern":
                raise ValueError("Image checks require a FindText capture.")


def steps(raw, items, total, depth):
    if depth > 8 or not isinstance(items, list) or len(items) > 100:
        raise ValueError("Step groups support up to 100 steps and eight nested levels.")
    ids = set()
    for step in items:
        total[0] += 1
        if total[0] > 1000:
            raise ValueError("A definition supports up to 1000 steps.")
        if not isinstance(step, dict):
            raise ValueError("Expected a definition object.")
        identifier(step["id"])
        enum(step["action"], ACTIONS, "sequence action")
        if "button" in step:
            enum(step["button"], ["Left", "Right"], "mouse button")
        if "missing" in step:
            enum(step["missing"], ["error", "skip"], "missing-image behaviour")
        if step["id"] in ids:
            raise ValueError("Duplicate step identifier.")
        ids.add(step["id"])
        _step(raw, step, total, depth)


def _step(raw, step, total, depth):
    action = step["action"]
    if action == "ocr-input":
        keys(step, "id|action|readX|readY|width|height|x|y|filter|stripSpaces|clear|minLength|maxLength|missing")
        integer(step["readX"], 0, 799, "OCR region X")
        integer(step["readY"], 0, 599, "OCR region Y")
        integer(step["width"], 1, 800 - step["readX"], "OCR region width")
        integer(step["height"], 1, 600 - step["readY"], "OCR region height")
        integer(step["x"], 0, 799, "Textbox X")
        integer(step["y"], 0, 599, "Textbox Y")
        enum(step["filter"], ["digits", "alphanumeric", "text"], "OCR text filter")
        integer(step["stripSpaces"], 0, 1, "Remove spaces")
        integer(step["clear"], 0, 1, "Replace textbox content")
        integer(step["minLength"], 1, 128, "Minimum text length")
        integer(step["maxLength"], step["minLength"], 128, "Maximum text length")
        enum(step["missing"], ["error", "skip"], "OCR failure behaviour")
    elif action == "camera":
        keys(step, "id|action|zoomIn|zoomOut|tilt")
        integer(step["zoomIn"], 1, 50, "Zoom in ticks")
        integer(step["zoomOut"], 1, 50, "Zoom out ticks")
        integer(step["tilt"], 30, 299, "Camera tilt")
    elif action == "placements":
        keys(step, "id|action|route|fallback|setting")
        enum(step["fallback"], ["shared", "error"], "placement fallback")
        if step["route"] == "setting":
            spec = settings.spec(raw, step["setting"])
            if spec["type"] != "select":
                raise ValueError("Map selection requires a dropdown.")
            for option in spec["options"]:
                if option.get("map", "") not in raw.get("maps", {}):
                    raise ValueError("Map every dropdown option to a placement map.")
        if step["route"] not in ("setting", "selected", "shared") and step["route"] not in raw.get("maps", {}):
            raise ValueError("Choose a map defined by this macro or the player's selected setup.")
    elif action in ("click-wait", "dismiss"):
        keys(step, "id|action|target|ready|button|attempts|timeoutMs|intervalMs" if action == "click-wait" else "id|action|target|ready|button|timeoutMs|intervalMs")
        target(raw, step["target"])
        target(raw, step["ready"])
        if raw["targets"][step["ready"]]["kind"] != "pattern" or step["target"] == step["ready"]:
            raise ValueError("Choose a separate ready image that confirms the next screen.")
        enum(step["button"], ["Left", "Right"], "mouse button")
        param(raw, step["timeoutMs"], 100, 60000, "Component timeout")
        param(raw, step["intervalMs"], 100, 5000, "Component interval")
        if action == "click-wait":
            param(raw, step["attempts"], 1, 5, "Click attempts")
    elif action == "scroll-option":
        keys(step, "id|action|setting|x|y|direction|maxScrolls|timeoutMs|intervalMs")
        spec = settings.spec(raw, step["setting"])
        if spec["type"] != "select":
            raise ValueError("Scroll to option requires a dropdown setting.")
        for option in spec["options"]:
            target(raw, option.get("target", ""))
            if raw["targets"][option["target"]]["kind"] != "pattern":
                raise ValueError("Map each dropdown option to a captured image before scrolling to it.")
        point(step, raw)
        enum(step["direction"], ["Up", "Down"], "scroll direction")
        param(raw, step["maxScrolls"], 1, 100, "Maximum scrolls")
        param(raw, step["timeoutMs"], 100, 60000, "Scroll timeout")
        param(raw, step["intervalMs"], 100, 5000, "Scroll interval")
    elif action == "setting-call":
        keys(step, "id|action|setting|routes")
        spec = settings.spec(raw, step["setting"])
        if spec["type"] != "select" or not isinstance(step["routes"], dict) or len(step["routes"]) != len(spec["options"]):
            raise ValueError("Map every dropdown option to a sequence.")
        for option in spec["options"]:
            if option["value"] not in step["routes"]:
                raise ValueError("Choose a sequence for option: " + option["label"])
            reference(raw, step["routes"][option["value"]])
    elif action == "match-result":
        keys(step, "id|action|victory|defeat|dismiss|lobby|replay|next|lobbyReady|matchReady|victoryAction|defeatAction|victorySetting|defeatSetting|timeoutMs|menuTimeoutMs|transitionTimeoutMs|intervalMs")
        seen = set()
        for field in ("victory", "defeat", "lobby", "lobbyReady", "matchReady", "replay", "next"):
            ident = step[field]
            if ident == "" and field in ("replay", "next"):
                continue
            target(raw, ident)
            if raw["targets"][ident]["kind"] != "pattern":
                raise ValueError("Match result " + field + " requires a captured image.")
            if ident in seen:
                raise ValueError("Use separate images for match result detection, buttons and destination screens.")
            seen.add(ident)
        if step["dismiss"] != "":
            target(raw, step["dismiss"])
        for side in ("victory", "defeat"):
            enum(step[side + "Action"], ["lobby", "replay", "next", "setting"], "After " + side)
            if step[side + "Action"] == "setting":
                spec = settings.spec(raw, step[side + "Setting"])
                if spec["type"] != "select":
                    raise ValueError("Match result choices require a dropdown setting.")
                for option in spec["options"]:
                    if option.get("target", "") == "" or option["target"] not in (step["lobby"], step["replay"], step["next"]):
                        raise ValueError("Map each result setting option to the Lobby, Replay or Next stage button image.")
        param(raw, step["timeoutMs"], 100, 3600000, "Match result timeout")
        param(raw, step["menuTimeoutMs"], 100, 120000, "Reward dismissal timeout")
        param(raw, step["transitionTimeoutMs"], 100, 180000, "Destination loading timeout")
        param(raw, step["intervalMs"], 100, 5000, "Reward click interval")
    elif action == "outcome":
        keys(step, "id|action|victory|defeat|timeoutMs|thenSteps|elseSteps")
        for field in ("victory", "defeat"):
            target(raw, step[field])
            if raw["targets"][step[field]]["kind"] != "pattern":
                raise ValueError("Match results require captured images.")
        if step["victory"] == step["defeat"]:
            raise ValueError("Choose different Victory and Defeat images.")
        param(raw, step["timeoutMs"], 100, 3600000, "Match result timeout")
        steps(raw, step["thenSteps"], total, depth + 1)
        steps(raw, step["elseSteps"], total, depth + 1)
    elif action == "stop":
        keys(step, "id|action")
    elif action == "click-point":
        keys(step, "id|action|x|y|button")
        point(step, raw)
        if step["button"] not in ("Left", "Right"):
            raise ValueError("Choose left or right click.")
    elif action == "move":
        keys(step, "id|action|x|y")
        point(step, raw)
    elif action == "walk":
        keys(step, "id|action|keys|sprint|sprintKey|durationMs")
        if not isinstance(step["keys"], list) or len(step["keys"]) < 1 or len(step["keys"]) > 2:
            raise ValueError("Choose one or two movement directions.")
        directions = set()
        for item in step["keys"]:
            if not isinstance(item, str) or not re.match(r"^[WASD]$", item) or item in directions:
                raise ValueError("Walking only supports distinct W, A, S and D keys.")
            directions.add(item)
        if {"W", "S"} <= directions or {"A", "D"} <= directions:
            raise ValueError("Choose movement directions that do not oppose each other.")
        param(raw, step["sprint"], 0, 1, "Sprint")
        if step["sprintKey"] not in ("Shift", "Control"):
            raise ValueError("Choose Shift or Control for sprint.")
        param(raw, step["durationMs"], 30, 30000, "Walking duration")
    elif action == "scroll":
        enum(step["direction"], ["Up", "Down"], "scroll direction")
        keys(step, "id|action|direction|ticks|count|intervalMs")
        param(raw, step["ticks"], 1, 10, "Scroll amount")
        param(raw, step["count"], 1, 100, "Scroll repeats")
        param(raw, step["intervalMs"], 0, 5000, "Scroll interval")
        if maximum(raw, step["count"]) * maximum(raw, step["intervalMs"]) > 60000:
            raise ValueError("A scroll step cannot take longer than one minute.")
    elif action == "click-setting":
        keys(step, "id|action|setting|timeoutMs|missing|button")
        spec = settings.spec(raw, step["setting"])
        if spec["type"] not in ("select", "multiselect", "priority"):
            raise ValueError("Choose a dropdown or list setting for this step.")
        for option in spec["options"]:
            if option.get("target", "") == "":
                raise ValueError("Map each option to an image or coordinate for setting: " + spec["label"])
        param(raw, step["timeoutMs"], 0, 60000, "Timeout")
        if step["missing"] not in ("skip", "error"):
            raise ValueError("Unknown missing-target behaviour.")
        if step["button"] not in ("Left", "Right"):
            raise ValueError("Choose left or right click.")
    elif action in ("click", "wait"):
        keys(step, "id|action|condition|timeoutMs|missing" if "condition" in step else "id|action|target|timeoutMs|missing|button")
        if action == "wait" and "condition" in step:
            condition(raw, step["condition"])
        else:
            target(raw, step["target"])
        if "button" in step and step["button"] not in ("Left", "Right"):
            raise ValueError("Choose left or right click.")
        param(raw, step["timeoutMs"], 100 if action == "wait" else 0, 3600000 if action == "wait" else 60000, "Timeout")
        if step["missing"] not in ("skip", "error"):
            raise ValueError("Unknown missing-target behaviour.")
    elif action == "delay":
        keys(step, "id|action|durationMs")
        param(raw, step["durationMs"], 0, 60000, "Delay")
    elif action in ("key", "press"):
        keys(step, "id|action|key|durationMs" if action == "key" else "id|action|key|count|intervalMs")
        if not isinstance(step["key"], str) or not _KEY.match(step["key"]):
            raise ValueError("Unsupported key.")
        if action == "key":
            param(raw, step["durationMs"], 30, 10000, "Key duration")
        else:
            param(raw, step["count"], 1, 20, "Key presses")
            param(raw, step["intervalMs"], 0, 5000, "Key interval")
    elif action == "for-setting":
        keys(step, "id|action|setting|steps")
        spec = settings.spec(raw, step["setting"])
        if spec["type"] not in ("multiselect", "priority"):
            raise ValueError("Choose a checkbox list or priority setting to iterate.")
        steps(raw, step["steps"], total, depth + 1)
    elif action in ("call", "repeat"):
        keys(step, "id|action|workflow" if action == "call" else ("id|action|steps|count" if "steps" in step else "id|action|workflow|count"))
        if "steps" in step:
            steps(raw, step["steps"], total, depth + 1)
        else:
            reference(raw, step["workflow"])
        if action == "repeat":
            param(raw, step["count"], 1, 20, "Repeat count")
    elif action == "if":
        if "condition" in step:
            keys(step, "id|action|condition|thenSteps|elseSteps")
            condition(raw, step["condition"])
            steps(raw, step["thenSteps"], total, depth + 1)
            steps(raw, step["elseSteps"], total, depth + 1)
        else:
            keys(step, "id|action|target|then|otherwise")
            target(raw, step["target"])
            for field in ("then", "otherwise"):
                if step[field] != "":
                    reference(raw, step[field])
    elif action in ("retry", "until"):
        keys(step, "id|action|steps|condition|attempts|timeoutMs|intervalMs|failure" if action == "retry" else "id|action|steps|condition|timeoutMs|intervalMs|failure")
        steps(raw, step["steps"], total, depth + 1)
        condition(raw, step["condition"])
        failure(step["failure"])
        param(raw, step["timeoutMs"], 100, 60000 if action == "retry" else 3600000, "Image-check timeout")
        param(raw, step["intervalMs"], 100, 10000, "Repeat interval")
        if action == "retry":
            param(raw, step["attempts"], 1, 20, "Retry attempts")
    else:
        raise ValueError("Unsupported workflow action.")


def visit(raw, ident, path, depth, done):
    if depth > 8 or ident in path:
        raise ValueError("Workflow calls cannot be recursive or more than eight levels deep.")
    if ident in done:
        if depth + done[ident] > 8:
            raise ValueError("Workflow calls cannot be more than eight levels deep.")
        return done[ident]
    path.add(ident)
    height = visit_steps(raw, raw["workflows"][ident]["steps"], path, depth, done)
    path.discard(ident)
    done[ident] = height
    return height


def visit_steps(raw, items, path, depth, done):
    if depth > 8:
        raise ValueError("Step and sequence nesting cannot exceed eight levels.")
    height = 0
    for step in items:
        action = step["action"]
        if action == "call" or (action == "repeat" and "workflow" in step):
            height = max(height, 1 + visit(raw, step["workflow"], path, depth + 1, done))
        elif action == "setting-call":
            for workflow in step["routes"].values():
                height = max(height, 1 + visit(raw, workflow, path, depth + 1, done))
        elif action == "if" and "condition" not in step:
            for field in ("then", "otherwise"):
                if step[field] != "":
                    height = max(height, 1 + visit(raw, step[field], path, depth + 1, done))
        for field in ("steps", "thenSteps", "elseSteps"):
            if field in step:
                height = max(height, 1 + visit_steps(raw, step[field], path, depth + 1, done))
    return height
