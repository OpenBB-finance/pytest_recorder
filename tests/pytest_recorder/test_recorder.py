# IMPORT STANDARD
from pathlib import Path

# IMPORT THIRD-PARTY
import pytest

# IMPORT INTERNAL
from pytest_recorder.recorder import record_fixture


def build_mock_request(
    mocker,
    test_module_path: Path,
    test_function_name: str,
    record_type: str,
    record_add_only: bool,
    record_without_hash: bool,
):
    def config_getoption(name):
        value = None
        if name == "--record":
            value = record_type
        elif name == "--record-add-only":
            return record_add_only
        elif name == "--record-without-hash":
            return record_without_hash
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
        record_add_only=False,
        record_without_hash=False,
    )

    record_fixture_generator = record_fixture(request=mock_request)
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
        record_add_only=False,
        record_without_hash=True,
    )

    record_fixture_generator = record_fixture(request=mock_request)
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
