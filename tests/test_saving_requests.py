# IMPORT STANDARD

# IMPORT THIRD-PARTY
import pytest
import requests
from curl_adapter import CurlCffiAdapter

# IMPORT INTERNAL


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "filter_headers": [("User-Agent", None)],
        "filter_query_parameters": [("apikey", "MOCK_API_KEY")],
    }


@pytest.mark.record_http
def test_saving_requests():
    response = requests.get(
        "https://vcrpy.readthedocs.io/en/latest/configuration.html?apikey=123"
    )
    print(response.text)


@pytest.mark.record_curl
def test_saving_curl_requests():
    curl_session = requests.Session()
    curl_session.mount("https://", CurlCffiAdapter())
    response = curl_session.get(
        "https://vcrpy.readthedocs.io/en/latest/configuration.html?apikey=123"
    )
    assert response.status_code == 200
    assert "configuration" in response.text.lower()

    print(response.text)
