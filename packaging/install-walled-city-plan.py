#!/usr/bin/env python3
import json
import os
import shutil
import sys

APP_ID = "io.github.MinecraftNerd123.PantheonLinux"
HERE = os.path.dirname(os.path.abspath(__file__))


def data_dir():
    flatpak = os.path.expanduser("~/.var/app/%s/data/pantheon" % APP_ID)
    if "--local" not in sys.argv and os.path.isdir(os.path.dirname(flatpak)):
        return flatpak
    return os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "pantheon")


def main():
    folder = os.path.join(data_dir(), "placements", "anime-adventures")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "plan.json")
    routes = [json.load(open(os.path.join(HERE, "walled-city", name))) for name in ("route.json", "route-takedowns.json")]
    start = {"delayMs": 0, "enabled": 1, "id": "start-game", "kind": "start", "repeat": 1, "slot": 1, "timeoutMs": 30000, "x": 0, "y": 0}
    plan = json.load(open(path)) if os.path.exists(path) else {
        "routes": [{"id": "shared", "name": "Shared setup", "parent": "", "team": 1, "teams": [{"steps": [dict(start)]} for _ in range(8)]}],
        "selectedRoute": "shared", "useShared": 0, "version": 1}
    if os.path.exists(path):
        shutil.copy(path, path + ".bak")
    ids = {route["id"] for route in routes}
    plan["routes"] = [r for r in plan["routes"] if r["id"] not in ids] + routes
    with open(path + ".tmp", "w") as file:
        json.dump(plan, file, sort_keys=True, separators=(",", ":"))
    os.replace(path + ".tmp", path)
    for ident in ids:
        shutil.copy(os.path.join(HERE, "walled-city", "walled-city.png"), os.path.join(folder, ident + ".png"))
    print("Installed the Walled City (Infinite) and (Takedowns) placement plans in", folder)


main()
