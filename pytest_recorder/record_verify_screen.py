# IMPORT STANDARD
import json
import logging
from hashlib import sha256
from pathlib import Path

# IMPORT THIRD-PARTY
import pytest
from _pytest.capture import CaptureResult, MultiCapture, SysCapture
from _pytest.fixtures import SubRequest

# IMPORT INTERNAL
from pytest_recorder.record_type import RecordType

logger = logging.getLogger(__name__)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "record_verify_screen: record the text output on the screen and compare it on next run.",
    )


class CaptureResultHandler:
    @staticmethod
    def hash_output(capture_result: CaptureResult) -> CaptureResult:
        out = capture_result.out
        out_hash = sha256(out.encode()).hexdigest()
        err = capture_result.err
        capture_result_hash = CaptureResult(out=out_hash, err=err)

        return capture_result_hash

    @staticmethod
    def load_capture_result(record_file_path: Path) -> CaptureResult:
        if record_file_path.exists():
            logger.debug("Loading record file : %s", record_file_path)
            with record_file_path.open(
                mode="r", encoding="utf-8", newline="\n"
            ) as file:
                data = json.load(file)

            if isinstance(data, dict):
                out = data.get("out", "")
                err = data.get("err", "")
                capture_result = CaptureResult(out=out, err=err)
            else:
                out = ""
                err = ""
                capture_result = CaptureResult(out=out, err=err)
        else:
            raise AttributeError(
                f"Cannot load record file : {record_file_path}",
            )

        return capture_result

    @staticmethod
    def persist(
        capture_result: CaptureResult,
        record_file_path: Path,
    ):
        logger.debug("Making record folder : %s", record_file_path.parent)
        record_file_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "out": capture_result.out,
            "err": capture_result.err,
        }
        with record_file_path.open(mode="w", encoding="utf-8", newline="\n") as file:
            logger.debug("Writing record file : %s", record_file_path)
            json.dump(data, file)

    @staticmethod
    def verify(
        capture_result: CaptureResult,
        capture_result_loaded: CaptureResult,
        record_file_path: Path,
    ):
        if capture_result.out != capture_result_loaded.out:
            raise AttributeError(
                "Recorded screen output doesn't match current screen output:\n"
                f"\nRECORD_FILE_PATH =\n{record_file_path}\n"
                f"\nCURRENT = {capture_result.out}\n"
                f"\nLOADED  = {capture_result_loaded.out}\n"
            )


class RecordFilePathBuilder:
    @staticmethod
    def build(test_module_path: Path, test_function: str) -> Path:
        test_module = test_module_path.stem

        record_folder_name = RecordType.screen.name
        record_file_folder_path = (
            test_module_path.parent / "record" / record_folder_name
        )
        record_file_name = f"{test_function}.json"
        record_file_path = record_file_folder_path / test_module / record_file_name

        return record_file_path


def record_screen_context_manager(
    request: SubRequest,
):
    marker = request.node.get_closest_marker("record_verify_screen")

    if marker:
        capture = request.config.getoption("--capture")
        record_no_hash = request.config.getoption("--record-no-hash")
        record_no_overwrite = request.config.getoption("--record-no-overwrite")
        record_type = request.config.getoption("--record")
        test_function = request.node.name
        test_module_path = Path(request.node.fspath)  # PYTEST 6.2.2 COMPATIBILITY

        record_file_path = RecordFilePathBuilder.build(
            test_module_path=test_module_path,
            test_function=test_function,
        )

        if capture == "no":
            global_capturing = MultiCapture(
                in_=SysCapture(0),
                out=SysCapture(1),
                err=SysCapture(2),
            )
            global_capturing.start_capturing()
            yield None
            capture_result = global_capturing.readouterr()
            global_capturing.stop_capturing()
        else:
            capsys = request.getfixturevalue("capsys")
            yield None
            capture_result = capsys.readouterr()

        if not record_no_hash:
            capture_result = CaptureResultHandler.hash_output(
                capture_result=capture_result
            )

        if (RecordType.all in record_type or RecordType.screen in record_type) and not (
            record_file_path.exists() and record_no_overwrite
        ):
            print("persist", capture_result)
            CaptureResultHandler.persist(
                capture_result=capture_result,
                record_file_path=record_file_path,
            )
        elif record_file_path.exists():
            capture_result_loaded = CaptureResultHandler.load_capture_result(
                record_file_path=record_file_path
            )
            CaptureResultHandler.verify(
                capture_result=capture_result,
                capture_result_loaded=capture_result_loaded,
                record_file_path=record_file_path,
            )
        else:
            raise AttributeError(
                f"No screen output recording to compare with the current result : {record_file_path}",
            )

    else:
        yield None


record_fixture = pytest.fixture(name="record_verify_screen", autouse=True)(
    record_screen_context_manager
)
