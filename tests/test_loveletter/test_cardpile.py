from collections import Counter

import more_itertools as mitt
import pytest
import pytest_cases

import loveletter.cardpile
import test_loveletter.test_cardpile_cases as cardpile_cases
import test_loveletter.test_cards_cases as card_cases
from loveletter.cardpile import CardPile, Deck, STANDARD_DECK_COUNTS
from loveletter.cards import CardType
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


@pytest_cases.parametrize_with_cases("card_pile")
def test_pileEq_equivalentToCountEq(card_pile):
    counts: Counter = card_pile.get_counts()
    assert card_pile == type(card_pile).from_counts(counts)
    counts[CardType.SPY] += 1
    assert card_pile != type(card_pile).from_counts(counts)
    with pytest.raises(TypeError):
        assert card_pile == counts


def test_deckFromCounts_default_isStandardDeck():
    deck = Deck.from_counts()
    assert Counter(map(CardType, deck)) == STANDARD_DECK_COUNTS


@pytest_cases.parametrize_with_cases("card", cases=card_cases.CardCases)
@pytest_cases.parametrize_with_cases("deck", cases=cardpile_cases.DeckCases)
def test_deckPlace_card_placesBottom(deck, card):
    deck.place(card)
    assert deck.stack[0] is card


@pytest_cases.parametrize_with_cases(
    "discard_pile", cases=cardpile_cases.DiscardPileCases
)
def test_discardPileTake_raises(discard_pile):
    with pytest.raises(TypeError):
        discard_pile.take()
