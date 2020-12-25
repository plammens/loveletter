from collections import Counter  # noqa

import more_itertools as mitt  # noqa
import pytest  # noqa
import pytest_cases  # noqa

# from ... import * imports are needed because of how fixtures are generated;
# see pytest-cases#174
import loveletter.cardpile
import loveletter.cards as cards
from loveletter.cardpile import CardPile, Deck, STANDARD_DECK_COUNTS  # noqa
from loveletter.cards import CardType  # noqa
from test_loveletter.unit.test_cardpile_cases import *
from test_loveletter.unit.test_cards_cases import *
from test_loveletter.utils import collect_subclasses, random_card_counts


@pytest_cases.parametrize(
    counts=mitt.repeatfunc(random_card_counts, 5),
    pile_class=collect_subclasses(CardPile, loveletter.cardpile),
)
def test_pileFromCounts_counts_hasCorrectCards(pile_class, counts):
    pile = pile_class.from_counts(counts)
    empiric_counts = Counter(map(CardType, pile))
    assert empiric_counts == counts
    assert pile.get_counts() == empiric_counts


def test_deckFromCounts_default_isStandardDeck():
    deck = Deck.from_counts()
    assert Counter(map(CardType, deck)) == STANDARD_DECK_COUNTS


def test_deck_containsSetAside():
    deck = Deck([], set_aside=(set_aside := cards.Princess()))
    assert set_aside in deck


@pytest_cases.parametrize_with_cases("card", cases=CardCases)
@pytest_cases.parametrize_with_cases("deck", cases=DeckCases)
def test_deckPlace_card_placesBottom(deck, card):
    deck.place(card)
    assert deck.stack[0] is card


@pytest_cases.parametrize_with_cases("discard_pile", cases=DiscardPileCases)
def test_discardPileTake_raises(discard_pile):
    with pytest.raises(TypeError):
        discard_pile.take()
