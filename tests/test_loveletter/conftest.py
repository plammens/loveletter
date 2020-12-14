import random

import pytest


random.seed(2020)
_RAND_STATE = random.getstate()


@pytest.fixture(scope="function", autouse=True)
def set_random_state():
    random.setstate(_RAND_STATE)
    yield
    random.setstate(_RAND_STATE)
