import json
import os
import re
import urllib.error
import urllib.request

from pantheon import jsonutil, paths, store
from pantheon.store import Registry

REPOSITORY = "MinecraftNerd123/PantheonLinux"


class RunSettings:
    busy_state = staticmethod(lambda: "stopped")

    @staticmethod
    def schema():
        return jsonutil.read(os.path.join(paths.UI, "run-settings-schema.json"))

    @classmethod
    def fields(cls, mode):
        if mode != "general":
            raise ValueError("Macro settings are defined by their configuration.")
        return cls.schema()["general"]

    @staticmethod
    def check(field, value):
        kind = field["type"]
        if kind in ("toggle", "select"):
            if isinstance(value, str) and re.match(r"^\d+$", value):
                value = int(value)
            if kind == "select":
                return store.integer(value, 1, len(field["options"]), field["label"])
            on, off = field.get("on", 1), field.get("off", 0)
            if not isinstance(value, int) or value not in (on, off):
                raise ValueError("Invalid value for " + field["label"] + ".")
            return value
        if not isinstance(value, str) or len(value) > field.get("maxLength", 2048) or re.search(r"[\x00-\x1f]", value):
            raise ValueError("Invalid " + field["label"] + ".")
        fmt = field.get("format", "")
        if fmt in ("server", "webhook") and '"' in value:
            raise ValueError("Invalid " + field["label"] + ".")
        if value != "":
            if fmt == "server" and not re.match(r"(?i)^https://(?:www\.)?roblox\.com/(?:games/\d+/[^\s]*[?&]privateServerLinkCode=[a-z0-9]{32}(?:&[^\s]*)?|share\?code=[a-z0-9]+&type=Server)$", value):
                raise ValueError("Enter a Roblox private-server link.")
            if fmt == "webhook" and not re.match(r"(?i)^https://(?:(?:canary|ptb)\.)?discord(?:app)?\.com/api/(?:v\d+/)?webhooks/\d+/[a-z0-9_-]+$", value):
                raise ValueError("Enter a Discord webhook URL.")
            if fmt == "userId" and not re.match(r"^\d{15,22}$", value):
                raise ValueError("Enter a Discord user ID.")
            if fmt == "waves" and (not re.match(r"^\d{1,6}$", value) or int(value) < 1):
                raise ValueError("Leave wave must be a positive number, or blank.")
        return value

    @classmethod
    def validate(cls, mode, raw):
        if not isinstance(raw, dict):
            raise ValueError("Invalid macro settings.")
        clean = {}
        for field in cls.fields(mode):
            key = field["key"]
            if key not in raw:
                raise ValueError("Missing " + field["label"] + ".")
            clean[key] = cls.check(field, raw[key])
        if mode == "general":
            if clean["WebhookE"] and clean["WebhookURL"] == "":
                raise ValueError("Enter a webhook URL before enabling webhooks.")
            if clean["PingE"] and clean["UserID"] == "":
                raise ValueError("Enter a Discord user ID before enabling pings.")
        return clean

    @classmethod
    def load(cls, mode):
        values, warnings = {}, []
        for field in cls.fields(mode):
            try:
                values[field["key"]] = cls.check(field, Registry.read(field["key"], field["default"]))
            except Exception:
                values[field["key"]] = field["default"]
                warnings.append(field["label"] + " has an invalid saved value. Review and save these settings.")
        return {"values": values, "warnings": warnings}

    @classmethod
    def save(cls, mode, values):
        if cls.busy_state() in ("running", "paused", "initializing", "starting"):
            raise RuntimeError("Stop the macro before changing its settings.")
        values = cls.validate(mode, values)
        Registry.write(values, "run-" + mode)
        return {"values": values}

    @staticmethod
    def webhook_target(url):
        clean = url.strip(" \t")
        if "with_components=true" in clean:
            return clean
        if "?" not in clean:
            return clean + "?with_components=true"
        if clean.endswith("?") or clean.endswith("&"):
            return clean + "with_components=true"
        return clean + "&with_components=true"

    @staticmethod
    def normalize_event(event):
        for name in ("Completed", "Loss", "Disconnect", "Reconnect", "Stopping", "Shop"):
            if name.lower() == str(event).lower():
                return name
        return event

    @classmethod
    def event_title(cls, event):
        titles = {"Completed": "Stage Completed", "Disconnect": "Disconnected", "Loss": "Stage Lost", "Reconnect": "Reconnected",
                  "Shop": "Shop", "Stopping": "Dungeon Entry Failed"}
        return titles.get(cls.normalize_event(event), event)

    @staticmethod
    def build_payload(title, description="", ping=False, user_id="", server_url=""):
        content = title
        if description != "":
            content += ("" if content == "" else "\n\n") + description
        has_ping = bool(ping and user_id != "")
        if has_ping:
            content += ("" if content == "" else "\n\n") + "<@" + user_id + ">"
        if content == "":
            content = "Pantheon Notification"
        if len(content) > 4000:
            content = content[:3997] + "..."
        buttons = [{"label": "GitHub Repository", "style": 5, "type": 2, "url": "https://github.com/" + REPOSITORY}]
        if server_url != "":
            buttons.append({"label": "Private Server", "style": 5, "type": 2, "url": server_url})
        else:
            buttons.append({"label": "Releases", "style": 5, "type": 2, "url": "https://github.com/" + REPOSITORY + "/releases"})
        container = {"components": [{"content": content, "type": 10}, {"divider": True, "spacing": 1, "type": 14},
                                    {"components": buttons, "type": 1}], "type": 17}
        return {"allowed_mentions": {"parse": [], "users": [user_id] if has_ping else []}, "components": [container], "flags": 32768}

    @classmethod
    def send_payload(cls, url, payload, throw=True):
        request = urllib.request.Request(cls.webhook_target(url), data=json.dumps(payload).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json", "User-Agent": "Pantheon"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                status = response.status
        except urllib.error.HTTPError as err:
            status = err.code
        except Exception:
            if throw:
                raise
            return False
        if status < 200 or status >= 300:
            if throw:
                raise RuntimeError("Webhook request failed (HTTP %d)." % status)
            return False
        return True

    @classmethod
    def test_webhook(cls):
        values = cls.load("general")["values"]
        if values.get("WebhookURL", "") == "":
            raise RuntimeError("Save a webhook URL first.")
        ping = values.get("PingE", 0) and values.get("UserID", "") != ""
        payload = cls.build_payload("# Pantheon Webhook Test", "Webhook test message sent from Pantheon. Discord Components V2 integration is active.",
                                    ping, values["UserID"], values.get("PServerURL", ""))
        cls.send_payload(values["WebhookURL"], payload, True)
        return {"message": "Webhook test sent."}

    @classmethod
    def dispatch(cls, event, details="", throw=False):
        event = cls.normalize_event(event)
        values = cls.load("general")["values"]
        if not values.get("WebhookE", 0) or values.get("WebhookURL", "") == "":
            return 0
        hook = "Webhook" + str(event) + "E"
        if hook in values and not values[hook]:
            return 0
        ping_key = "Ping" + str(event) + "E"
        ping = values.get("PingE", 0) and values.get("UserID", "") != "" and (values[ping_key] if ping_key in values else False)
        title = "# Pantheon: " + str(cls.event_title(event))
        if isinstance(details, dict):
            description = "\n".join("**" + str(k) + ":** " + str(v) for k, v in details.items())
        elif isinstance(details, list):
            description = "\n".join("• " + str(item) for item in details)
        elif isinstance(details, str) and details != "":
            description = details
        else:
            description = "Status update: " + str(cls.event_title(event))
        payload = cls.build_payload(title, description, ping, values["UserID"], values.get("PServerURL", ""))
        return 1 if cls.send_payload(values["WebhookURL"], payload, throw) else 0
