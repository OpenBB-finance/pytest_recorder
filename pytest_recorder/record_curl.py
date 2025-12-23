"""Pytest configuration and fixtures for YFinance tests."""

from pathlib import Path
from typing import Any
from io import BytesIO
import yaml
import pytest
import vcr
from _pytest.fixtures import SubRequest
from vcr.persisters.filesystem import FilesystemPersister, serialize

from pytest_recorder.record_type import RecordType

# Try importing all CURL libraries with fallback
HAS_CURL_CFFI_SYNC = False
HAS_CURL_CFFI_ASYNC = False
HAS_PYCURL = False

try:
    import curl_cffi.requests  # noqa: F401
    from curl_cffi.requests import Session as CurlCffiSession

    HAS_CURL_CFFI_SYNC = True
except ImportError:
    CurlCffiSession = None  # type: ignore

try:
    from curl_cffi.requests import AsyncSession as CurlCffiAsyncSession

    HAS_CURL_CFFI_ASYNC = True
except ImportError:
    CurlCffiAsyncSession = None  # type: ignore

try:
    import pycurl  # noqa: F401

    HAS_PYCURL = True
except ImportError:
    pycurl = None  # type: ignore


@pytest.fixture(name="vcr_config")
def vcr_config_fixture() -> dict[str, Any]:
    return {}


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "record_curl: Records HTTP request or the last recorded requests.",
    )


class VCRFilesystemPersister(FilesystemPersister):
    """Persister for curl cassettes."""

    @staticmethod
    def save_cassette(cassette_path, cassette_dict, serializer):
        data = serialize(cassette_dict, serializer)
        cassette_path = Path(cassette_path).resolve()
        cassette_path.parent.mkdir(parents=True, exist_ok=True)

        with cassette_path.open("w", encoding="utf-8", newline="\n") as f:
            f.write(data)


class CurlRecordFilePathBuilder:
    """Builds file paths for curl recordings."""

    @staticmethod
    def build(test_module_path: Path, test_function: str) -> Path:
        test_module = test_module_path.stem

        record_folder_name = RecordType.curl.name
        record_file_folder_path = (
            test_module_path.parent / "record" / record_folder_name
        )
        record_file_name = f"{test_function}_curl.yaml"
        record_file_path = record_file_folder_path / test_module / record_file_name

        return record_file_path


