class Desktop:
    clipboard = staticmethod(lambda text: None)
    open_file = staticmethod(lambda title, filters: "")
    save_file = staticmethod(lambda name, title, filters: "")
    confirm = staticmethod(lambda text, title: False)
    open_uri = staticmethod(lambda uri: None)
    report = staticmethod(lambda text: None)
    pick = staticmethod(lambda client, frame, point: None)
    viewer = staticmethod(lambda enabled: None)
