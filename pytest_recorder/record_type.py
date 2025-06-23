# IMPORT STANDARD
from enum import Enum


class RecordType(str, Enum):
    none = "none"
    all = "all"
    curl = "curl"
    http = "http"
    object = "object"
    screen = "screen"
    time = "time"
