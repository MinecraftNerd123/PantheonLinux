class PantheonError(Exception):
    pass


class FlowImageError(PantheonError):
    pass


class FlowStop(PantheonError):
    pass


class GameClosed(PantheonError):
    pass


class FlowLoopTimeout(PantheonError):
    def __init__(self, owner):
        super().__init__("Image loop timed out.")
        self.owner = owner


def message(err):
    if isinstance(err, KeyError):
        return "Missing definition field: " + str(err.args[0] if err.args else "")
    if isinstance(err, (TypeError, AttributeError, IndexError)):
        return "Invalid definition data."
    text = str(err)
    return text or err.__class__.__name__