class PycurlWrapper:
    """Wrapper for pycurl.Curl that tracks requests for recording."""

    def __init__(
        self, captured_requests, original_curl_class, vcr_config, apply_vcr_filters_func
    ):
        self._captured_requests = captured_requests
        self._curl = original_curl_class()
        self._vcr_config = vcr_config
        self._apply_vcr_filters = apply_vcr_filters_func
        self._request_data = {
            "url": None,
            "method": "GET",
            "headers": {},
            "body": None,
        }
        self._response_body = BytesIO()
        self._response_headers = BytesIO()
        self._user_write_function = None
        self._user_write_data = None

    def setopt(self, option, value):
        """Track request configuration via setopt calls."""
        if HAS_PYCURL:
            # Track URL
            if option == pycurl.URL:  # type: ignore[attr-defined]
                self._request_data["url"] = value
            # Track HTTP method
            elif option == pycurl.CUSTOMREQUEST:  # type: ignore[attr-defined]
                self._request_data["method"] = value
            # Track headers (format: ["Key: Value"])
            elif option == pycurl.HTTPHEADER:  # type: ignore[attr-defined]
                for header in value:
                    if ":" in header:
                        key, val = header.split(":", 1)
                        self._request_data["headers"][key.strip()] = val.strip()
            # Track POST data
            elif option == pycurl.POSTFIELDS:  # type: ignore[attr-defined]
                self._request_data["body"] = value
                if self._request_data["method"] == "GET":
                    self._request_data["method"] = "POST"
            # Track user's write callbacks
            elif option == pycurl.WRITEFUNCTION:  # type: ignore[attr-defined]
                self._user_write_function = value
            elif option == pycurl.WRITEDATA:  # type: ignore[attr-defined]
                self._user_write_data = value

        return self._curl.setopt(option, value)

    def perform(self):
        """Execute request and capture response."""
        if HAS_PYCURL:
            # Always chain to capture response body
            if self._user_write_function:
                # Chain user's callback function
                def chained_write_func(data):
                    self._response_body.write(data)
                    return self._user_write_function(data)  # type: ignore[attr-defined]

                self._curl.setopt(pycurl.WRITEFUNCTION, chained_write_func)  # type: ignore[attr-defined]
            elif self._user_write_data:
                # Chain user's write data buffer
                def chained_write_data(data):
                    self._response_body.write(data)
                    return self._user_write_data.write(data)

                self._curl.setopt(pycurl.WRITEFUNCTION, chained_write_data)  # type: ignore[attr-defined]
            else:
                # No user callback, use our buffer
                self._curl.setopt(pycurl.WRITEDATA, self._response_body)  # type: ignore[attr-defined]

            # Capture headers
            self._curl.setopt(
                pycurl.HEADERFUNCTION, lambda x: self._response_headers.write(x)  # type: ignore[attr-defined]
            )

        # Perform the actual request
        result = self._curl.perform()

        if HAS_PYCURL:
            # Extract response data
            status_code = self._curl.getinfo(pycurl.RESPONSE_CODE)  # type: ignore[attr-defined]

            # Parse headers from raw HTTP format
            headers_raw = self._response_headers.getvalue().decode(
                "utf-8", errors="ignore"
            )
            headers = {}
            for line in headers_raw.split("\r\n"):
                if ":" in line:
                    key, val = line.split(":", 1)
                    headers[key.strip()] = val.strip()

            # Build cassette entry
            cassette_entry = {
                "request": {
                    "method": self._request_data["method"],
                    "uri": self._request_data["url"],
                    "headers": self._request_data["headers"],
                    "body": self._request_data["body"],
                },
                "response": {
                    "status": {
                        "code": int(status_code),
                        "message": "OK" if status_code == 200 else "Error",
                    },
                    "headers": headers,
                    "body": {
                        "string": self._response_body.getvalue(),
                        "encoding": "utf-8",
                    },
                },
                "source_type": "pycurl",
            }

            # Apply filters only for 200 responses
            if int(status_code) == 200:
                cassette_entry = self._apply_vcr_filters(
                    cassette_entry, self._vcr_config
                )
                if cassette_entry is not None:
                    self._captured_requests.append(cassette_entry)

        return result

    def getinfo(self, option):
        """Pass through getinfo calls."""
        return self._curl.getinfo(option)

    def close(self):
        """Pass through close calls."""
        return self._curl.close()

    def reset(self):
        """Reset tracked state."""
        self._request_data = {
            "url": None,
            "method": "GET",
            "headers": {},
            "body": None,
        }
        self._response_body = BytesIO()
        self._response_headers = BytesIO()
        return self._curl.reset()

    def __getattr__(self, name):
        """Pass through all other attributes to the wrapped curl object."""
        return getattr(self._curl, name)


