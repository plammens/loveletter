import pytest_cases

from test_loveletter.utils import collect_card_classes


@pytest_cases.parametrize("cls", collect_card_classes())
def card_any(cls):
    return cls()
