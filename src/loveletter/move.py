import abc
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Tuple

import valid8

from loveletter.gameevent import (
    ChoiceEvent,
    GameInputRequest,
    GameResultEvent,
    Serializable,
)


if TYPE_CHECKING:
    from loveletter.cards import Card
    from loveletter.roundplayer import RoundPlayer
    from loveletter.round import Round


class CancelMove(BaseException):
    pass


class CancellationError(RuntimeError):
    pass


# -------------------- MoveStep hierarchy ------------------


class MoveStep(GameInputRequest, metaclass=abc.ABCMeta):
    pass


class ChoiceStep(MoveStep, ChoiceEvent, metaclass=abc.ABCMeta):
    pass


class CardGuess(ChoiceStep):
    """Make the player guess a card type"""

    @ChoiceStep.choice.setter
    def choice(self, value):
        from loveletter.cards import CardType

        super(CardGuess, type(self)).choice.fset(self, CardType(value))

    def to_serializable(self) -> Serializable:
        super().to_serializable()
        return self.choice.value

    def from_serializable(self, value: Serializable) -> None:
        from loveletter.cards import CardType

        return CardType(value)

    def _validate_choice(self, value):
        # Validation and setter implemented in one step with CardType.__new__
        pass


class PlayerChoice(ChoiceStep):
    """Make the player choose a player"""

    def __init__(self, game_round: "Round"):
        super().__init__()
        self.game_round = game_round
        self._valid_choices = {
            p for p in self.game_round.players if p.alive and not p.immune
        }

    def to_serializable(self) -> int:
        super().to_serializable()
        choice: RoundPlayer = self.choice
        return choice.id

    def from_serializable(self, value: Serializable) -> "RoundPlayer":
        return self.game_round.players[value]

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

    def __init__(self, player: "RoundPlayer"):
        super().__init__(player.round)
        self.player: "RoundPlayer" = player
        self._valid_choices = self._valid_choices - {player}

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
    def __init__(self, options: Tuple["Card", ...]):
        super().__init__()
        self.options = options

    def to_serializable(self) -> int:
        super().to_serializable()
        choice: Card = self.choice
        return self.options.index(choice)

    def from_serializable(self, value: Serializable) -> "Card":
        return self.options[value]

    def _validate_choice(self, value):
        valid8.validate(
            "choice",
            value,
            is_in=self.options,
            help_msg="This card is not an option",
        )


class ChooseOrderForDeckBottom(ChoiceStep):
    """
    Choose the order in which to put some cards at the bottom of the deck.

    The choice should be a tuple of the given cards, ordered from bottommost to topmost.
    """

    def __init__(self, cards: Tuple["Card", ...]):
        super().__init__()
        self.cards = cards

    def to_serializable(self) -> Tuple[int, ...]:
        super().to_serializable()
        choice: Tuple["Card", ...] = self.choice
        cards = self.cards
        return tuple(cards.index(c) for c in choice)

    def from_serializable(self, value: Serializable) -> Tuple["Card", ...]:
        cards = self.cards
        return tuple(cards[i] for i in value)

    def _validate_choice(self, value):
        valid8.validate("choice", value, instance_of=tuple)
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
class PlayerEliminated(MoveResult):
    eliminated: "RoundPlayer"


@dataclass(frozen=True)
class ShowOpponentCard(MoveResult):
    opponent: "RoundPlayer"


@dataclass(frozen=True)
class CardComparison(MoveResult):
    opponent: "RoundPlayer"


@dataclass(frozen=True)
class CardDiscarded(MoveResult):
    target: "RoundPlayer"
    discarded: "Card"


@dataclass(frozen=True)
class CardDealt(MoveResult):
    target: "RoundPlayer"
    dealt: "Card"


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
