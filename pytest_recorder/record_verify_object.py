# IMPORT STANDARD
import json
import logging
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any, List

# IMPORT THIRD-PARTY
import pytest
from _pytest.fixtures import SubRequest

# IMPORT INTERNAL
from pytest_recorder.record_type import RecordType

logger = logging.getLogger(__name__)


class ObjectCollector:
    @property
    def hash_only(self) -> bool:
        return self._hash_only

    @hash_only.setter
    def hash_only(self, value: bool):
        self._hash_only = value

    @property
    def object_list(self) -> List[Any]:
        return deepcopy(self._object_list)

    def add_verify(self, obj: Any, *args, **kwargs):
        if hasattr(obj, "to_dict"):
            obj = obj.to_dict(*args, **kwargs)
        self._object_list.append(obj)

    def __init__(
        self,
        object_list: List = None,
        hash_only: bool = True,
    ) -> None:
        self._hash_only = hash_only
        self._object_list = object_list or []


class ObjectCollectorHandler:
    @staticmethod
    def jsonify_record_data(record_model: ObjectCollector) -> ObjectCollector:
        object_list = record_model.object_list
        data_str_list = [json.dumps(data, sort_keys=True) for data in object_list]

        record_model = ObjectCollector(
            object_list=data_str_list,
            hash_only=True,
        )
        return record_model

    @staticmethod
    def hash_record_data(record_model: ObjectCollector) -> ObjectCollector:
        object_list = record_model.object_list
        data_str_list = [json.dumps(data, sort_keys=True) for data in object_list]
        data_hash_list = [sha256(data.encode()).hexdigest() for data in data_str_list]

        record_model = ObjectCollector(
            object_list=data_hash_list,
            hash_only=True,
        )
        return record_model

    @classmethod
    def jsonify_and_hash_record_data(
        cls, record_model: ObjectCollector
    ) -> ObjectCollector:
        object_list = record_model.object_list
        object_json_list = [json.dumps(data, sort_keys=True) for data in object_list]

        if record_model.hash_only:
            object_hash_list = [
                sha256(obj.encode()).hexdigest() for obj in object_json_list
            ]
            record_model = ObjectCollector(
                object_list=object_hash_list,
                hash_only=True,
            )
        else:
            record_model = ObjectCollector(
                object_list=object_json_list,
                hash_only=False,
            )

        return record_model

    @classmethod
    def persist(cls, record_model: ObjectCollector, record_file_path: Path):
        logger.debug("Making record folder : %s", record_file_path.parent)
        record_file_path.parent.mkdir(parents=True, exist_ok=True)

        with record_file_path.open(mode="w", encoding="utf-8", newline="\n") as file:
            logger.debug("Writing record file : %s", record_file_path)
            json.dump(record_model.object_list, file)

    @staticmethod
    def load_record_model(
        hash_only: bool,
        record_file_path: Path,
    ) -> ObjectCollector:
        if record_file_path.exists():
            logger.debug("Loading record file : %s", record_file_path)
            with record_file_path.open(
                mode="r", encoding="utf-8", newline="\n"
            ) as file:
                object_list = json.load(file)
        else:
            raise AttributeError(
                f"Cannot load record file : {record_file_path}",
            )

        record_model_loaded = ObjectCollector(
            object_list=object_list,
            hash_only=hash_only,
        )

        return record_model_loaded

    @staticmethod
    def verify(
        record_current: ObjectCollector,
        record_loaded: ObjectCollector,
        record_file_path: Path,
    ):
        current_data_list = record_current.object_list
        loaded_data_list = record_loaded.object_list
        if len(current_data_list) != len(loaded_data_list):
            raise AttributeError(
                "Record have different number of objects:\n"
                f"\nRECORD_FILE_PATH =\n{record_file_path}\n"
                f"\nCURRENT_OBJECT_LIST = {len(current_data_list)}\n"
                f"\nLOADED_OBJECT_LIST  = {len(loaded_data_list)}\n"
            )

        for index, (current, loaded) in enumerate(
            zip(current_data_list, loaded_data_list)
        ):
            if current != loaded:
                raise AttributeError(
                    "Record's data have changed.\n"
                    f"\nRECORD_FILE_PATH =\n{record_file_path}\n"
                    f"\nINDEX = {index}\n"
                    f"\nCURRENT =\n{current}\n"
                    f"\nPREVIOUS =\n{loaded}\n"
                )


class RecordFilePathBuilder:
    @staticmethod
    def build(test_module_path: Path, test_function: str, hash_only: bool) -> Path:
        test_module = test_module_path.stem
        data_folder_name = "object_hash" if hash_only else RecordType.object.name
        data_file_folder_path = test_module_path.parent / "record" / data_folder_name
        data_file_name = f"{test_function}.json"
        data_file_path = data_file_folder_path / test_module / data_file_name

        return data_file_path


def record_context_manager(
    request: SubRequest,
):
    """
    Provides an ObjectCollector.

    ObjectCollector allows collecting object.

    Once the object are collected they are:
    - Either saved in a file.
    - Either compared to the last saved objects.
    """

    record_no_overwrite = request.config.getoption("--record-no-overwrite")
    record_no_hash = request.config.getoption("--record-no-hash")
    record_type = request.config.getoption("--record")
    test_function = request.node.name
    test_module_path = Path(request.node.fspath)  # PYTEST 6.2.2 COMPATIBILITY

    record = ObjectCollector()

    yield record

    if record_no_hash:
        record.hash_only = False

    record_file_path = RecordFilePathBuilder.build(
        test_module_path=test_module_path,
        test_function=test_function,
        hash_only=record.hash_only,
    )

    record_formatted = ObjectCollectorHandler.jsonify_and_hash_record_data(
        record_model=record,
    )

    if (RecordType.all in record_type or RecordType.object in record_type) and not (
        record_file_path.exists() and record_no_overwrite
    ):
        ObjectCollectorHandler.persist(
            record_file_path=record_file_path,
            record_model=record_formatted,
        )
    elif record_file_path.exists():
        record_loaded = ObjectCollectorHandler.load_record_model(
            hash_only=record.hash_only,
            record_file_path=record_file_path,
        )

        ObjectCollectorHandler.verify(
            record_current=record_formatted,
            record_loaded=record_loaded,
            record_file_path=record_file_path,
        )
    else:
        raise AttributeError(
            f"No record to compare with the collected objects : {record_file_path}",
        )


record_fixture = pytest.fixture(name="record")(record_context_manager)
