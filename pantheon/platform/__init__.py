_HYPR = None


def hypr():
    global _HYPR
    if _HYPR is None:
        from pantheon.platform.hyprland import Hyprland
        _HYPR = Hyprland()
    return _HYPR
