
from enum import IntFlag, StrEnum
DOMAIN = "light"
ATTR_EFFECT = "effect"

class ColorMode(StrEnum):
    ONOFF = "onoff"

class LightEntityFeature(IntFlag):
    EFFECT = 4

class LightEntity:
    pass
