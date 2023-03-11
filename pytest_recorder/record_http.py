# IMPORT STANDARD
from pathlib import Path

# IMPORT THIRD-PARTY
import pytest
import vcr
from _pytest.fixtures import SubRequest

# IMPORT INTERNAL
from pytest_recorder.record_type import RecordType


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "record_http: record the text output on the screen and compare it on next run.",
    )


class RecordFilePathBuilder:
    @staticmethod
    def build(test_module_path: Path, test_function: str) -> Path:
        test_module = test_module_path.stem

        cassette_folder_name = RecordType.http.name
        cassette_file_folder_path = (
            test_module_path.parent / "record" / cassette_folder_name
        )
        cassette_file_name = f"{test_function}.yaml"
        cassette_file_path = (
            cassette_file_folder_path / test_module / cassette_file_name
        )

        return cassette_file_path


def record_http_context_manager(
    request: SubRequest,
):
    marker = request.node.get_closest_marker("record_http")

    if marker:
        record_no_overwrite = request.config.getoption("--record-no-overwrite")
        record_type = request.config.getoption("--record")
        test_function = request.node.name
        test_module_path = Path(request.node.fspath)  # PYTEST 6.2.2 COMPATIBILITY

        record_file_path = RecordFilePathBuilder.build(
            test_module_path=test_module_path,
            test_function=test_function,
        )

        if (RecordType.all in record_type or RecordType.http in record_type) and not (
            record_file_path.exists() and record_no_overwrite
        ):
            record_file_path.unlink(missing_ok=True)

            vcr_object = vcr.VCR(
                cassette_library_dir=str(record_file_path.parent),
                record_mode="once",
            )

            with vcr_object.use_cassette(record_file_path.name) as cassette:
                yield cassette
        elif record_file_path.exists():
            vcr_object = vcr.VCR(
                cassette_library_dir=str(record_file_path.parent),
                record_mode="none",
            )

            with vcr_object.use_cassette(record_file_path) as cassette:
                yield cassette
    else:
        yield None


record_fixture = pytest.fixture(name="record_http", autouse=True)(
    record_http_context_manager
)
