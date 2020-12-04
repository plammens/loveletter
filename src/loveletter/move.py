import abc
from typing import Optional

from loveletter.cards import CardType


class MoveStep(metaclass=abc.ABCMeta):
    @property
    @abc.abstractmethod
    def completed(self) -> bool:
        return False


DONE = MoveStep()  # special flag to indicate the move is done


class CardGuess(MoveStep):
    """Make the player guess a card type"""

    def __init__(self):
        self._choice = None

    @property
    def choice(self) -> Optional[CardType]:
        return self._choice

    @choice.setter
    def choice(self, value):
        self._choice = CardType(value)

    @property
    def completed(self) -> bool:
        return self._choice is not None