# pylint: disable=R0915
def record_curl_context_manager(
    request: SubRequest,
    vcr_config: dict[str, Any],
):
    """Context manager for curl recording."""
    marker = request.node.get_closest_marker("record_curl")

    if marker:
        record_no_overwrite = request.config.getoption(
            "--record-no-overwrite", default=False
        )
        record_type = request.config.getoption("--record", default="none")
        test_function = request.node.name
        test_module_path = Path(request.node.fspath)

        record_file_path = CurlRecordFilePathBuilder.build(
            test_module_path=test_module_path,
            test_function=test_function,
        )

        def normalize_cassette_entry(source_type, request_data, response_data):
            """Normalize request/response data from different sources to unified cassette format."""
            # Normalize request
            if source_type in [
                "curl_cffi_sync",
                "curl_cffi_async",
                "curl_cffi_module",
            ]:
                # Direct curl_cffi uses kwargs
                request_entry = {
                    "method": request_data.get("method", "GET"),
                    "uri": str(request_data.get("url", "")),
                    "headers": dict(request_data.get("headers", {})),
                    "body": request_data.get("data")
                    or request_data.get("json")
                    or request_data.get("content"),
                }
            elif source_type == "pycurl":
                # pycurl uses tracked state dict
                request_entry = {
                    "method": request_data.get("method", "GET"),
                    "uri": request_data.get("url", ""),
                    "headers": request_data.get("headers", {}),
                    "body": request_data.get("body"),
                }
            else:
                request_entry = {}

            # Normalize response
            if hasattr(response_data, "status_code"):
                # Response object (curl_cffi)
                response_entry = {
                    "status": {
                        "code": response_data.status_code,
                        "message": getattr(response_data, "reason", "OK"),
                    },
                    "headers": dict(response_data.headers),
                    "body": {
                        "string": (
                            response_data.content
                            if response_data.status_code == 200
                            else None
                        ),
                        "encoding": "utf-8",
                    },
                }
            else:
                # Dict format (pycurl or pre-built)
                response_entry = response_data

            return {
                "request": request_entry,
                "response": response_entry,
                "source_type": source_type,
            }

        def apply_vcr_filters(cassette_entry, vcr_config):
            """Apply VCR config filters to cassette entry."""
            # Filter headers
            if "filter_headers" in vcr_config:
                for header_name, replacement in vcr_config["filter_headers"]:
                    if header_name in cassette_entry["request"]["headers"]:
                        if replacement is None:
                            del cassette_entry["request"]["headers"][header_name]
                        else:
                            cassette_entry["request"]["headers"][
                                header_name
                            ] = replacement
                    if header_name in cassette_entry["response"]["headers"]:
                        if replacement is None:
                            del cassette_entry["response"]["headers"][header_name]
                        else:
                            cassette_entry["response"]["headers"][
                                header_name
                            ] = replacement

            # Filter query parameters
            if "filter_query_parameters" in vcr_config:
                # pylint: disable=import-outside-toplevel
                from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

                parsed_url = urlparse(cassette_entry["request"]["uri"])
                query_params = parse_qs(parsed_url.query)

                for param_name, replacement in vcr_config["filter_query_parameters"]:
                    if param_name in query_params:
                        query_params[param_name] = [replacement]

                # Rebuild URL with filtered parameters
                new_query = urlencode(query_params, doseq=True)
                new_parsed = parsed_url._replace(query=new_query)
                cassette_entry["request"]["uri"] = urlunparse(new_parsed)

            # Handle before_record_response function
            if "before_record_response" in vcr_config:
                for filter_func in vcr_config["before_record_response"]:
                    filtered_response = filter_func(cassette_entry["response"])

                    # If filter returns None, don't record this request at all
                    if filtered_response is None:
                        return None  # Don't record this request

                    # Apply the filtered response back to the cassette entry
                    cassette_entry["response"] = filtered_response

            return cassette_entry

        # Determine if we should record and create VCR object
        if (RecordType.all in record_type or RecordType.curl in record_type) and not (
            record_file_path.exists() and record_no_overwrite
        ):
            record_file_path.unlink(missing_ok=True)

            # Create VCR config without custom filters that VCR doesn't recognize
            vcr_config_clean = {
                k: v
                for k, v in vcr_config.items()
                if k not in ["before_record_response", "allow_playback_repeats"]
            }

            # Create VCR object for recording
            vcr_object = vcr.VCR(
                cassette_library_dir=str(record_file_path.parent),
                record_mode="once",  # type: ignore[attr-defined]
                **vcr_config_clean,
            )
            vcr_object.register_persister(VCRFilesystemPersister)

            # Unified captured_requests list for all CURL sources
            captured_requests = []

            # Save originals
            originals = {}
            if HAS_CURL_CFFI_SYNC:
                originals["session_request"] = CurlCffiSession.request  # type: ignore[attr-defined]
                # Module-level functions
                originals["module_request"] = curl_cffi.requests.request
                originals["module_get"] = curl_cffi.requests.get
                originals["module_post"] = curl_cffi.requests.post
                originals["module_put"] = curl_cffi.requests.put
                originals["module_delete"] = curl_cffi.requests.delete
                originals["module_head"] = curl_cffi.requests.head
                originals["module_options"] = curl_cffi.requests.options
                originals["module_patch"] = curl_cffi.requests.patch
            if HAS_CURL_CFFI_ASYNC:
                originals["async_session_request"] = CurlCffiAsyncSession.request  # type: ignore[attr-defined]
            if HAS_PYCURL:
                originals["pycurl_curl"] = pycurl.Curl  # type: ignore[attr-defined]

            # Patch 1: curl_cffi.requests.Session
            def capture_session_request(self, method, url, **kwargs):
                response = originals["session_request"](self, method, url, **kwargs)
                request_data = {"method": method, "url": url, **kwargs}
                cassette_entry = normalize_cassette_entry(
                    "curl_cffi_sync", request_data, response
                )

                if cassette_entry["response"]["status"]["code"] == 200:
                    cassette_entry = apply_vcr_filters(cassette_entry, vcr_config)
                    if cassette_entry is not None:
                        captured_requests.append(cassette_entry)
                return response

            # Patch 2: curl_cffi.requests.AsyncSession (async-aware)
            async def capture_async_session_request(self, method, url, **kwargs):
                response = await originals["async_session_request"](
                    self, method, url, **kwargs
                )
                request_data = {"method": method, "url": url, **kwargs}
                cassette_entry = normalize_cassette_entry(
                    "curl_cffi_async", request_data, response
                )

                if cassette_entry["response"]["status"]["code"] == 200:
                    cassette_entry = apply_vcr_filters(cassette_entry, vcr_config)
                    if cassette_entry is not None:
                        captured_requests.append(cassette_entry)
                return response

            # Patch 4: curl_cffi module-level functions
            def create_module_wrapper(original_func, method_name):
                def wrapper(url, **kwargs):
                    response = original_func(url, **kwargs)
                    request_data = {"method": method_name.upper(), "url": url, **kwargs}
                    cassette_entry = normalize_cassette_entry(
                        "curl_cffi_module", request_data, response
                    )

                    if cassette_entry["response"]["status"]["code"] == 200:
                        cassette_entry = apply_vcr_filters(cassette_entry, vcr_config)
                        if cassette_entry is not None:
                            captured_requests.append(cassette_entry)
                    return response

                return wrapper

            def create_module_request_wrapper(original_func):
                def wrapper(method, url, **kwargs):
                    response = original_func(method, url, **kwargs)
                    request_data = {"method": method, "url": url, **kwargs}
                    cassette_entry = normalize_cassette_entry(
                        "curl_cffi_module", request_data, response
                    )

                    if cassette_entry["response"]["status"]["code"] == 200:
                        cassette_entry = apply_vcr_filters(cassette_entry, vcr_config)
                        if cassette_entry is not None:
                            captured_requests.append(cassette_entry)
                    return response

                return wrapper

            # Patch 3: pycurl.Curl constructor wrapper
            def pycurl_curl_wrapper():
                return PycurlWrapper(
                    captured_requests,
                    originals["pycurl_curl"],
                    vcr_config,
                    apply_vcr_filters,
                )

            # Apply all patches
            try:
                if HAS_CURL_CFFI_SYNC:
                    CurlCffiSession.request = capture_session_request  # type: ignore[attr-defined]
                    curl_cffi.requests.request = create_module_request_wrapper(
                        originals["module_request"]
                    )
                    curl_cffi.requests.get = create_module_wrapper(
                        originals["module_get"], "get"
                    )
                    curl_cffi.requests.post = create_module_wrapper(
                        originals["module_post"], "post"
                    )
                    curl_cffi.requests.put = create_module_wrapper(
                        originals["module_put"], "put"
                    )
                    curl_cffi.requests.delete = create_module_wrapper(
                        originals["module_delete"], "delete"
                    )
                    curl_cffi.requests.head = create_module_wrapper(
                        originals["module_head"], "head"
                    )
                    curl_cffi.requests.options = create_module_wrapper(
                        originals["module_options"], "options"
                    )
                    curl_cffi.requests.patch = create_module_wrapper(
                        originals["module_patch"], "patch"
                    )
                if HAS_CURL_CFFI_ASYNC:
                    CurlCffiAsyncSession.request = capture_async_session_request  # type: ignore[attr-defined]
                if HAS_PYCURL:
                    pycurl.Curl = pycurl_curl_wrapper  # type: ignore[attr-defined]

                # Run test with all patches active
                with vcr_object.use_cassette(record_file_path.name) as cassette:  # type: ignore[attr-defined]
                    yield cassette

                # Save the captured curl requests separately (after test completes)
                if captured_requests:
                    cassette_data = {"interactions": captured_requests}
                    record_file_path.parent.mkdir(parents=True, exist_ok=True)
                    with record_file_path.open("w", encoding="utf-8") as f:
                        yaml.dump(cassette_data, f, default_flow_style=False)

            finally:
                # Restore all originals

                if HAS_CURL_CFFI_SYNC:
                    CurlCffiSession.request = originals["session_request"]  # type: ignore[attr-defined]
                    curl_cffi.requests.request = originals["module_request"]
                    curl_cffi.requests.get = originals["module_get"]
                    curl_cffi.requests.post = originals["module_post"]
                    curl_cffi.requests.put = originals["module_put"]
                    curl_cffi.requests.delete = originals["module_delete"]
                    curl_cffi.requests.head = originals["module_head"]
                    curl_cffi.requests.options = originals["module_options"]
                    curl_cffi.requests.patch = originals["module_patch"]
                if HAS_CURL_CFFI_ASYNC:
                    CurlCffiAsyncSession.request = originals["async_session_request"]  # type: ignore[attr-defined]
                if HAS_PYCURL:
                    pycurl.Curl = originals["pycurl_curl"]  # type: ignore[attr-defined]

        elif record_file_path.exists():
            # Playback mode: Use existing cassette
            # Load the cassette data directly
            with open(record_file_path, "r") as f:
                cassette_data = yaml.safe_load(f)
            interactions = cassette_data.get("interactions", [])

            # Check if playback repeats are allowed (interactions can be reused)
            allow_playback_repeats = vcr_config.get("allow_playback_repeats", False)

            # Track used interactions to handle multiple requests to same URL
            used_interactions = []

            def find_matching_interaction(url):
                """Find an interaction matching the given URL."""
                # Try to find a matching interaction (unused first, then any if repeats allowed)
                for i, interaction in enumerate(interactions):
                    if interaction["request"]["uri"] == url:
                        if i not in used_interactions:
                            used_interactions.append(i)
                            return interaction
                        elif allow_playback_repeats:
                            # Allow reusing this interaction
                            return interaction

                # If no exact match found, try matching without query parameters
                from urllib.parse import urlparse

                parsed_url = urlparse(url)
                base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"

                for i, interaction in enumerate(interactions):
                    interaction_url = interaction["request"]["uri"]
                    parsed_interaction = urlparse(interaction_url)
                    interaction_base = f"{parsed_interaction.scheme}://{parsed_interaction.netloc}{parsed_interaction.path}"
                    if base_url == interaction_base:
                        if i not in used_interactions:
                            used_interactions.append(i)
                            return interaction
                        elif allow_playback_repeats:
                            # Allow reusing this interaction
                            return interaction

                # Last resort: return first unused interaction, or any if repeats allowed
                for i, interaction in enumerate(interactions):
                    if i not in used_interactions:
                        used_interactions.append(i)
                        return interaction

                # If repeats allowed and we have interactions, return the first one
                if allow_playback_repeats and interactions:
                    return interactions[0]

                raise RuntimeError(
                    f"Cassette {record_file_path.name} has no more unused interactions. "
                    f"Total interactions: {len(interactions)}, all have been used."
                )

            # Save originals for restoration
            originals = {}
            if HAS_CURL_CFFI_SYNC:
                originals["session_request"] = CurlCffiSession.request
                originals["module_request"] = curl_cffi.requests.request
                originals["module_get"] = curl_cffi.requests.get
                originals["module_post"] = curl_cffi.requests.post
                originals["module_put"] = curl_cffi.requests.put
                originals["module_delete"] = curl_cffi.requests.delete
                originals["module_head"] = curl_cffi.requests.head
                originals["module_options"] = curl_cffi.requests.options
                originals["module_patch"] = curl_cffi.requests.patch
            if HAS_CURL_CFFI_ASYNC:
                originals["async_session_request"] = CurlCffiAsyncSession.request
            if HAS_PYCURL:
                originals["pycurl_curl"] = pycurl.Curl

            # Create mock response class that mimics curl_cffi.requests.Response
            class MockResponse:
                def __init__(self, interaction):
                    self.status_code = interaction["response"]["status"]["code"]
                    self.reason = interaction["response"]["status"]["message"]
                    self.headers = interaction["response"]["headers"]
                    body_data = interaction["response"]["body"]["string"]
                    self.content = body_data if isinstance(body_data, bytes) else b""
                    self.text = (
                        body_data.decode("utf-8")
                        if isinstance(body_data, bytes)
                        else ""
                    )
                    self.url = interaction["request"]["uri"]

                def raise_for_status(self):
                    """Raise an exception if the response status indicates an error."""
                    if 400 <= self.status_code < 600:
                        raise Exception(f"HTTP {self.status_code}: {self.reason}")

                def json(self):
                    """Parse response content as JSON."""
                    import json

                    return json.loads(self.text)

            # Patch curl_cffi functions to return mock responses
            def mock_session_request(self, method, url, **kwargs):
                interaction = find_matching_interaction(url)
                return MockResponse(interaction)

            async def mock_async_session_request(self, method, url, **kwargs):
                interaction = find_matching_interaction(url)
                return MockResponse(interaction)

            def create_mock_module_wrapper(http_method):
                def wrapper(url, **kwargs):
                    interaction = find_matching_interaction(url)
                    return MockResponse(interaction)

                return wrapper

            def mock_module_request(method, url, **kwargs):
                interaction = find_matching_interaction(url)
                return MockResponse(interaction)

            # Patch pycurl
            class MockPycurlCurl:
                def __init__(self):
                    self._url = None
                    self._write_data = None
                    self._interaction = None

                def setopt(self, option, value):
                    if HAS_PYCURL and option == pycurl.URL:
                        self._url = value
                    elif HAS_PYCURL and option == pycurl.WRITEDATA:
                        self._write_data = value

                def perform(self):
                    if self._url:
                        self._interaction = find_matching_interaction(self._url)
                    if self._write_data and self._interaction:
                        body = self._interaction["response"]["body"]["string"]
                        if isinstance(body, bytes):
                            self._write_data.write(body)

                def getinfo(self, info):
                    if (
                        HAS_PYCURL
                        and info == pycurl.RESPONSE_CODE
                        and self._interaction
                    ):
                        return self._interaction["response"]["status"]["code"]
                    return None

                def close(self):
                    pass

            try:
                # Apply playback patches
                if HAS_CURL_CFFI_SYNC:
                    CurlCffiSession.request = mock_session_request  # type: ignore[attr-defined]
                    curl_cffi.requests.request = mock_module_request
                    curl_cffi.requests.get = create_mock_module_wrapper("GET")
                    curl_cffi.requests.post = create_mock_module_wrapper("POST")
                    curl_cffi.requests.put = create_mock_module_wrapper("PUT")
                    curl_cffi.requests.delete = create_mock_module_wrapper("DELETE")
                    curl_cffi.requests.head = create_mock_module_wrapper("HEAD")
                    curl_cffi.requests.options = create_mock_module_wrapper("OPTIONS")
                    curl_cffi.requests.patch = create_mock_module_wrapper("PATCH")
                if HAS_CURL_CFFI_ASYNC:
                    CurlCffiAsyncSession.request = mock_async_session_request  # type: ignore[attr-defined]
                if HAS_PYCURL:
                    pycurl.Curl = MockPycurlCurl  # type: ignore[attr-defined]

                yield None  # No cassette object in playback mode

            finally:
                # Restore originals
                if HAS_CURL_CFFI_SYNC:
                    CurlCffiSession.request = originals["session_request"]  # type: ignore[attr-defined]
                    curl_cffi.requests.request = originals["module_request"]
                    curl_cffi.requests.get = originals["module_get"]
                    curl_cffi.requests.post = originals["module_post"]
                    curl_cffi.requests.put = originals["module_put"]
                    curl_cffi.requests.delete = originals["module_delete"]
                    curl_cffi.requests.head = originals["module_head"]
                    curl_cffi.requests.options = originals["module_options"]
                    curl_cffi.requests.patch = originals["module_patch"]
                if HAS_CURL_CFFI_ASYNC:
                    CurlCffiAsyncSession.request = originals["async_session_request"]  # type: ignore[attr-defined]
                if HAS_PYCURL:
                    pycurl.Curl = originals["pycurl_curl"]  # type: ignore[attr-defined]
        else:
            raise AttributeError(
                f"No comparison possible since there is no curl cassette: {record_file_path}",
            )
    else:
        yield None


# Create the fixture
record_curl_fixture = pytest.fixture(name="record_curl", autouse=True)(
    record_curl_context_manager
)
