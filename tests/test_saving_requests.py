# IMPORT STANDARD

# IMPORT THIRD-PARTY
import pytest
import requests

# IMPORT INTERNAL

@pytest.fixture(scope="module")
def vcr_config():
    return {
        "filter_headers": [("User-Agent", None)],
        "filter_query_parameters": [("apikey", "MOCK_API_KEY")],
    }

@pytest.mark.record_http
def test_saving_requests():
    response = requests.get("https://vcrpy.readthedocs.io/en/latest/configuration.html?apikey=123")
    print(response.text)
