
DOMAIN = "binary_sensor"

class BinarySensorEntity:
    @property
    def state(self):
        on = self.is_on
        return None if on is None else ("on" if on else "off")
