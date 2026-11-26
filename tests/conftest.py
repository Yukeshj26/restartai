import os
import pytest

@pytest.fixture(autouse=True, scope="session")
def default_demo_mode_for_tests():
    previous = os.environ.get("CALL_E_MODE")
    os.environ["CALL_E_MODE"] = "demo"
    yield
    if previous is None:
        os.environ.pop("CALL_E_MODE", None)
    else:
        os.environ["CALL_E_MODE"] = previous
