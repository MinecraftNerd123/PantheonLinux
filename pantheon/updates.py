import json
import re
import urllib.request

from pantheon import version
from pantheon.desktop import Desktop
from pantheon.run_settings import REPOSITORY


class PantheonUpdates:
    candidate = None

    @classmethod
    def check(cls):
        cls.candidate = None
        request = urllib.request.Request("https://api.github.com/repos/" + REPOSITORY + "/releases?per_page=20",
                                         headers={"User-Agent": "Pantheon/" + version.CURRENT, "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(request, timeout=9) as response:
                status, body = response.status, response.read()
        except urllib.error.HTTPError as err:
            raise RuntimeError("GitHub could not check for updates (HTTP %d)." % err.code) from None
        except Exception:
            raise RuntimeError("The update check timed out.") from None
        if status != 200:
            raise RuntimeError("GitHub could not check for updates (HTTP %d)." % status)
        cls.candidate = cls.find_release(json.loads(body))
        return {"canInstall": 0, "version": cls.candidate or ""}

    @staticmethod
    def find_release(releases):
        best, current = None, version.CURRENT
        for release in releases:
            if release.get("draft") or (release.get("prerelease") and "-" not in current):
                continue
            tag = release.get("tag_name", "")
            if not re.match(r"^v[0-9]+\.[0-9]+(?:\.[0-9]+)?(?:-[0-9A-Za-z.-]+)?$", tag):
                continue
            candidate = tag[1:]
            try:
                if version.compare(candidate, best or current) <= 0:
                    continue
            except ValueError:
                continue
            best = candidate
        return best

    @classmethod
    def open_release_notes(cls):
        if not cls.candidate:
            raise RuntimeError("Check for an available update first.")
        Desktop.open_uri("https://github.com/" + REPOSITORY + "/releases/tag/v" + cls.candidate)
        return {"opened": 1}

    @staticmethod
    def install():
        raise RuntimeError("Update Pantheon through Flatpak: flatpak update")
