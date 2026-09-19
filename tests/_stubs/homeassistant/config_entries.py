
CONN_CLASS_LOCAL_PUSH = "local_push"

class ConfigEntry:
    def __init__(self, entry_id="entry1", data=None):
        self.entry_id = entry_id
        self.data = data or {}

class ConfigFlow:
    def __init_subclass__(cls, **kw):
        pass
