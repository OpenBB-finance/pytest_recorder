# IMPORT STANDARD
import json
import logging
from datetime import datetime
from pathlib import Path

# IMPORT THIRD-PARTY
import pytest
import time_machine
from _pytest.fixtures import SubRequest

# IMPORT INTERNAL
from pytest_recorder.record_type import RecordType

logger = logging.getLogger(__name__)


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "record_time(destination, *, tick): Records time or time travel to the saved time.",
    )


class TravelModel:
    @property
    def dt(self) -> datetime:
        return self._dt

    @property
    def tick(self) -> bool:
        return self._tick

    def __init__(self, dt: datetime, tick: bool) -> None:
        self._dt = dt
        self._tick = tick


class TravelHandler:
    @staticmethod
    def load_travel(record_file_path: Path) -> TravelModel:
        if record_file_path.exists():
            logger.debug("Loading record file : %s", record_file_path)
            with record_file_path.open(
                mode="r", encoding="utf-8", newline="\n"
            ) as file:
                data = json.load(file)

            if isinstance(data, dict) and "isoformat" in data and "tick" in data:
                isoformat = data["isoformat"]
                tick = data["tick"]
                dt = datetime.fromisoformat(isoformat)
                travel = TravelModel(dt=dt, tick=tick)

                return travel
            else:
                raise AttributeError(
                    f"No JSON object with`isoformat` time found : {record_file_path}",
                )
        else:
            raise AttributeError(
                f"Cannot load record file : {record_file_path}",
            )

        return dt

    @staticmethod
    def persist(
        travel: TravelModel,
        record_file_path: Path,
    ):
        logger.debug("Making record folder : %s", record_file_path.parent)
        record_file_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "isoformat": travel.dt.isoformat(),
            "tick": travel.tick,
        }
        with record_file_path.open(mode="w", encoding="utf-8", newline="\n") as file:
            logger.debug("Writing record file : %s", record_file_path)
            json.dump(data, file)


class RecordFilePathBuilder:
    @staticmethod
    def build(test_module_path: Path, test_function: str) -> Path:
        test_module = test_module_path.stem

        record_folder_name = RecordType.time.name
        record_file_folder_path = (
            test_module_path.parent / "record" / record_folder_name
        )
        record_file_name = f"{test_function}.json"
        record_file_path = record_file_folder_path / test_module / record_file_name

        return record_file_path


def record_time_context_manager(
    request: SubRequest,
):
    marker = request.node.get_closest_marker("record_time")

    if marker:
        record_no_overwrite = request.config.getoption("--record-no-overwrite")
        record_type = request.config.getoption("--record")
        test_function = request.node.name
        test_module_path = Path(request.node.fspath)  # PYTEST 6.2.2 COMPATIBILITY

        record_file_path = RecordFilePathBuilder.build(
            test_module_path=test_module_path,
            test_function=test_function,
        )

        if (RecordType.all in record_type or RecordType.time in record_type) and not (
            record_file_path.exists() and record_no_overwrite
        ):
            if len(marker.args) > 0 and isinstance(marker.args[0], datetime):
                dt = marker.args[0]
            else:
                dt = marker.kwargs.get("destination", datetime.now())

            tick = marker.kwargs.get("tick", False)
            travel = TravelModel(dt=dt, tick=tick)

            TravelHandler.persist(
                travel=travel,
                record_file_path=record_file_path,
            )
            travel_context_manager = time_machine.travel(
                destination=travel.dt,
                tick=travel.tick,
            )
        elif record_file_path.exists():
            travel = TravelHandler.load_travel(record_file_path=record_file_path)

            travel_context_manager = time_machine.travel(
                destination=travel.dt,
                tick=travel.tick,
            )
        else:
            raise AttributeError(
                f"No time to record to compare with the current result : {record_file_path}",
            )

        with travel_context_manager as traveller:
            yield traveller
    else:
        yield None


record_fixture = pytest.fixture(name="record_time", autouse=True)(
    record_time_context_manager
)
