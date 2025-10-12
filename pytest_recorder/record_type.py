# IMPORT STANDARD
from enum import Enum


class RecordType(str, Enum):
    none = "none"
    all = "all"
    curl = "curl"
    ftp = "ftp"
    http = "http"
    object = "object"
    screen = "screen"
    time = "time"
