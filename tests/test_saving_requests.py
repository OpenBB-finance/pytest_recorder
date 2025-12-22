"""Tests for saving HTTP requests using different curl libraries with VCR.py."""

import pytest
import requests

# pylint: disable=I1101

# Try importing optional curl libraries
try:
    import curl_cffi.requests

    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

try:
    from curl_cffi.requests import AsyncSession

    HAS_ASYNC_SESSION = True
except ImportError:
    HAS_ASYNC_SESSION = False

try:
    import pycurl
    from io import BytesIO

    HAS_PYCURL = True
except ImportError:
    HAS_PYCURL = False


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


@pytest.mark.skipif(not HAS_CURL_CFFI, reason="curl_cffi not installed")
@pytest.mark.record_curl
def test_saving_curl_cffi_session_requests():
    """Test direct curl_cffi Session usage."""
    session = curl_cffi.requests.Session()
    response = session.get(
        "https://vcrpy.readthedocs.io/en/latest/configuration.html?apikey=123"
    )
    assert response.status_code == 200
    assert "configuration" in response.text.lower()
    print(response.text)


@pytest.mark.skipif(not HAS_CURL_CFFI, reason="curl_cffi not installed")
@pytest.mark.record_curl
def test_saving_curl_cffi_module_requests():
    """Test curl_cffi module-level function usage."""
    response = curl_cffi.requests.get(
        "https://vcrpy.readthedocs.io/en/latest/configuration.html?apikey=123"
    )
    assert response.status_code == 200
    assert "configuration" in response.text.lower()
    print(response.text)


@pytest.mark.skipif(
    not HAS_ASYNC_SESSION, reason="curl_cffi AsyncSession not available"
)
@pytest.mark.asyncio
@pytest.mark.record_curl
async def test_saving_curl_cffi_async_requests():
    """Test curl_cffi AsyncSession usage."""
    async with AsyncSession() as session:
        response = await session.get(
            "https://vcrpy.readthedocs.io/en/latest/configuration.html?apikey=123"
        )
        assert response.status_code == 200
        assert "configuration" in response.text.lower()
        print(response.text)


@pytest.mark.skipif(not HAS_PYCURL, reason="pycurl not installed")
@pytest.mark.record_curl
def test_saving_pycurl_requests():
    """Test pycurl direct usage."""
    curl = pycurl.Curl()
    buffer = BytesIO()

    curl.setopt(pycurl.URL, "https://httpbin.org/get?apikey=123")
    curl.setopt(pycurl.WRITEDATA, buffer)
    curl.perform()

    status_code = curl.getinfo(pycurl.RESPONSE_CODE)
    assert status_code == 200

    body = buffer.getvalue().decode("utf-8")
    assert "httpbin" in body.lower() or "args" in body
    print(body)

    curl.close()


@pytest.mark.skipif(
    not (HAS_CURL_CFFI and HAS_ASYNC_SESSION),
    reason="curl_cffi with async not available",
)
@pytest.mark.asyncio
@pytest.mark.record_curl
async def test_saving_mixed_curl_requests():
    """Test mixed sync and async curl_cffi in same test - unified cassette."""
    # Use sync direct
    response1 = curl_cffi.requests.get(
        "https://vcrpy.readthedocs.io/en/latest/configuration.html?apikey=123"
    )
    assert response1.status_code == 200

    # Use async direct
    async with AsyncSession() as session:
        response2 = await session.get(
            "https://vcrpy.readthedocs.io/en/latest/configuration.html?apikey=456"
        )
        assert response2.status_code == 200

    print("Mixed test completed successfully")
