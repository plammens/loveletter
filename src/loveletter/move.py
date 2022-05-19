import abc
import itertools
from collections import Counter
from dataclasses import dataclass
from typing import AbstractSet, Sequence, TYPE_CHECKING, Tuple

import valid8

from loveletter.gameevent import (
    ChoiceEvent,
    GameInputRequest,
    GameResultEvent,
    Serializable,
)


if TYPE_CHECKING:
    from loveletter.cards import Card, CardType
    from loveletter.roundplayer import RoundPlayer


class CancelMove(BaseException):
    pass


class CancellationError(RuntimeError):
    pass


# -------------------- MoveStep hierarchy ------------------


class MoveStep(GameInputRequest, metaclass=abc.ABCMeta):
    def __init__(self, player: "RoundPlayer", card_played: "Card"):
        super().__init__()
        self.player = player  #: who is making this move
        self.card_played = card_played


class ChoiceStep(MoveStep, ChoiceEvent, metaclass=abc.ABCMeta):
    pass


class CardGuess(ChoiceStep):
    """Make the player guess a card type"""

    @property
    def options(self):
        if not hasattr(CardGuess, "_OPTIONS"):
            from loveletter.cards import CardType

            CardGuess._OPTIONS = set(CardType) - {CardType.GUARD}

        # noinspection PyUnresolvedReferences
        return self._OPTIONS

    @ChoiceStep.choice.setter
    def choice(self, value):
        from loveletter.cards import CardType

        super(CardGuess, type(self)).choice.fset(self, CardType(value))

    def to_serializable(self) -> Serializable:
        super().to_serializable()
        return self.choice.value

    def from_serializable(self, value: Serializable) -> "CardType":
        from loveletter.cards import CardType

        return CardType(value)

    def _validate_choice(self, value):
        from loveletter.cards import CardType

        card_type = CardType(value)
        valid8.validate(
            "card_type",
            card_type,
            custom=lambda t: t != CardType.GUARD,  # TODO: use minilambda
            help_msg="You can't guess a Guard",
        )


class PlayerChoice(ChoiceStep):
    """Make the player choose a player"""

    def __init__(self, player: "RoundPlayer", card_played: "Card"):
        super().__init__(player, card_played)
        game_round = self.player.round
        self._valid_choices = {
            p for p in game_round.players if p.alive and not p.immune
        }

    @property
    def options(self) -> AbstractSet:
        return self._valid_choices

    def to_serializable(self) -> int:
        super().to_serializable()
        choice: RoundPlayer = self.choice
        return choice.id

    def from_serializable(self, value: Serializable) -> "RoundPlayer":
        return self.player.round.players[value]

    def _validate_choice(self, value):
        valid8.validate(
            "target",
            value,
            is_in=self._valid_choices,
            help_msg="Must target a living, non-immune player from the round",
        )


class OpponentChoice(PlayerChoice):
    """Make the player choose an opponent (any player but themselves)"""

    # special value for when no player can be targeted because they're all immune
    NO_TARGET = object()

    def __init__(self, player: "RoundPlayer", card_played: "Card"):
        super().__init__(player, card_played)
        self._valid_choices = self._valid_choices - {self.player}

    @property
    def options(self) -> AbstractSet:
        return self._valid_choices or {self.NO_TARGET}

    def to_serializable(self) -> int:
        return (
            "NO_TARGET" if self.choice is self.NO_TARGET else super().to_serializable()
        )

    def from_serializable(self, value: Serializable) -> "RoundPlayer":
        return (
            self.NO_TARGET if value == "NO_TARGET" else super().from_serializable(value)
        )

    def _validate_choice(self, value):
        if self._valid_choices:
            super()._validate_choice(value)
        else:
            valid8.validate(
                "choice",
                value,
                equals=self.NO_TARGET,
                help_msg="No opponent can be targeted, they're all immune",
            )
        valid8.validate(
            "target",
            value,
            custom=lambda v: v is not self.player,
            help_msg="You can't choose yourself",
        )


class ChooseOneCard(ChoiceStep):
    """Choose one card to keep out of a predefined set of options (chancellor)."""

    def __init__(
        self, player: "RoundPlayer", card_played: "Card", options: Tuple["Card", ...]
    ):
        super().__init__(player, card_played)
        self._options = options

    @property
    def options(self) -> Sequence["Card"]:
        return self._options

    def to_serializable(self) -> int:
        super().to_serializable()
        choice: Card = self.choice
        return self._options.index(choice)

    def from_serializable(self, value: Serializable) -> "Card":
        return self._options[value]


class ChooseOrderForDeckBottom(ChoiceStep):
    """
    Choose the order in which to put some cards at the bottom of the deck.

    The choice should be a tuple of the given cards, ordered from topmost to bottommost.
    """

    def __init__(
        self, player: "RoundPlayer", card_played: "Card", cards: Tuple["Card", ...]
    ):
        from loveletter.cards import CardType

        super().__init__(player, card_played)
        self.cards = tuple(sorted(cards, key=CardType))

    @property
    def options(self) -> AbstractSet:
        return set(itertools.permutations(self.cards))

    def to_serializable(self) -> Tuple[int, ...]:
        super().to_serializable()
        choice: Tuple["Card", ...] = self.choice
        cards = self.cards
        return tuple(cards.index(c) for c in choice)

    def from_serializable(self, value: Serializable) -> Tuple["Card", ...]:
        cards = self.cards
        return tuple(cards[i] for i in value)

    def _validate_choice(self, value):
        valid8.validate(
            "choice",
            Counter(value),
            equals=Counter(self.cards),
            help_msg="Chosen cards don't match cards to be ordered",
        )


# -------------------- MoveResult hierarchy ------------------


@dataclass(frozen=True)
class MoveResult(GameResultEvent, metaclass=abc.ABCMeta):
    player: "RoundPlayer"
    card_played: "Card"


@dataclass(frozen=True)
class CorrectCardGuess(MoveResult):
    opponent: "RoundPlayer"
    guess: "CardType"


@dataclass(frozen=True)
class WrongCardGuess(MoveResult):
    opponent: "RoundPlayer"
    guess: "CardType"


@dataclass(frozen=True)
class PlayerEliminated(MoveResult):
    eliminated: "RoundPlayer"
    eliminated_card: "Card"


@dataclass(frozen=True)
class ShowOpponentCard(MoveResult):
    opponent: "RoundPlayer"
    card_shown: "Card"


@dataclass(frozen=True)
class CardComparison(MoveResult):
    opponent: "RoundPlayer"
    player_card: "Card"
    opponent_card: "Card"


@dataclass(frozen=True)
class CardDiscarded(MoveResult):
    """Card discarded as a result of the Prince's effect."""

    target: "RoundPlayer"
    discarded: "Card"


@dataclass(frozen=True)
class CardDealt(MoveResult):
    target: "RoundPlayer"
    card_dealt: "Card"


@dataclass(frozen=True)
class CardChosen(MoveResult):
    choice: "Card"


@dataclass(frozen=True)
class CardsPlacedBottomOfDeck(MoveResult):
    cards: Tuple["Card"]


@dataclass(frozen=True)
class ImmunityGranted(MoveResult):
    pass


@dataclass(frozen=True)
class CardsSwapped(MoveResult):
    opponent: "RoundPlayer"


def is_move_results(obj):
    """Utility to determine whether a value yielded from .play() is the result"""
    return isinstance(obj, tuple) and all(isinstance(r, MoveResult) for r in obj)
