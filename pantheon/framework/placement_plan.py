import re

from pantheon import store
from pantheon.framework import base

_ROUTE = re.compile(r"^[-a-z0-9]{1,48}$")
_STEP = re.compile(r"^[-a-zA-Z0-9]{1,64}$")


def route_id(ident):
    if not isinstance(ident, str) or not _ROUTE.match(ident):
        raise ValueError("Invalid route identifier.")
    return ident


def config(raw=None):
    from pantheon.framework import managed_upgrade, placement_feedback
    raw = {} if raw is None else raw
    base.keys(raw, "targeting|autoUpgrade|autoUpgradeLevels|managedUpgrade|placementFeedback")
    names = raw.get("targeting", ["First", "Last", "Strongest", "Weakest"])
    if not isinstance(names, list) or not names or len(names) > 16:
        raise ValueError("Provide 1 to 16 targeting priorities in their in-game cycle order.")
    seen = set()
    for name in names:
        base.text(name, 40, "targeting priority")
        if base.trim(name) == "" or name in seen:
            raise ValueError("Targeting names must be unique and nonempty.")
        seen.add(name)
    result = {"autoUpgrade": store.integer(raw.get("autoUpgrade", 0), 0, 1, "Auto upgrade support"),
              "autoUpgradeLevels": store.integer(raw.get("autoUpgradeLevels", 3), 1, 10, "Auto upgrade priorities"),
              "targeting": names}
    if "managedUpgrade" in raw:
        result["managedUpgrade"] = managed_upgrade.config(raw["managedUpgrade"])
    if "placementFeedback" in raw:
        result["placementFeedback"] = placement_feedback.config(raw["placementFeedback"])
    return result


def validate(raw, strict=False, capabilities=None):
    if not isinstance(raw, dict) or raw["version"] != 1 or not isinstance(raw["routes"], list) or not raw["routes"] or len(raw["routes"]) > 60:
        raise ValueError("Invalid placement setup.")
    cfg = config(capabilities) if capabilities is not None else None
    ids, routes = set(), []
    for route in raw["routes"]:
        ident = route_id(route["id"])
        if ident in ids:
            raise ValueError("Duplicate route.")
        ids.add(ident)
        base.text(route["name"], 80, "route name")
        if base.trim(route["name"]) == "" or not isinstance(route["teams"], list) or len(route["teams"]) != 8:
            raise ValueError("Each named route requires eight teams.")
        teams = []
        for team in route["teams"]:
            if not isinstance(team["steps"], list) or len(team["steps"]) > 200:
                raise ValueError("A team supports at most 200 match steps.")
            steps, seen, starts = [], set(), 0
            for action in team["steps"]:
                if not isinstance(action["id"], str) or not _STEP.match(action["id"]) or action["id"] in seen:
                    raise ValueError("Invalid or duplicate match step.")
                seen.add(action["id"])
                kind = base.enum(action["kind"], ["start", "place", "reconfigure", "upgrade", "sell", "wait"], "match action")
                starts += 1 if kind == "start" else 0
                link = action.get("placement", "")
                if not isinstance(link, str) or (link != "" and not _STEP.match(link)):
                    raise ValueError("Invalid placed-unit reference.")
                steps.append({
                    "autoUpgrade": store.integer(action.get("autoUpgrade", -1 if kind == "reconfigure" else 0), -1 if kind == "reconfigure" else 0, 10, "Auto upgrade priority"),
                    "changeTargeting": store.integer(action.get("changeTargeting", 1), 0, 1, "Change targeting"),
                    "delayMs": store.integer(action["delayMs"], 0, 600000, "Delay"),
                    "enabled": store.integer(action.get("enabled", 1), 0, 1, "Action enabled"),
                    "id": action["id"], "kind": kind,
                    "managedLimit": store.integer(action.get("managedLimit", 0), 0, 100, "Managed upgrade limit"),
                    "managedPriority": store.integer(action.get("managedPriority", 0), 0, 10, "Managed upgrade priority"),
                    "placement": link,
                    "repeat": store.integer(action["repeat"], 1, 20, "Repeats"),
                    "slot": store.integer(action["slot"], 1, 6, "Unit slot"),
                    "targeting": store.integer(action.get("targeting", 0), 0, 15, "Targeting priority"),
                    "timeoutMs": store.integer(action["timeoutMs"], 1000, 1800000, "Placement timeout"),
                    "x": store.integer(action["x"], 0, 799, "X"), "y": store.integer(action["y"], 0, 599, "Y"),
                })
            if starts != 1:
                raise ValueError("Each team requires exactly one Start Game step.")
            places = {a["id"]: a for a in steps if a["kind"] == "place"}
            places = {k: places[k] for k in sorted(places)}
            active = set()
            for action in steps:
                kind = action["kind"]
                if kind in ("upgrade", "sell", "reconfigure"):
                    if action["placement"] == "":
                        matches = [p for p in places if places[p]["slot"] == action["slot"] and places[p]["x"] == action["x"] and places[p]["y"] == action["y"]]
                        if len(matches) == 1:
                            action["placement"] = matches[0]
                    if action["placement"] in places:
                        linked = places[action["placement"]]
                        action["slot"], action["x"], action["y"] = linked["slot"], linked["x"], linked["y"]
                    elif strict:
                        raise ValueError("Select a placed unit for every Upgrade, Sell and Reconfigure action.")
                    if strict and action["enabled"] and action["placement"] not in active:
                        raise ValueError("Place the unit before its linked action; sold units cannot be reused.")
                    if kind == "sell" and action["enabled"] and action["placement"] in active:
                        active.discard(action["placement"])
                if kind == "place" and action["enabled"]:
                    active.add(action["id"])
                if strict and cfg and action["enabled"] and kind in ("place", "reconfigure"):
                    if (kind == "place" or action["changeTargeting"]) and action["targeting"] >= len(cfg["targeting"]):
                        raise ValueError("Targeting priority is not supported by this macro.")
                    if action["autoUpgrade"] > 0 and (not cfg["autoUpgrade"] or action["autoUpgrade"] > cfg["autoUpgradeLevels"]):
                        raise ValueError("This macro does not support that auto upgrade priority.")
            teams.append({"steps": steps})
        routes.append({"id": ident, "name": route["name"], "parent": route.get("parent", ""),
                       "team": store.integer(route["team"], 1, 8, "Team"), "teams": teams})
    for route in routes:
        parent = route["parent"]
        if parent == "":
            continue
        route_id(parent)
        if parent == route["id"] or parent not in ids:
            raise ValueError("Invalid placement map parent.")
        for candidate in routes:
            if candidate["id"] == parent and candidate["parent"] != "":
                raise ValueError("Placement maps support one child level.")
    if raw["selectedRoute"] not in ids:
        raise ValueError("Selected route does not exist.")
    return {"routes": routes, "selectedRoute": raw["selectedRoute"],
            "useShared": store.integer(raw.get("useShared", 0), 0, 1, "Shared placements"), "version": 1}
