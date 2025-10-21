"""FTP recording fixture for pytest_recorder.

This module intercepts FTP protocol requests issued through
`urllib.request.urlopen('ftp://...')`, or `ftplib.FTP`, and records/replays the remote payloads
so tests can run deterministically.

Marker: `@pytest.mark.record_ftp`
Files: `tests/record/ftp/<module>/<test>_ftp.yaml` (YAML with `interactions` list)
"""

# pylint: disable=protected-access,unused-argument,try-except-raise,unused-variable
# noqa: flake8: disable=F841

from pathlib import Path
from typing import Any, Dict, Optional
import base64
import ftplib
import io
import urllib.request
from urllib.error import URLError
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from unittest.mock import patch

import yaml
import pytest
from _pytest.fixtures import SubRequest
from pytest_recorder.record_type import RecordType


@pytest.fixture(name="vcr_config")
def vcr_config_fixture() -> Dict[str, Any]:
    # Default empty vcr_config; tests can override
    return {}


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "record_ftp: Records FTP request or the last recorded requests.",
    )


class RecordFilePathBuilder:
    @staticmethod
    def build(test_module_path: Path, test_function: str) -> Path:
        test_module = test_module_path.stem

        record_folder_name = RecordType.ftp.name
        record_file_folder_path = (
            test_module_path.parent / "record" / record_folder_name
        )
        record_file_name = f"{test_function}_ftp.yaml"
        record_file_path = record_file_folder_path / test_module / record_file_name

        return record_file_path


class _FakeResponse:
    def __init__(self, data: bytes, url: Optional[str] = None):
        self._buf = io.BytesIO(data)
        self._url = url

    def read(self, amt: int = -1) -> bytes:
        return self._buf.read(amt)

    def geturl(self) -> Optional[str]:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            self._buf.close()
        except Exception:
            pass


