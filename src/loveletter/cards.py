import abc
import enum
import functools
from typing import (
    ClassVar,
    Dict,
    Generator,
    Optional,
    TYPE_CHECKING,
    Tuple,
    Type,
)

import valid8

import loveletter.move as move
from loveletter.utils import is_subclass

if TYPE_CHECKING:
    from loveletter.player import Player
    from loveletter.round import Round


MoveStepGenerator = Generator[
    move.MoveStep, move.MoveStep, Optional[Tuple[move.MoveResult, ...]]
]


class Card(metaclass=abc.ABCMeta):
    value: ClassVar[int]
    steps: ClassVar[Tuple[Type[move.MoveStep]]]  # indicates the steps yielded by play()
    cancellable: ClassVar[bool] = True

    @property
    def name(self):
        """Name of the card"""
        return self.__class__.__name__

    def __str__(self) -> str:
        return f"{self.name}()"

    def __repr__(self) -> str:
        return f"<{self} at {id(self):#X}>"

    def check_move(self, owner, card):
        """Check if the owner can play a given card if it has this one in their hand"""
        pass

    @abc.abstractmethod
    def play(self, owner: "Player") -> MoveStepGenerator:
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
        will return a tuple of :class:`loveletter.move.MoveResult` instances
        summarising the results of the move in sequence.

        For cancellable cards (those whose ``cancellable`` class variable is set to
        True), at any point before the move is executed, the caller can .throw() a
        CancelMove exception to cancel the move. This will exit the generator
        (raising a StopIteration) and thus will not apply the effect of the move.
        Calling .close() is equivalent, but doesn't raise the StopIteration.

        Some moves don't allow cancellation; if attempted to be cancelled, they will
        throw a CancellationError will be thrown and the turn will be put in an
        invalid state.

        :param owner: Owner of the card; who is playing it.
        :returns: A generator as described above.
        """
        pass

    def discard_effects(self, owner: "Player") -> Tuple[move.MoveResult, ...]:
        """Apply the effects of discarding this card from the player's hand"""
        return ()

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


class Spy(Card):
    value = 0
    steps = ()

    def play(self, owner: "Player") -> MoveStepGenerator:
        self._validate_move(owner)
        game_round = owner.round
        spy_winner = getattr(game_round, "spy_winner", None)
        game_round.spy_winner = owner if spy_winner in {None, owner} else None
        return ()
        # noinspection PyUnreachableCode
        yield

    @classmethod
    def collect_extra_points(cls, game_round: "Round") -> Dict["Player", int]:
        points = super().collect_extra_points(game_round)
        if (spy_winner := getattr(game_round, "spy_winner", None)) and spy_winner.alive:
            points.update({spy_winner: 1})
        return points


class Guard(Card):
    value = 1
    steps = (move.OpponentChoice, move.CardGuess)

    def play(self, owner: "Player") -> MoveStepGenerator:
        self._validate_move(owner)
        opponent = (yield from self._yield_step(move.OpponentChoice(owner))).choice
        if opponent is move.OpponentChoice.NO_TARGET:
            return ()

        guess = (yield from self._yield_step(move.CardGuess())).choice

        # execute move:
        results = []
        if type(opponent.hand.card) == guess:
            opponent.eliminate()
            results.append(move.PlayerEliminated(owner, self, opponent))

        return tuple(results)


class Priest(Card):
    value = 2
    steps = (move.OpponentChoice,)

    def play(self, owner: "Player") -> MoveStepGenerator:
        self._validate_move(owner)
        opponent = (yield from self._yield_step(move.OpponentChoice(owner))).choice
        if opponent is move.OpponentChoice.NO_TARGET:
            return ()
        return (move.ShowOpponentCard(owner, self, opponent),)


class Baron(Card):
    value = 3
    steps = (move.OpponentChoice,)

    def play(self, owner: "Player") -> MoveStepGenerator:
        self._validate_move(owner)
        opponent = (yield from self._yield_step(move.OpponentChoice(owner))).choice
        if opponent is move.OpponentChoice.NO_TARGET:
            return ()

        results = [move.CardComparison(owner, self, opponent)]
        # owner.hand.card is guaranteed not to be the card being played (i.e. self)
        owner_value, opponent_value = owner.hand.card.value, opponent.hand.card.value
        eliminated = (
            opponent
            if opponent_value < owner_value
            else owner
            if owner_value < opponent_value
            else None
        )
        if eliminated:
            eliminated.eliminate()
            results.append(move.PlayerEliminated(owner, self, eliminated))

        return tuple(results)


