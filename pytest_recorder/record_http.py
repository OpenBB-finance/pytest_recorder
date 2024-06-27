# IMPORT STANDARD
import urllib3
from pathlib import Path
from typing import Any, Dict

# IMPORT THIRD-PARTY
import pytest
import vcr
from _pytest.fixtures import SubRequest
from vcr.persisters.filesystem import FilesystemPersister, serialize

# IMPORT INTERNAL
from pytest_recorder.record_type import RecordType


@pytest.fixture(name="vcr_config")
def vcr_config_fixture() -> Dict[str, Any]:
    return {}


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "record_http: Records HTTP request or the last recorded requests.",
    )


class VCRFilesystemPersister(FilesystemPersister):
    @staticmethod
    def save_cassette(cassette_path, cassette_dict, serializer):
        data = serialize(cassette_dict, serializer)
        cassette_path = Path(cassette_path).resolve()
        cassette_path.parent.mkdir(parents=True, exist_ok=True)

        with cassette_path.open("w", encoding="utf-8", newline="\n") as f:
            f.write(data)


class RecordFilePathBuilder:
    @staticmethod
    def build(test_module_path: Path, test_function: str) -> Path:
        test_module = test_module_path.stem

        record_folder_name = RecordType.http.name
        record_file_folder_path = (
            test_module_path.parent / "record" / record_folder_name
        )
        urllib3_version = urllib3.__version__.split(".")[0]
        record_file_name = f"{test_function}_urllib3_v{urllib3_version}.yaml"
        record_file_path = record_file_folder_path / test_module / record_file_name

        return record_file_path


def record_http_context_manager(
    request: SubRequest,
    vcr_config: Dict[str, Any],
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
                **vcr_config,
            )
            vcr_object.register_persister(VCRFilesystemPersister)

            with vcr_object.use_cassette(record_file_path.name) as cassette:
                yield cassette
        elif record_file_path.exists():
            vcr_object = vcr.VCR(
                cassette_library_dir=str(record_file_path.parent),
                record_mode="none",
                **vcr_config,
            )
            vcr_object.register_persister(VCRFilesystemPersister)

            with vcr_object.use_cassette(record_file_path.name) as cassette:
                yield cassette
        else:
            raise AttributeError(
                f"No comparison possible since there is no vcr cassette : {record_file_path}",
            )
    else:
        yield None


record_fixture = pytest.fixture(name="record_http", autouse=True)(
    record_http_context_manager
)
