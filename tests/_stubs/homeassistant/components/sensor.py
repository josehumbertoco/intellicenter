
from enum import StrEnum
DOMAIN = "sensor"

class SensorDeviceClass(StrEnum):
    TEMPERATURE = "temperature"
    POWER = "power"

class SensorStateClass(StrEnum):
    MEASUREMENT = "measurement"

class SensorEntity:
    _attr_device_class = None
    _attr_native_unit_of_measurement = None
    _attr_state_class = None
