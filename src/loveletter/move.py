import abc
from typing import Any, Optional, TYPE_CHECKING

import valid8

if TYPE_CHECKING:
    from loveletter.player import Player
    from loveletter.round import Round


class MoveStep(metaclass=abc.ABCMeta):
    @property
    @abc.abstractmethod
    def completed(self) -> bool:
        return False


class _Done(MoveStep):
    @property
    def completed(self) -> bool:
        return True


DONE = _Done()  # special flag to indicate the move is done


class ChoiceStep(MoveStep, metaclass=abc.ABCMeta):
    def __init__(self):
        self._choice = None

    @property
    def choice(self) -> Optional[Any]:
        return self._choice

    @choice.setter
    @abc.abstractmethod
    def choice(self, value):
        self._choice = value

    @property
    def completed(self) -> bool:
        return self._choice is not None


class CardGuess(ChoiceStep):
    """Make the player guess a card type"""

    @ChoiceStep.choice.setter
    def choice(self, value):
        from loveletter.cards import CardType

        super(CardGuess, type(self)).choice.fset(self, CardType(value))


class PlayerChoice(ChoiceStep):
    """Make the player choose a player"""

    def __init__(self, game_round: "Round"):
        super().__init__()
        self.game_round = game_round

    @ChoiceStep.choice.setter
    def choice(self, value):
        from loveletter.round import Player

        valid8.validate("value", value, instance_of=Player)
        valid8.validate(
            "target",
            value,
            is_in=self.game_round.players,
            help_msg="Cannot choose a player from outside the round",
        )
        super(PlayerChoice, type(self)).choice.fset(self, value)


class OpponentChoice(PlayerChoice):
    """Make the player choose an opponent (any player but themselves)"""

    def __init__(self, player: "Player"):
        super().__init__(player.round)
        self.player: "Player" = player

    @PlayerChoice.choice.setter
    def choice(self, value):
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
        # TODO: refactor so only method to override is validation
        super(OpponentChoice, type(self)).choice.fset(self, value)


class CancelMove(Exception):
    pass
