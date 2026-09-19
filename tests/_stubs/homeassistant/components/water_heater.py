
from enum import IntFlag
DOMAIN = "water_heater"

class WaterHeaterEntityFeature(IntFlag):
    TARGET_TEMPERATURE = 1
    OPERATION_MODE = 2

class WaterHeaterEntity:
    pass
