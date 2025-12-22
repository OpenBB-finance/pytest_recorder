## Purpose
Short, focused guidance to help an AI coding agent be productive in the pytest_recorder repository.

## Quick start (how developers run and record tests)
- Install dependencies with Poetry (project uses poetry):
  - poetry install
- Run tests normally:
  - pytest -q
- Run a single test and create/update recording artifacts:
  - pytest tests/test_saving_requests.py::test_saving_requests --record=http
  - pytest tests/test_saving_requests.py::test_saving_curl_requests --record=curl
  - To record everything for a test run: --record=all
  - Useful flags: --record-no-overwrite (don't overwrite existing records), --record-no-hash (don't hash object/screen records)

## Big picture / architecture
- This project is a pytest plugin (registered in `pyproject.toml` under `[tool.poetry.plugins."pytest11"]`).
- Core responsibilities:
  - Capture and replay HTTP interactions (via `vcrpy` for urllib3 and a custom curl capture for `curl_adapter`). See `pytest_recorder/record_http.py` and `pytest_recorder/record_curl.py`.
  - Persist/compare arbitrary Python objects for deterministic tests (JSON + optional SHA256 hashing). See `pytest_recorder/record_verify_object.py`.
  - Time travel for deterministic datetime-based tests (via `time-machine`). See `pytest_recorder/record_time.py`.
  - High-level test API: a `record` fixture (object collection) plus pytest markers like `@pytest.mark.record_http`, `@pytest.mark.record_curl`, `@pytest.mark.record_time(...)`, `@pytest.mark.record_verify_screen`.

## Important files and patterns (use these as examples)
- Plugin entry: `pytest_recorder/plugin.py` — defines CLI options (`--record`, `--record-no-hash`, `--record-no-overwrite`) and registers markers.
- Fixtures/behaviour:
  - `pytest_recorder/record_http.py` — builds cassette path with `RecordFilePathBuilder.build(...)`. HTTP cassette filename: `{test_function}_urllib3_v{urllib3_major}.yaml`.
  - `pytest_recorder/record_curl.py` — custom Curl cassette handling and `CurlRecordFilePathBuilder.build(...)` which produces `{test_function}_curl.yaml`.
  - `pytest_recorder/record_verify_object.py` — `ObjectCollector` + `ObjectCollectorHandler` for JSON serialization, hashing, persisting and verifying. Object files live under `tests/record/object/` or `tests/record/object_hash/` depending on `hash_only`.
  - `pytest_recorder/record_time.py` — persists a small JSON with `{"isoformat": <iso>, "tick": <bool>}` into `tests/record/time/<module>/<test>.json` and uses `time_machine.travel` on teardown/setup.
  - `pytest_recorder/record_type.py` — canonical list of allowed record types: `none, all, curl, http, object, screen, time`.

## Data flow and file layout
- Recorded artifacts are written under `tests/record/<type>/<test_module>/<file>` (examples are already committed under `tests/record/`).
- On test setup:
  - The fixture checks the marker on the test node and CLI flags.
  - If recording is enabled and no existing record (or overwrite allowed), the fixture arranges record-mode resources and yields a context object (cassette or collector).
  - On teardown, the fixture either persists the captured data or compares current results to the stored records and raises an exception on mismatch.

## Project-specific conventions and gotchas
- Autouse fixtures: `record_http`, `record_curl` and `record_time` are registered with `autouse=True` — the presence of the corresponding pytest marker controls whether they actually activate for a test.
- The `record` fixture (object verifier) is not autouse: tests must declare `record` as an argument or use the helper in examples/tests.
- File name conventions are enforced by `*RecordFilePathBuilder` classes. If you change naming, update those builders and existing fixtures/tests.
- HTTP cassette naming depends on the installed `urllib3` major version to allow multiple recorded versions to coexist: expect filenames like `test_fn_urllib3_v1.yaml` or `..._v2.yaml`.
- `vcr_config` fixture (in tests) can include `filter_headers`, `filter_query_parameters`, and for curl-specific code a `before_record_response` list of callables — `record_curl.py` applies these filters before persisting.

## How to modify behaviour safely
- If adding filters or altering serialization, update `record_curl.apply_vcr_filters` or `ObjectCollectorHandler` accordingly and add targeted unit tests in `tests/`.
- When changing persistence format (YAML/JSON or path), update the Records already under `tests/record/` or add a migration test to avoid false failures for consumers.

## Tests and examples
- Look at `tests/test_saving_requests.py` and the `tests/pytest_recorder/test_recorder_verify_object.py` for concrete usage and test helpers (mocks, example `vcr_config` fixture).
- The repository contains sample recorded artifacts under `tests/record/` (use them as canonical examples to follow).

## Fail-fast cues for AI edits
- If a new failing test references missing record files in `tests/record/`, check the `--record` flags and `RecordFilePathBuilder` naming.
- AttributeError messages raised by the fixtures include the expected record file path — use those paths to locate or regenerate golden records.

If anything here is unclear or you'd like more examples (e.g., a small toy test that demonstrates a specific record type), tell me which area to expand.
