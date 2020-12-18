from collections import Counter

import more_itertools as mitt
import pytest_cases

from loveletter.cardpile import Deck, DiscardPile, STANDARD_DECK_COUNTS
from test_loveletter.utils import random_card_counts


class DeckCases:
    @pytest_cases.case()
    def case_empty_deck(self):
        return Deck.from_counts(Counter())

    @pytest_cases.case()
    @pytest_cases.parametrize(counts=mitt.repeatfunc(random_card_counts, 5))
    def case_random_deck(self, counts) -> Deck:
        return Deck.from_counts(counts)

    @pytest_cases.case()
    def case_full_deck(self):
        return Deck.from_counts(STANDARD_DECK_COUNTS)


class DiscardPileCases:
    @pytest_cases.case()
    def case_empty_discard_pile(self):
        return DiscardPile.from_counts(Counter())

    @pytest_cases.case()
    @pytest_cases.parametrize(counts=mitt.repeatfunc(random_card_counts, 5))
    def case_random_discard_pile(self, counts) -> Deck:
        return DiscardPile.from_counts(counts)

    @pytest_cases.case()
    def case_full_discard_pile(self):
        return DiscardPile.from_counts(STANDARD_DECK_COUNTS)
