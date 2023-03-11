# IMPORT STANDARD
from pathlib import Path

# IMPORT THIRD-PARTY
import pytest

# IMPORT INTERNAL
from pytest_recorder.record_verify_object import record_context_manager


def build_mock_request(
    mocker,
    test_module_path: Path,
    test_function_name: str,
    record_type: str,
    record_no_overwrite: bool,
    record_no_hash: bool,
):
    def config_getoption(name):
        value = None
        if name == "--record":
            value = record_type
        elif name == "--record-no-overwrite":
            return record_no_overwrite
        elif name == "--record-no-hash":
            return record_no_hash
        return value

    attrs = {
        "config.getoption": config_getoption,
        "node.fspath": test_module_path,
        "node.name": test_function_name,
    }
    mock_request = mocker.Mock(**attrs)

    return mock_request


def test_record_fixture_persist_with_hash(mocker, tmp_path):
    mock_request = build_mock_request(
        mocker=mocker,
        test_module_path=tmp_path / "mock_test_module.py",
        test_function_name="mock_test_function",
        record_type="all",
        record_no_overwrite=False,
        record_no_hash=False,
    )

    record_fixture_generator = record_context_manager(request=mock_request)
    record = next(record_fixture_generator)

    record.add_verify(True)
    record.add_verify(1)
    record.add_verify("Some str")
    record.add_verify(["Some", "list"])
    record.add_verify({"Some": "dict"})

    with pytest.raises(StopIteration):
        next(record_fixture_generator)

    record_path = (
        tmp_path
        / "record"
        / "object_hash"
        / "mock_test_module"
        / "mock_test_function.json"
    )

    assert record_path.exists()


def test_record_fixture_persist_no_hash(mocker, tmp_path):
    mock_request = build_mock_request(
        mocker=mocker,
        test_module_path=tmp_path / "mock_test_module.py",
        test_function_name="mock_test_function",
        record_type="all",
        record_no_overwrite=False,
        record_no_hash=True,
    )

    record_fixture_generator = record_context_manager(request=mock_request)
    record = next(record_fixture_generator)

    record.add_verify(True)
    record.add_verify(1)
    record.add_verify("Some str")
    record.add_verify(["Some", "list"])
    record.add_verify({"Some": "dict"})

    with pytest.raises(StopIteration):
        next(record_fixture_generator)

    record_path = (
        tmp_path / "record" / "object" / "mock_test_module" / "mock_test_function.json"
    )

    assert record_path.exists()
