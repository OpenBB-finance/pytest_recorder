# IMPORT STANDARD
import datetime as dt
import time
from zoneinfo import ZoneInfo

# IMPORT THIRD-PARTY
import pytest

# IMPORT INTERNAL


hill_valley_tz = ZoneInfo("America/Los_Angeles")


@pytest.mark.record_time(
    destination=dt.datetime(
        year=1985, month=10, day=26, hour=1, minute=24, tzinfo=hill_valley_tz
    ),
    tick=False,
)
def test_save_delorean_time():
    assert dt.date.today().isoformat() == "1985-10-26"


@pytest.mark.record_time(tick=False)
def test_save_current_time():
    print("\n", dt.datetime.now())
    time.sleep(2)
    print("\n", dt.datetime.now())
