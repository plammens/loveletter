import abc
from dataclasses import dataclass
from typing import TYPE_CHECKING, Tuple

import valid8

from loveletter.gameevent import ChoiceEvent, GameInputRequest, GameResultEvent


if TYPE_CHECKING:
    from loveletter.cards import Card
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

    @ChoiceStep.choice.setter
    def choice(self, value):
        from loveletter.cards import CardType

        super(CardGuess, type(self)).choice.fset(self, CardType(value))

    def _validate_choice(self, value):
        # Validation and setter implemented in one step with CardType.__new__
        pass


class PlayerChoice(ChoiceStep):
    """Make the player choose a player"""

    def __init__(self, player: "RoundPlayer", card_played: "Card"):
        super().__init__(player, card_played)
        game_round = self.player.round
        self._valid_choices = {
            p for p in game_round.players if p.alive and not p.immune
        }

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
    def __init__(
        self, player: "RoundPlayer", card_played: "Card", options: Tuple["Card", ...]
    ):
        super().__init__(player, card_played)
        self.options = options

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

    def __init__(
        self, player: "RoundPlayer", card_played: "Card", cards: Tuple["Card", ...]
    ):
        super().__init__(player, card_played)
        self.cards = cards

    def _validate_choice(self, value):
        valid8.validate("choice", value, instance_of=tuple)
        valid8.validate(
            "choice",
            set(value),
            equals=set(self.cards),
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
