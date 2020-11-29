import inspect
from typing import Collection

import loveletter.cards


def collect_card_classes() -> Collection[loveletter.cards.Card]:
    def is_card_class(obj):
        return (
            inspect.isclass(obj)
            and issubclass(obj, cards.Card)
            and obj is not cards.Card
        )

    cards = loveletter.cards
    return list(filter(is_card_class, vars(cards).values()))
