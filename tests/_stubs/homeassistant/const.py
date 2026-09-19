
from enum import StrEnum

CONF_HOST = "host"
CONF_NAME = "name"
EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"
ATTR_TEMPERATURE = "temperature"
STATE_ON = "on"
STATE_OFF = "off"
STATE_IDLE = "idle"
STATE_OPEN = "open"
STATE_CLOSED = "closed"
PERCENTAGE = "%"
CONCENTRATION_PARTS_PER_MILLION = "ppm"

class UnitOfTemperature(StrEnum):
    CELSIUS = "\u00b0C"
    FAHRENHEIT = "\u00b0F"

class UnitOfPower(StrEnum):
    WATT = "W"