class Handmaid(Card):
    value = 4
    steps = ()

    def play(self, owner: "Player") -> MoveStepGenerator:
        self._validate_move(owner)
        owner.immune = True
        return (move.ImmunityGranted(owner, self),)
        # noinspection PyUnreachableCode
        yield


class Prince(Card):
    value = 5
    steps = (move.PlayerChoice,)

    def play(self, owner: "Player") -> MoveStepGenerator:
        self._validate_move(owner)
        player = (yield from self._yield_step(move.PlayerChoice(owner.round))).choice

        # if player is owner, player.hand.card is guaranteed not to be self
        results = [move.CardDiscarded(owner, self, player, player.hand.card)]
        results.extend(player.discard_card(player.hand.card))
        if player.alive:
            deck = owner.round.deck
            card = deck.take() if deck.stack else deck.take_set_aside()
            player.give(card)
            results.append(move.CardDealt(owner, self, player, card))

        return tuple(results)


class Chancellor(Card):
    value = 6
    steps = (move.ChooseOneCard, move.ChooseOrderForDeckBottom)
    cancellable = False

    def play(self, owner: "Player") -> MoveStepGenerator:
        self._validate_move(owner)

        deck = owner.round.deck
        try:
            # don't take cards from deck yet so that if something raises, the deck
            # will remain intact
            options = (owner.hand.card, *deck.stack[-2:])
            choice = (yield from self._yield_step(move.ChooseOneCard(options))).choice
            owner.hand.replace(choice)
            leftover = set(options) - {choice}
            order = (
                yield from self._yield_step(
                    move.ChooseOrderForDeckBottom(tuple(leftover))
                )
            ).choice

            # actually take cards from deck
            for card in reversed(options[1:]):
                _ = deck.take()
                assert _ is card
            for card in reversed(order):
                deck.place(card)

            return (
                move.CardChosen(owner, self, choice),
                move.CardsPlacedBottomOfDeck(owner, self, order),
            )
        except (move.CancelMove, GeneratorExit) as e:
            raise move.CancellationError(
                "Can't cancel anymore; player has seen cards in deck"
            ) from e


class King(Card):
    value = 7
    steps = (move.OpponentChoice,)

    def play(self, owner: "Player") -> MoveStepGenerator:
        self._validate_move(owner)
        opponent = (yield from self._yield_step(move.OpponentChoice(owner))).choice
        if opponent is move.OpponentChoice.NO_TARGET:
            return ()
        opponent.hand.replace(owner.hand.replace(opponent.hand.card))
        return (move.CardsSwapped(owner, self, opponent),)


class Countess(Card):
    value = 8
    steps = ()

    def play(self, owner: "Player") -> MoveStepGenerator:
        self._validate_move(owner)
        return ()
        # noinspection PyUnreachableCode
        yield

    def check_move(self, owner, card):
        disallowed = {CardType.PRINCE, CardType.KING}
        card_type = CardType(card)
        valid8.validate(
            "card",
            card_type,
            custom=lambda t: t not in disallowed,
            help_msg=f"Can't play a {card_type.name.title()} with a Countess in hand",
        )


class Princess(Card):
    value = 9
    steps = ()

    def play(self, owner: "Player") -> MoveStepGenerator:
        self._validate_move(owner)
        return ()
        # noinspection PyUnreachableCode
        yield

    def discard_effects(self, owner: "Player") -> Tuple[move.MoveResult, ...]:
        if owner.alive:
            owner.eliminate()
            return (move.PlayerEliminated(owner, self, owner),)
        else:
            return ()


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
    def _missing_(cls, value):
        if not (isinstance(value, Card) or is_subclass(value, Card)):
            return None
        return CardType(value.value)

    def __eq__(self, other):
        return super().__eq__(CardType(self._get_value(other)))

    def __hash__(self):
        return self.value

    def __lt__(self, other):
        return self.value < self._get_value(other)

    @staticmethod
    def _get_value(other):
        return other.value if is_subclass(other, Card) else other
