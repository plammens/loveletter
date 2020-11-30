import pytest

from loveletter.cards import Card
from test_loveletter.utils import collect_card_classes


@pytest.fixture(params=collect_card_classes())
def card(request) -> Card:
    return request.param()
