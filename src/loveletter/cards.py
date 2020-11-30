import abc
import enum
import typing
from typing import ClassVar, Optional

if typing.TYPE_CHECKING:
    from loveletter.player import Player


class Card(metaclass=abc.ABCMeta):
    class ActionType(enum.Enum):
        """How can this card be played"""

        DISCARD = enum.auto()  # discard it onto the pile without targeting
        TARGET = enum.auto()  # target a player

    value: ClassVar[int]
    action_type: ClassVar[ActionType]

    @property
    def name(self):
        """Name of the card"""
        return self.__class__.__name__

    @abc.abstractmethod
    def play(self, owner: "Player", target: Optional["Player"]) -> None:
        """
        Play this card from its owner.

        :param owner: Owner of the card; who is playing it.
        :param target: Optional target player to play the card against. If None,
                       denotes the card is just discarded onto the discard pile.
        """
        assert owner.round is target.round


class Spy(Card):
    value = 0
    action_type = Card.ActionType.DISCARD


class Guard(Card):
    value = 1
    action_type = Card.ActionType.TARGET


class Priest(Card):
    value = 2
    action_type = Card.ActionType.TARGET


class Baron(Card):
    value = 3
    action_type = Card.ActionType.TARGET


class Handmaid(Card):
    value = 4
    action_type = Card.ActionType.DISCARD


class Prince(Card):
    value = 5
    action_type = Card.ActionType.TARGET


class Chancellor(Card):
    value = 6
    action_type = Card.ActionType.TARGET


class King(Card):
    value = 7
    action_type = Card.ActionType.TARGET


class Countess(Card):
    value = 8
    action_type = Card.ActionType.DISCARD


class Princess(Card):
    value = 9
    action_type = Card.ActionType.DISCARD
