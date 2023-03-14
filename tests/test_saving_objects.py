# IMPORT STANDARD

# IMPORT THIRD-PARTY

# IMPORT INTERNAL


def test_saving_object(record):
    record.hash_only = True
    record.add_verify(True)
    record.add_verify(1)
    record.add_verify("Some str")
    record.add_verify(["Some", "list"])
    record.add_verify({"Some": "dict"})
