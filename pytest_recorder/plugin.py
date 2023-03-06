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
        "--record-without-hash",
        action="store_true",
        default=False,
        help="Forces the following feature to save the full records and not only the hash : record_screen, recorder.",
    )
    group.addoption(
        "--record-add-only",
        action="store_true",
        default=False,
        help="Only saves the current record if there is no existing records.",
    )
