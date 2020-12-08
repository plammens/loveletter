import abc
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

import valid8


if TYPE_CHECKING:
    from loveletter.cards import Card
    from loveletter.player import Player
    from loveletter.round import Round


class CancelMove(Exception):
    pass


class MoveStep(metaclass=abc.ABCMeta):
    @property
    @abc.abstractmethod
    def completed(self) -> bool:
        return False


class ChoiceStep(MoveStep, metaclass=abc.ABCMeta):
    def __init__(self):
        self._choice = None

    @property
    def choice(self) -> Optional[Any]:
        return self._choice

    @choice.setter
    def choice(self, value):
        self._validate_choice(value)
        self._choice = value

    @property
    def completed(self) -> bool:
        return self._choice is not None

    @abc.abstractmethod
    def _validate_choice(self, value):
        """Subclasses should override this to provide validation for the choice"""
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

    def __init__(self, game_round: "Round"):
        super().__init__()
        self.game_round = game_round

    def _validate_choice(self, value):
        from loveletter.round import Player

        valid8.validate("value", value, instance_of=Player)
        valid8.validate(
            "target",
            value,
            is_in=self.game_round.living_players,
            help_msg="Cannot choose a player from outside the round",
        )


class OpponentChoice(PlayerChoice):
    """Make the player choose an opponent (any player but themselves)"""

    def __init__(self, player: "Player"):
        super().__init__(player.round)
        self.player: "Player" = player

    def _validate_choice(self, value):
        valid8.validate(
            "target",
            value,
            custom=lambda v: v is not self.player,
            help_msg="You can't choose yourself",
        )
        valid8.validate(
            "target",
            value,
            custom=lambda v: not getattr(v, "immune", False),
            help_msg="Can't target an immune player",
        )


# -------------------- MoveResult hierarchy ------------------


@dataclass
class MoveResult(metaclass=abc.ABCMeta):
    player: "Player"
    card_played: "Card"


@dataclass
class PlayerEliminated(MoveResult):
    eliminated: "Player"


@dataclass
class ShowOpponentCard(MoveResult):
    opponent: "Player"


@dataclass
class CardComparison(MoveResult):
    opponent: "Player"


def is_move_results(obj):
    """Utility to determine whether a value yielded from .play() is the result"""
    return isinstance(obj, tuple) and all(isinstance(r, MoveResult) for r in obj)
