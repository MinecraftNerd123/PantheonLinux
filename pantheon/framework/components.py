import re

from pantheon.errors import FlowImageError, FlowLoopTimeout
from pantheon.framework import settings


def clean_text(text, step):
    text = re.sub(r"[\x00-\x20]+", " ", text).strip(" \t")
    if step["filter"] == "digits":
        if re.search(r"[A-Za-z]", text):
            return ""
        text = re.sub(r"[^0-9]", "", text)
    elif step["filter"] == "alphanumeric":
        text = re.sub(r"[^A-Za-z0-9 ]", "", text)
    if step["stripSpaces"]:
        text = text.replace(" ", "")
    return text if step["minLength"] <= len(text) <= step["maxLength"] else ""


def execute(r, step, location):
    action = step["action"]
    if action == "ocr-input":
        text = clean_text(r.environment.read_text(step), step)
        r.check()
        if not text:
            if step["missing"] == "skip":
                return
            raise FlowImageError("OCR found no valid text. Check the capture region, filter and length limits (" + location + ").")
        r.environment.click(step["x"], step["y"], "Left")
        r.wait(100)
        r.environment.type_text(text, step["clear"])
        return
    if action == "setting-call":
        r.execute(step["routes"][r.values[step["setting"]]])
        return
    if action == "click-wait":
        cond = {"operator": "all", "checks": [{"state": "present", "target": step["ready"]}]}
        for attempt in range(1, step["attempts"] + 1):
            if r.find(step["ready"], 0):
                return
            found = r.find(step["target"], step["timeoutMs"])
            if not found:
                raise FlowImageError("Click and wait could not find its click target (" + location + ").")
            r.environment.click(found["x"], found["y"], step["button"])
            if r.wait_condition(cond, step["timeoutMs"]):
                return
            if attempt < step["attempts"]:
                r.wait(step["intervalMs"])
        raise FlowImageError("Click and wait did not detect its ready image (" + location + ").")
    r.push_deadline(step["timeoutMs"], location)
    try:
        if action == "scroll-option":
            target = settings.option(settings.spec(r.definition, step["setting"]), r.values[step["setting"]])["target"]
            for attempt in range(1, step["maxScrolls"] + 2):
                found = r.find(target, 0)
                if found:
                    r.environment.click(found["x"], found["y"], "Left")
                    return
                if attempt > step["maxScrolls"]:
                    break
                r.environment.move(step["x"], step["y"])
                r.environment.scroll(step["direction"], 1)
                r.wait(step["intervalMs"])
            raise FlowImageError("Selected option was not found within the scroll limit (" + location + ").")
        while True:
            if r.find(step["ready"], 0):
                return
            found = r.find(step["target"], 0)
            if found:
                r.environment.click(found["x"], found["y"], step["button"])
            r.wait(step["intervalMs"])
    except FlowLoopTimeout as err:
        if err.owner != location:
            raise
        raise FlowImageError("Component timed out before its ready image was found (" + location + ").") from None
    finally:
        r.deadlines.pop()
