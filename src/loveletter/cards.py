import abc
import enum
import functools
from typing import ClassVar, Dict, Generator, TYPE_CHECKING, Tuple, Type

import valid8

import loveletter.move as move

if TYPE_CHECKING:
    from loveletter.player import Player
    from loveletter.round import Round


class Card(metaclass=abc.ABCMeta):
    value: ClassVar[int]
    steps: ClassVar[Tuple[Type[move.MoveStep]]]  # indicates the steps yielded by play()

    @property
    def name(self):
        """Name of the card"""
        return self.__class__.__name__

    @abc.abstractmethod
    def play(self, owner: "Player") -> Generator[move.MoveStep, move.MoveStep, None]:
        """
        Play this card on behalf of its owner.

        The returned generator yields at every step in the move in which some
        additional input is needed from the player. This is encoded as an instance of
        MoveStep. Different types of input requests are represented as subclasses of
        MoveStep; how to fulfill each request is defined by the particular subclass.

        Once the MoveStep object gets "filled in" with the appropriate information,
        it should be sent back to the generator (sending in something else than what
        was yielded by the generator results in an error).

        When all steps get fulfilled, the move will be executed and the generator
        will yield an instance of :class:`loveletter.move.MoveResult` summarising the
        result of the move. After this, the only valid thing to do is to .close() the
        generator, which will clean it up and terminate it gracefully. If .send() is
        called again after a MoveResult has been yielded, the generator will return,
        thus raising a StopIteration exception.

        At any point before the move is executed, the caller can .throw() a
        CancelMove exception to cancel the move. This will destroy the generator and
        thus will not apply the effect of the move. Once a MoveResult has been
        yielded, though, the move cannot be cancelled anymore.

        :param owner: Owner of the card; who is playing it.
        :returns: A generator as described above.
        """
        pass

    @classmethod
    def collect_extra_points(cls, game_round: "Round") -> Dict["Player", int]:
        """
        After a round has ended, collect any extra points to award to players.

        This behaviour is defined by each type of card, that's why it's implemented
        as a classmethod.
        """
        assert game_round.ended
        return {}

    # noinspection PyMethodMayBeStatic
    def _validate_move(self, owner: "Player") -> None:
        valid8.validate("owner", owner)

    @staticmethod
    def _yield_step(step):
        completed = yield step
        valid8.validate(
            "completed_step",
            completed,
            custom=lambda s: s is step,
            help_msg=(
                f"Did not receive the same MoveStep that was yielded: "
                f"expected {step}, got {completed}"
            ),
        )
        valid8.validate(
            "completed_step",
            completed,
            custom=lambda s: s.completed,
            help_msg="Received an incomplete move step",
        )
        return completed

    @staticmethod
    def _yield_done(result: move.MoveResult):
        yield result


class Spy(Card):
    value = 0
    steps = ()

    def play(self, owner: "Player") -> Generator[move.MoveStep, move.MoveStep, None]:
        self._validate_move(owner)
        game_round = owner.round
        game_round.spy_winner = owner if not hasattr(game_round, "spy_winner") else None
        yield from self._yield_done(move.MoveResult(owner, self))

    @classmethod
    def collect_extra_points(cls, game_round: "Round") -> Dict["Player", int]:
        points = super().collect_extra_points(game_round)
        if spy_winner := getattr(game_round, "spy_winner", None):
            points.update({spy_winner: 1})
        return points


class Guard(Card):
    value = 1
    steps = (move.OpponentChoice, move.CardGuess)

    def play(self, owner: "Player") -> Generator[move.MoveStep, move.MoveStep, None]:
        self._validate_move(owner)
        opponent = (yield from self._yield_step(move.OpponentChoice(owner))).choice
        guess = (yield from self._yield_step(move.CardGuess())).choice

        # execute move:
        if type(opponent.hand.card) == guess:
            opponent.eliminate()

        yield from self._yield_done(move.OpponentEliminated(owner, self, opponent))


class Priest(Card):
    value = 2
    steps = ()

    def play(self, owner: "Player") -> Generator[move.MoveStep, move.MoveStep, None]:
        self._validate_move(owner)
        yield from self._yield_done(move.MoveResult(owner, self))


class Baron(Card):
    value = 3
    steps = ()

    def play(self, owner: "Player") -> Generator[move.MoveStep, move.MoveStep, None]:
        self._validate_move(owner)
        yield from self._yield_done(move.MoveResult(owner, self))


class Handmaid(Card):
    value = 4
    steps = ()

    def play(self, owner: "Player") -> Generator[move.MoveStep, move.MoveStep, None]:
        self._validate_move(owner)
        owner.immune = True
        yield from self._yield_done(move.MoveResult(owner, self))


class Prince(Card):
    value = 5
    steps = ()

    def play(self, owner: "Player") -> Generator[move.MoveStep, move.MoveStep, None]:
        self._validate_move(owner)
        yield from self._yield_done(move.MoveResult(owner, self))


class Chancellor(Card):
    value = 6
    steps = ()

    def play(self, owner: "Player") -> Generator[move.MoveStep, move.MoveStep, None]:
        self._validate_move(owner)
        yield from self._yield_done(move.MoveResult(owner, self))


class King(Card):
    value = 7
    steps = ()

    def play(self, owner: "Player") -> Generator[move.MoveStep, move.MoveStep, None]:
        self._validate_move(owner)
        yield from self._yield_done(move.MoveResult(owner, self))


class Countess(Card):
    value = 8
    steps = ()

    def play(self, owner: "Player") -> Generator[move.MoveStep, move.MoveStep, None]:
        self._validate_move(owner)
        yield from self._yield_done(move.MoveResult(owner, self))


class Princess(Card):
    value = 9
    steps = ()

    def play(self, owner: "Player") -> Generator[move.MoveStep, move.MoveStep, None]:
        self._validate_move(owner)
        yield from self._yield_done(move.MoveResult(owner, self))


@functools.total_ordering
class CardType(enum.Enum):
    def __new__(cls, card_class):
        obj = object.__new__(cls)
        obj._value_ = card_class.value
        return obj

    def __init__(self, card_class):
        self.card_class = card_class

    SPY = Spy
    GUARD = Guard
    PRIEST = Priest
    BARON = Baron
    HANDMAID = Handmaid
    PRINCE = Prince
    CHANCELLOR = Chancellor
    KING = King
    COUNTESS = Countess
    PRINCESS = Princess

    @classmethod
    def _missing_(cls, card_class):
        return CardType(card_class.value)

    def __eq__(self, other):
        return super().__eq__(CardType(self._get_value(other)))

    def __hash__(self):
        return self.value

    def __lt__(self, other):
        return self.value < self._get_value(other)

    @staticmethod
    def _get_value(other):
        try:
            if issubclass(other, Card):
                return other.value
        except TypeError:
            pass
        return other
