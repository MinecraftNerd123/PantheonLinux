from pantheon.errors import FlowImageError, FlowLoopTimeout
from pantheon.framework import settings


def choice(r, s, won):
    side = "victory" if won else "defeat"
    selected = s[side + "Action"]
    if selected != "setting":
        return selected
    target = settings.option(settings.spec(r.definition, s[side + "Setting"]), r.values[s[side + "Setting"]])["target"]
    return "replay" if target == s["replay"] else "next" if target == s["next"] else "lobby"


def menu_visible(r, s):
    return any(s[field] != "" and r.find(s[field], 0) for field in ("lobby", "replay", "next"))


def handle(r, s, won, location):
    selected = choice(r, s, won)
    env = r.environment
    env.trace("Result handling", "Rewards", "Waiting for result menu")
    r.push_deadline(s["menuTimeoutMs"], location + " rewards")
    try:
        while True:
            r.check()
            if r.find(s["lobby"], 0):
                break
            point = r.find(s["dismiss"], 0) if s["dismiss"] != "" else 0
            if point:
                env.click(point["x"], point["y"], "Left")
            r.wait(s["intervalMs"])
    except FlowLoopTimeout as err:
        if err.owner != location + " rewards":
            raise
        raise FlowImageError("Result menu did not appear. Check the reward dismissal target and Lobby image.") from None
    finally:
        r.deadlines.pop()
    point = r.find(s[selected], 0) if s[selected] != "" else 0
    if not point and selected != "lobby":
        env.trace("Result handling", selected, "Unavailable; returning to lobby")
        selected, point = "lobby", r.find(s["lobby"], 0)
    if not point:
        raise FlowImageError("The Lobby button is no longer visible.")
    env.trace("Result handling", selected, "Clicking and waiting for destination")
    env.click(point["x"], point["y"], "Left")
    ready = s["lobbyReady"] if selected == "lobby" else s["matchReady"]
    r.push_deadline(s["transitionTimeoutMs"], location + " destination")
    try:
        while True:
            r.check()
            if not menu_visible(r, s) and r.find(ready, 0):
                break
            r.wait(100)
    except FlowLoopTimeout as err:
        if err.owner != location + " destination":
            raise
        raise FlowImageError("Result action " + selected + " did not reach its destination. Check the button and destination image.") from None
    finally:
        r.deadlines.pop()
    env.trace("Result handling", selected, "Destination ready; continuing sequence")
