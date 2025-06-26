"""Pytest configuration and fixtures for YFinance tests."""

from pathlib import Path
from typing import Any
from unittest.mock import patch
import yaml
import pytest
import vcr
from _pytest.fixtures import SubRequest
from vcr.persisters.filesystem import FilesystemPersister, serialize
from curl_adapter import CurlCffiAdapter

from pytest_recorder.record_type import RecordType


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


class CurlCassette:
    """Cassette-like object for curl requests."""

    def __init__(self, cassette_path, record_mode="once"):
        self.cassette_path = Path(cassette_path)
        self.record_mode = record_mode
        self.captured_requests = []
        self.existing_cassette = VCRFilesystemPersister.load_cassette(cassette_path)
        self._original_send = None

    def __enter__(self):
        if self._should_record():
            self._patch_curl_adapter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._should_record() and self.captured_requests:
            cassette_data = {"interactions": self.captured_requests}
            VCRFilesystemPersister.save_cassette(
                self.cassette_path, cassette_data, yaml.safe_dump
            )

        if self._original_send:
            # Restore original send method
            CurlCffiAdapter.send = self._original_send

    def _should_record(self):
        if self.record_mode == "none":
            return False
        elif self.record_mode == "once":
            return not self.cassette_path.exists()
        elif self.record_mode == "all":
            return True
        return False

    def _patch_curl_adapter(self):
        self._original_send = CurlCffiAdapter.send

        def capture_send(self_adapter, request, *args, **kwargs):
            # Call the original send method
            response = self._original_send(self_adapter, request, *args, **kwargs)

            # Create cassette-compatible request/response pair
            cassette_entry = {
                "request": {
                    "method": request.method,
                    "uri": str(request.url),
                    "headers": dict(request.headers),
                    "body": request.body.decode() if request.body else None,
                },
                "response": {
                    "status": {
                        "code": response.status_code,
                        "message": response.reason,
                    },
                    "headers": dict(response.headers),
                    "body": {"string": response.text, "encoding": "utf-8"},
                },
            }
            self.captured_requests.append(cassette_entry)

            return response

        CurlCffiAdapter.send = capture_send


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
                if k not in ["before_record_response"]
            }

            # Create VCR object for recording
            vcr_object = vcr.VCR(
                cassette_library_dir=str(record_file_path.parent),
                record_mode="once",
                **vcr_config_clean,
            )
            vcr_object.register_persister(VCRFilesystemPersister)

            # Patch CurlCffiAdapter to capture requests
            captured_requests = []
            original_send = CurlCffiAdapter.send

            def capture_send(self_adapter, request, *args, **kwargs):
                response = original_send(self_adapter, request, *args, **kwargs)

                cassette_entry = {
                    "request": {
                        "method": request.method,
                        "uri": str(request.url),
                        "headers": dict(request.headers),
                        "body": request.body if request.body else None,
                    },
                    "response": {
                        "status": {
                            "code": response.status_code,
                            "message": response.reason,
                        },
                        "headers": dict(response.headers),
                        "body": {
                            "string": (
                                response.content
                                if response.status_code == 200
                                else None
                            ),
                            "encoding": "utf-8",
                        },
                    },
                }
                if cassette_entry["response"]["status"]["code"] == 200:
                    # Apply VCR config filters
                    cassette_entry = apply_vcr_filters(cassette_entry, vcr_config)

                    # Only add to captured_requests if the filter didn't return None
                    if cassette_entry is not None:
                        captured_requests.append(cassette_entry)
                return response

            with patch.object(CurlCffiAdapter, "send", capture_send):
                with vcr_object.use_cassette(record_file_path.name) as cassette:
                    yield cassette

            # Save the captured curl requests separately
            if captured_requests:
                cassette_data = {"interactions": captured_requests}
                record_file_path.parent.mkdir(parents=True, exist_ok=True)
                with record_file_path.open("w", encoding="utf-8") as f:
                    yaml.dump(cassette_data, f, default_flow_style=False)

        elif record_file_path.exists():
            # Use existing cassette
            vcr_object = vcr.VCR(
                cassette_library_dir=str(record_file_path.parent),
                record_mode="none",
                **vcr_config,
            )
            vcr_object.register_persister(VCRFilesystemPersister)

            with vcr_object.use_cassette(record_file_path.name) as cassette:
                yield cassette
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
