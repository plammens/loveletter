from collections import Counter

import more_itertools as mitt
import pytest

import loveletter.cardpile
from loveletter.cardpile import CardPile, Deck, STANDARD_DECK_COUNTS
from test_loveletter.utils import collect_subclasses, random_card_counts


@pytest.mark.parametrize(
    "pile_class", collect_subclasses(CardPile, loveletter.cardpile)
)
@pytest.mark.parametrize("counts", mitt.repeatfunc(random_card_counts, 5))
def test_pileFromCounts_counts_hasCorrectCards(pile_class, counts):
    pile = pile_class.from_counts(counts)
    assert Counter(map(type, pile)) == counts


def test_deckFromCounts_default_isStandardDeck():
    deck = Deck.from_counts()
    assert Counter(map(type, deck)) == STANDARD_DECK_COUNTS


def test_deckPlace_card_raises(deck, card):
    with pytest.raises(TypeError):
        deck.place(card)


def test_discardPileTake_raises(discard_pile, card):
    with pytest.raises(TypeError):
        discard_pile.take()
