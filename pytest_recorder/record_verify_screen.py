# IMPORT STANDARD
from pathlib import Path

# IMPORT THIRD-PARTY
import pytest
from _pytest.fixtures import SubRequest

# IMPORT INTERNAL
from pytest_recorder.record_type import RecordType


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "record_verify_screen: record the text output on the screen and compare it on next run.",
    )


class RecordFilePathBuilder:
    @staticmethod
    def build(test_module_path: Path, test_function: str) -> Path:
        test_module = test_module_path.stem

        cassette_folder_name = RecordType.screen.name
        cassette_file_folder_path = (
            test_module_path.parent / "record" / cassette_folder_name
        )
        cassette_file_name = f"{test_function}.json"
        cassette_file_path = (
            cassette_file_folder_path / test_module / cassette_file_name
        )

        return cassette_file_path


def record_http_context_manager(
    request: SubRequest,
):
    marker = request.node.get_closest_marker("record_screen")
    record_no_overwrite = request.config.getoption("--record-no-overwrite")
    record_type = request.config.getoption("--record")
    test_function = request.node.name
    test_module_path = Path(request.node.fspath)  # PYTEST 6.2.2 COMPATIBILITY

    record_file_path = RecordFilePathBuilder.build(
        test_module_path=test_module_path,
        test_function=test_function,
    )

    capture = request.config.getoption("--capture")

    print("record_file_path", record_file_path)
    print("marker", marker)
    print("capture", capture)

    # if (
    #     marker
    #     and (RecordType.all in record_type or RecordType.screen in record_type)
    #     and not (record_file_path.exists() and record_no_overwrite)
    # ):
    #     pass

    # elif record_file_path.exists():
    #     pass
    # else:
    #     raise AttributeError(
    #         f"No comparison possible since there is no vcr cassette : {record_file_path}",
    #     )


record_fixture = pytest.fixture(name="record_verify_screen", autouse=True)(
    record_http_context_manager
)
