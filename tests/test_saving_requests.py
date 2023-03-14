# IMPORT STANDARD

# IMPORT THIRD-PARTY
import pytest
import requests

# IMPORT INTERNAL


@pytest.mark.record_http
def test_saving_requests():
    response = requests.get("https://vcrpy.readthedocs.io/en/latest/configuration.html")
    print(response.text)
