# IMPORT STANDARD

# IMPORT THIRD-PARTY
from _pytest.config.argparsing import Parser

# IMPORT INTERNAL
from pytest_recorder.record_type import RecordType


def pytest_addoption(parser: Parser) -> None:
    group = parser.getgroup("recorder")
    group.addoption(
        "--record",
        action="store",
        default=RecordType.none,
        choices=[item.name for item in RecordType],
        help="Records the listed elements (default: none).",
    )
    group.addoption(
        "--record-no-hash",
        action="store_true",
        default=False,
        help="Avoid hashing the content before saving the records, apply to : object and screen.",
    )
    group.addoption(
        "--record-no-overwrite",
        action="store_true",
        default=False,
        help="Avoid rewriting existing records, apply to : http, object, screen, time.",
    )
