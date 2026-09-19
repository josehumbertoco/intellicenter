"""Minimal stand-in for homeassistant.helpers.entity.

Home Assistant exposes a set of properties that each default to a matching
``_attr_`` attribute, and integrations set those attributes rather than
overriding the property. The stub reproduces that convention so the integration
is exercised the same way it would be in Home Assistant.
"""

_ATTR_BACKED = (
    "available",
    "color_mode",
    "device_class",
    "entity_registry_enabled_default",
    "icon",
    "native_max_value",
    "native_min_value",
    "native_step",
    "native_unit_of_measurement",
    "should_poll",
    "state_class",
    "supported_color_modes",
    "supported_features",
)


def _attr_property(name):
    def getter(self):
        return getattr(self, f"_attr_{name}", None)

    return property(getter)


class Entity:
    hass = None

    _attr_available = True
    _attr_name = None
    _attr_should_poll = True

    def __init__(self):
        self.state_writes = 0
        self._on_remove = []

    def async_write_ha_state(self):
        # the integration builds entities without calling Entity.__init__,
        # so the counter is created on first use
        self.state_writes = getattr(self, "state_writes", 0) + 1

    def async_on_remove(self, fn):
        if not hasattr(self, "_on_remove"):
            self._on_remove = []
        self._on_remove.append(fn)

    async def async_added_to_hass(self):
        pass

    async def async_will_remove_from_hass(self):
        pass

    def remove(self):
        """Run the teardown callbacks, as Home Assistant does on removal."""
        for fn in getattr(self, "_on_remove", []):
            fn()
        self._on_remove = []


for _name in _ATTR_BACKED:
    setattr(Entity, _name, _attr_property(_name))
