# 1. TL;DR example
STEP 1

Write this code:


# File tests/some_module.py

```python
@pytest.mark.record_curl
@pytest.mark.record_http
@pytest.mark.record_time
@pytest.mark.record_verify_screen
def test_some_test(record):
    some_python_object = ...

    record.add_verify(object=some_python_object)
```

STEP 2

Run:

pytest tests/some_module.py --record

It will:

Save all the Curl and urllib3 requests

Save the execution datetime

Save the screen output

Save the data you provide to recorder object

STEP 3

Run:

pytest tests/some_module.py

It will:

Reuse the stored Curl and urllib3 requests

Reuse the same datetime to execute the test

Compare the current screen output to the previous one and raise and exception if different

Compare the current recorder object data to the previous one and raise and exception if different

# 2. Detailed example
CODE

```python
@pytest.mark.record_curl
@pytest.mark.record_http
@pytest.mark.record_time(date=datetime(2023, 3, 1, 12, 0, 0), tic=False)
@pytest.mark.record_verify_screen(hash=True)
def test_some_test(record):
    ...
    record.hash_only = True
    record.add_verify(object=df)
    record.add_verify(object=[df])

    recorder.add_verify(
        object=df,
    )
```

USAGE

pytest [FILE] [--record[=none,all,curl,http,object,screen,time]] [--record-no-overwrite] [--record-no-hash]

FILES

For a given test_function from test_module, we will have the following files:

/tests/test_module.py:test_function

/tests/record/curl/test_module/test_function.yaml

/tests/record/http/test_module/test_function.yaml

/tests/record/object/test_module/test_function.json

/tests/record/object_hash/test_module/test_function.txt/json?

/tests/record/screen/test_module/test_function.txt/json?

/tests/record/screen_hash/test_module/test_function.txt/json?

/tests/record/time/test_module/test_function.txt/json?