class FTPCassette:
    def __init__(
        self,
        cassette_path: Path,
        record_mode: str = "once",
        vcr_config: Optional[Dict[str, Any]] = None,
    ):
        self.cassette_path = Path(cassette_path)
        self.record_mode = record_mode
        self.vcr_config = vcr_config or {}
        self.interactions: list[Dict[str, Any]] = []
        self._replay_index = 0
        self._patcher = None
        # keep references to original callables to allow wrapping/restoring
        self._orig_urlopen = urllib.request.urlopen
        self._originals: Dict[str, Any] = {}

    def _serialize_body(self, data: bytes) -> Dict[str, Any]:
        try:
            s = data.decode("utf-8")
            return {"encoding": "utf-8", "body": s}
        except Exception:
            return {
                "encoding": "base64",
                "body": base64.b64encode(data).decode("ascii"),
            }

    def _deserialize_body(self, entry: Dict[str, Any]) -> bytes:
        if entry.get("encoding") == "utf-8":
            return entry["body"].encode("utf-8")
        return base64.b64decode(entry["body"])

    def _apply_vcr_filters(
        self, cassette_entry: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        # Build wrapper structure used by other recorders to make filters consistent
        request_uri = cassette_entry.get("url") or cassette_entry.get(
            "request", {}
        ).get("uri")
        request_headers = (
            cassette_entry.get("request", {}).get("headers", {})
            or cassette_entry.get("headers", {})
            or {}
        )
        response_headers = (
            cassette_entry.get("response", {}).get("headers", {})
            or cassette_entry.get("headers", {})
            or {}
        )

        body_enc = cassette_entry.get("encoding")
        body_val = cassette_entry.get("body")
        response_body = {"string": body_val, "encoding": body_enc or "utf-8"}

        wrapper = {
            "request": {"uri": request_uri, "headers": dict(request_headers)},
            "response": {"body": response_body, "headers": dict(response_headers)},
        }

        # filter headers
        if "filter_headers" in self.vcr_config:
            for header_name, replacement in self.vcr_config["filter_headers"]:
                # request headers
                if header_name in wrapper["request"]["headers"]:
                    if replacement is None:
                        del wrapper["request"]["headers"][header_name]
                    else:
                        wrapper["request"]["headers"][header_name] = replacement

                # response headers
                if header_name in wrapper["response"]["headers"]:
                    if replacement is None:
                        del wrapper["response"]["headers"][header_name]
                    else:
                        wrapper["response"]["headers"][header_name] = replacement

        # Filter query parameters on the request URI
        if "filter_query_parameters" in self.vcr_config and wrapper["request"]["uri"]:
            parsed_url = (
                urlparse(wrapper["request"]["uri"])
                if wrapper["request"]["uri"]
                else None
            )
            if parsed_url:
                query_params = parse_qs(parsed_url.query)
                for param_name, replacement in self.vcr_config[
                    "filter_query_parameters"
                ]:
                    if param_name in query_params:
                        query_params[param_name] = [replacement]
                new_query = urlencode(query_params, doseq=True)
                new_parsed = parsed_url._replace(query=new_query)
                wrapper["request"]["uri"] = urlunparse(new_parsed)

        # Handle before_record_response functions
        if "before_record_response" in self.vcr_config:
            for filter_func in self.vcr_config["before_record_response"]:
                try:
                    filtered_response = filter_func(wrapper["response"])
                except Exception:
                    # Skip filters that raise
                    continue

                # None means drop this interaction
                if filtered_response is None:
                    return None

                # If filter returns a dict, replace the response
                if isinstance(filtered_response, dict):
                    # ensure structure
                    wrapper["response"] = filtered_response
                    continue

                # If it returned a string, treat it as new body text
                if isinstance(filtered_response, str):
                    wrapper["response"]["body"]["encoding"] = "utf-8"
                    wrapper["response"]["body"]["string"] = filtered_response

        # Map wrapper back to cassette_entry
        out = dict(cassette_entry)  # copy
        out["url"] = wrapper["request"]["uri"]

        resp_body = wrapper["response"]["body"]
        body_val = resp_body.get("string")
        body_enc = resp_body.get("encoding")
        if isinstance(body_val, (bytes, bytearray)):
            out["encoding"] = "base64"
            out["body"] = base64.b64encode(body_val).decode("ascii")
        else:
            out["encoding"] = body_enc or "utf-8"
            out["body"] = body_val

        # include headers back if present
        if wrapper["request"]["headers"]:
            out.setdefault("request", {})["headers"] = wrapper["request"]["headers"]
        if wrapper["response"]["headers"]:
            out.setdefault("response", {})["headers"] = wrapper["response"]["headers"]

        return out

    def _filter_ftplib_interaction(
        self, interaction: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        interaction = interaction.copy()

        # Filter arguments and other string values
        if "filter_arguments" in self.vcr_config:
            filters = self.vcr_config["filter_arguments"]

            # Filter args
            if "args" in interaction:
                args = list(interaction["args"])
                for value, replacement in filters:
                    for i, arg in enumerate(args):
                        if isinstance(arg, str):
                            args[i] = arg.replace(value, replacement)
                interaction["args"] = tuple(args)

            # Filter host
            if "host" in interaction and isinstance(interaction["host"], str):
                host = interaction["host"]
                for value, replacement in filters:
                    host = host.replace(value, replacement)
                interaction["host"] = host

        # Handle before_record_response
        if "before_record_response" in self.vcr_config:
            response_dict = {
                "body": {
                    "string": interaction.get("body"),
                    "encoding": interaction.get("encoding"),
                },
                "status": {"message": interaction.get("response")},
                "headers": {},  # No headers in FTP
            }

            for filter_func in self.vcr_config["before_record_response"]:
                filtered_response = filter_func(response_dict)
                if filtered_response is None:
                    return None  # Drop the interaction
                response_dict = filtered_response

            # Map back
            if "body" in response_dict:
                body_str = response_dict["body"].get("string")
                if body_str is not None:
                    if isinstance(body_str, bytes):
                        serialized = self._serialize_body(body_str)
                        interaction["body"] = serialized["body"]
                        interaction["encoding"] = serialized["encoding"]
                    else:
                        interaction["body"] = body_str
                        interaction["encoding"] = response_dict["body"].get(
                            "encoding", "utf-8"
                        )
                else:  # body might have been filtered out
                    interaction.pop("body", None)
                    interaction.pop("encoding", None)

            if "status" in response_dict:
                interaction["response"] = response_dict["status"].get("message")

        return interaction

    def _should_record(self) -> bool:
        if self.record_mode == "none":
            return False
        if self.record_mode == "once":
            return not self.cassette_path.exists()
        if self.record_mode == "all":
            return True
        return False

    # urllib interception
    def _recording_urlopen(self, orig, url, *a, **k):
        """Wrapper around urllib.request.urlopen to record FTP GETs."""
        try:
            resp = orig(url, *a, **k)
        except URLError as e:
            # When recording and the remote FTP host is unreachable, skip the test
            pytest.skip(f"Skipping FTP recording due to network error: {e}")
        data = resp.read()
        entry = {"url": str(url)}
        entry.update(self._serialize_body(data))
        entry_filtered = self._apply_vcr_filters(entry)
        if entry_filtered is None:
            return _FakeResponse(data, url=str(url))
        self.interactions.append(entry_filtered)
        return _FakeResponse(self._deserialize_body(entry_filtered), url=str(url))

    def _replay_urlopen(self, url, *a, **k):
        for i in range(self._replay_index, len(self.interactions)):
            if self.interactions[i].get("url") == str(url):
                entry = self.interactions[i]
                self._replay_index = i + 1
                return _FakeResponse(self._deserialize_body(entry), url=str(url))
        if self._replay_index < len(self.interactions):
            entry = self.interactions[self._replay_index]
            self._replay_index += 1
            return _FakeResponse(self._deserialize_body(entry), url=entry.get("url"))
        raise AttributeError(f"No recorded FTP interaction for URL: {url}")

    # ftplib interception: retrbinary / retrlines
    def __enter__(self):
        """Install the FTP and urllib interceptors."""
        # patch urllib
        if self._should_record():
            self._patcher = patch(
                "urllib.request.urlopen",
                lambda url, *a, **k: self._recording_urlopen(
                    self._orig_urlopen, url, *a, **k
                ),
            )
            self._patcher.start()

            # save originals
            self._originals["retrbinary"] = ftplib.FTP.retrbinary
            self._originals["retrlines"] = ftplib.FTP.retrlines

            cassette = self

            def retrbinary_recorder(self, cmd, callback, blocksize=8192, rest=None):
                buf = bytearray()

                def capture(chunk):
                    buf.extend(chunk)
                    try:
                        callback(chunk)
                    except Exception:
                        pass

                try:
                    res = cassette._originals["retrbinary"](
                        self, cmd, capture, blocksize, rest
                    )
                except ftplib.error_perm as e:
                    # Permanent error, record it and re-raise
                    host = (
                        getattr(self, "host", None) or getattr(self, "sock", None) or ""
                    )
                    entry = {
                        "command": "retrbinary",
                        "args": (cmd,),
                        "error": str(e),
                        "host": host,
                    }
                    cassette.interactions.append(entry)
                    raise
                host = getattr(self, "host", None) or getattr(self, "sock", None) or ""
                try:
                    res = cassette._originals["retrbinary"](
                        self, cmd, capture, blocksize, rest
                    )
                except ftplib.error_perm as e:
                    # Permanent error, record it and re-raise
                    entry = {
                        "command": "retrbinary",
                        "args": (cmd,),
                        "error": str(e),
                        "host": host,
                    }
                    cassette.interactions.append(entry)
                    raise
                except ftplib.all_errors:
                    # Let other errors fail the test loudly
                    raise

                entry = {
                    "command": "retrbinary",
                    "args": (cmd,),
                    "response": res,
                    "host": host,
                }
                entry.update(cassette._serialize_body(bytes(buf)))
                filtered_entry = cassette._filter_ftplib_interaction(entry)
                if filtered_entry:
                    cassette.interactions.append(filtered_entry)
                return res

            def retrlines_recorder(self, cmd, callback=None):
                lines: list[str] = []

                def capture(line):
                    lines.append(line)
                    if callback:
                        try:
                            callback(line)
                        except Exception:
                            pass

                try:
                    res = cassette._originals["retrlines"](self, cmd, capture)
                except ftplib.error_perm as e:
                    host = (
                        getattr(self, "host", None) or getattr(self, "sock", None) or ""
                    )
                    entry = {
                        "command": "retrlines",
                        "args": (cmd,),
                        "error": str(e),
                        "host": host,
                    }
                    cassette.interactions.append(entry)
                    raise
                host = getattr(self, "host", None) or getattr(self, "sock", None) or ""
                try:
                    res = cassette._originals["retrlines"](self, cmd, capture)
                except ftplib.error_perm as e:
                    entry = {
                        "command": "retrlines",
                        "args": (cmd,),
                        "error": str(e),
                        "host": host,
                    }
                    cassette.interactions.append(entry)
                    raise
                except ftplib.all_errors:
                    raise

                body = "\n".join(lines)
                entry = {
                    "command": "retrlines",
                    "args": (cmd,),
                    "response": res,
                    "host": host,
                }
                entry.update(cassette._serialize_body(body.encode("utf-8")))
                filtered_entry = cassette._filter_ftplib_interaction(entry)
                if filtered_entry:
                    cassette.interactions.append(filtered_entry)
                return res

            ftplib.FTP.retrbinary = retrbinary_recorder
            ftplib.FTP.retrlines = retrlines_recorder

            # command and upload wrappers
            COMMANDS_TO_PATCH = [
                "login",
                "cwd",
                "mkd",
                "rmd",
                "delete",
                "rename",
                "pwd",
                "storbinary",
                "storlines",
                "quit",
            ]
            for method_name in COMMANDS_TO_PATCH:
                if hasattr(ftplib.FTP, method_name):
                    self._originals[method_name] = getattr(ftplib.FTP, method_name)

            def record_command(method_name, self, *args):
                host = getattr(self, "host", None) or getattr(self, "sock", None) or ""

                # Censor login credentials before they are even processed
                display_args = args
                if method_name == "login" and len(args) > 0:
                    display_args = ("[REDACTED]",) * len(args)

                try:
                    res = cassette._originals[method_name](self, *args)
                except ftplib.error_perm as e:
                    entry = {
                        "command": method_name,
                        "args": display_args,
                        "error": str(e),
                        "host": host,
                    }
                    cassette.interactions.append(entry)
                    raise
                except ftplib.all_errors:
                    raise

                entry = {
                    "command": method_name,
                    "args": display_args,
                    "response": res,
                    "host": host,
                }
                filtered_entry = cassette._filter_ftplib_interaction(entry)
                if filtered_entry:
                    cassette.interactions.append(filtered_entry)
                return res

            def storbinary_recorder(self, cmd, fp, *args, **kwargs):
                file_content = fp.read()
                # We need to put the content back for the real call
                new_fp = io.BytesIO(file_content)
                host = getattr(self, "host", None) or getattr(self, "sock", None) or ""

                try:
                    res = cassette._originals["storbinary"](
                        self, cmd, new_fp, *args, **kwargs
                    )
                except ftplib.error_perm as e:
                    entry = {
                        "command": "storbinary",
                        "args": (cmd,) + args,
                        "error": str(e),
                        "host": host,
                    }
                    cassette.interactions.append(entry)
                    raise
                except ftplib.all_errors:
                    raise

                entry = {
                    "command": "storbinary",
                    "args": (cmd,) + args,
                    "response": res,
                    "host": host,
                }
                entry.update(cassette._serialize_body(file_content))
                filtered_entry = cassette._filter_ftplib_interaction(entry)
                if filtered_entry:
                    cassette.interactions.append(filtered_entry)
                return res

            def storlines_recorder(self, cmd, fp, *args, **kwargs):
                file_content_str = fp.read()
                new_fp = io.StringIO(file_content_str)
                host = getattr(self, "host", None) or getattr(self, "sock", None) or ""

                try:
                    res = cassette._originals["storlines"](
                        self, cmd, new_fp, *args, **kwargs
                    )
                except ftplib.error_perm as e:
                    entry = {
                        "command": "storlines",
                        "args": (cmd,) + args,
                        "error": str(e),
                        "host": host,
                    }
                    cassette.interactions.append(entry)
                    raise
                except ftplib.all_errors:
                    raise

                entry = {
                    "command": "storlines",
                    "args": (cmd,) + args,
                    "response": res,
                    "host": host,
                }
                entry.update(cassette._serialize_body(file_content_str.encode("utf-8")))
                filtered_entry = cassette._filter_ftplib_interaction(entry)
                if filtered_entry:
                    cassette.interactions.append(filtered_entry)
                return res

            ftplib.FTP.storbinary = storbinary_recorder
            ftplib.FTP.storlines = storlines_recorder

            def make_command_recorder(name):
                def recorder(self, *args):
                    return record_command(name, self, *args)

                return recorder

            for name in [
                "login",
                "cwd",
                "mkd",
                "rmd",
                "delete",
                "rename",
                "pwd",
                "quit",
            ]:
                setattr(ftplib.FTP, name, make_command_recorder(name))
        else:
            # replay mode
            if not self.cassette_path.exists():
                raise AttributeError(f"No ftp cassette to replay: {self.cassette_path}")
            with self.cassette_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self.interactions = data.get("interactions", [])
            self._patcher = patch(
                "urllib.request.urlopen",
                lambda url, *a, **k: self._replay_urlopen(url, *a, **k),
            )
            self._patcher.start()

            cassette = self

            def find_interaction(url=None, method=None, command=None, args=None):
                # Special case for login: we don't compare arguments for security.
                if command == "login":
                    for i in range(cassette._replay_index, len(cassette.interactions)):
                        interaction = cassette.interactions[i]
                        if interaction.get("command") == "login":
                            cassette._replay_index = i + 1
                            return interaction
                    return None

                search_args = list(args) if args is not None else None
                if search_args and "filter_arguments" in cassette.vcr_config:
                    for value, replacement in cassette.vcr_config["filter_arguments"]:
                        for i, arg in enumerate(search_args):
                            if isinstance(arg, str):
                                search_args[i] = arg.replace(value, replacement)

                for i in range(cassette._replay_index, len(cassette.interactions)):
                    interaction = cassette.interactions[i]
                    if url and interaction.get("url") != url:
                        continue
                    if method and interaction.get("method") != method:
                        continue
                    if command and interaction.get("command") != command:
                        continue
                    if (
                        search_args is not None
                        and interaction.get("args") != search_args
                    ):
                        continue

                    cassette._replay_index = i + 1
                    return interaction
                return None

            def retrbinary_replayer(self, cmd, callback, blocksize=8192, rest=None):
                interaction = find_interaction(command="retrbinary", args=(cmd,))
                if interaction is None:
                    raise AttributeError(
                        f"No recorded FTP interaction for retrbinary with cmd: {cmd}"
                    )
                if "error" in interaction:
                    raise ftplib.error_perm(interaction["error"])

                data = cassette._deserialize_body(interaction)
                for i in range(0, len(data), blocksize):
                    callback(data[i : i + blocksize])
                return interaction.get("response") or "226 Transfer complete."

            def retrlines_replayer(self, cmd, callback=None):
                interaction = find_interaction(command="retrlines", args=(cmd,))
                if interaction is None:
                    raise AttributeError(
                        f"No recorded FTP interaction for retrlines with cmd: {cmd}"
                    )
                if "error" in interaction:
                    raise ftplib.error_perm(interaction["error"])

                data = cassette._deserialize_body(interaction).decode("utf-8")
                lines = data.splitlines()
                for line in lines:
                    if callback:
                        callback(line)
                return interaction.get("response") or "226 Transfer complete."

            # install replay wrappers
            self._originals["retrbinary"] = ftplib.FTP.retrbinary
            self._originals["retrlines"] = ftplib.FTP.retrlines
            ftplib.FTP.retrbinary = retrbinary_replayer
            ftplib.FTP.retrlines = retrlines_replayer

            COMMANDS_TO_PATCH = [
                "login",
                "cwd",
                "mkd",
                "rmd",
                "delete",
                "rename",
                "pwd",
                "storbinary",
                "storlines",
                "quit",
            ]
            for method_name in COMMANDS_TO_PATCH:
                if hasattr(ftplib.FTP, method_name):
                    self._originals[method_name] = getattr(ftplib.FTP, method_name)

            def replay_command(method_name, self, *args):
                interaction = find_interaction(command=method_name, args=args)
                if interaction is None:
                    raise AttributeError(
                        f"No recorded FTP interaction for {method_name} with args {args}"
                    )
                if "error" in interaction:
                    raise ftplib.error_perm(interaction["error"])
                response = interaction.get("response")
                if response is None:
                    # Fallback for safety, though recorded response should exist.
                    return "250 Command successful."
                return response

            def storbinary_replayer(self, cmd, fp, *args, **kwargs):
                # fp is the file pointer with data to "upload", we can ignore it in replay
                # but we can use its content to find the right interaction if needed.
                interaction = find_interaction(command="storbinary", args=(cmd,) + args)
                if interaction is None:
                    raise AttributeError(
                        f"No recorded FTP interaction for storbinary with cmd: {cmd}"
                    )
                if "error" in interaction:
                    raise ftplib.error_perm(interaction["error"])
                return interaction.get("response") or "226 Transfer complete."

            def storlines_replayer(self, cmd, fp, *args, **kwargs):
                interaction = find_interaction(command="storlines", args=(cmd,) + args)
                if interaction is None:
                    raise AttributeError(
                        f"No recorded FTP interaction for storlines with cmd: {cmd}"
                    )
                if "error" in interaction:
                    raise ftplib.error_perm(interaction["error"])
                return interaction.get("response") or "226 Transfer complete."

            ftplib.FTP.storbinary = storbinary_replayer
            ftplib.FTP.storlines = storlines_replayer

            def make_command_replayer(name):
                def replayer(self, *args):
                    return replay_command(name, self, *args)

                return replayer

            for name in [
                "login",
                "cwd",
                "mkd",
                "rmd",
                "delete",
                "rename",
                "pwd",
                "quit",
            ]:
                setattr(ftplib.FTP, name, make_command_replayer(name))

        return self

    def __exit__(self, exc_type, exc, tb):
        if self._patcher:
            try:
                self._patcher.stop()
            except Exception:
                pass

        # restore ftplib originals
        for method_name, original_method in self._originals.items():
            try:
                setattr(ftplib.FTP, method_name, original_method)
            except Exception:
                pass

        # persist if recorded
        if self._should_record() and self.interactions:
            self.cassette_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cassette_path.open("w", encoding="utf-8", newline="\n") as f:
                yaml.safe_dump({"interactions": self.interactions}, f)


def record_ftp_context_manager(request: SubRequest):
    marker = request.node.get_closest_marker("record_ftp")

    if marker:
        record_no_overwrite = request.config.getoption("--record-no-overwrite")
        record_type = request.config.getoption("--record")
        test_function = request.node.name
        test_module_path = Path(request.node.fspath)

        record_file_path = RecordFilePathBuilder.build(
            test_module_path=test_module_path,
            test_function=test_function,
        )

        vcr_config = {}
        if "vcr_config" in request.fixturenames:
            vcr_config = request.getfixturevalue("vcr_config")

        if (RecordType.all in record_type or RecordType.ftp in record_type) and not (
            record_file_path.exists() and record_no_overwrite
        ):
            if record_file_path.exists():
                record_file_path.unlink(missing_ok=True)
            with FTPCassette(
                cassette_path=record_file_path,
                record_mode="once",
                vcr_config=vcr_config,
            ) as cassette:
                yield cassette
        elif record_file_path.exists():
            with FTPCassette(
                cassette_path=record_file_path,
                record_mode="none",
                vcr_config=vcr_config,
            ) as cassette:
                yield cassette
        else:
            raise AttributeError(
                f"No comparison possible since there is no ftp cassette : {record_file_path}"
            )
    else:
        yield None


record_ftp_fixture = pytest.fixture(name="record_ftp", autouse=True)(
    record_ftp_context_manager
)
