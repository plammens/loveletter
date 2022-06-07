import abc
import enum
import functools
from collections import Counter
from typing import (
    ClassVar,
    Counter as CounterType,
    Dict,
    Generator,
    Optional,
    TYPE_CHECKING,
    Tuple,
    Type,
)

import valid8

import loveletter.move as move
from loveletter.utils import safe_is_subclass

if TYPE_CHECKING:
    from loveletter.roundplayer import RoundPlayer
    from loveletter.round import Round


MoveStepGenerator = Generator[
    move.MoveStep, move.MoveStep, Optional[Tuple[move.MoveResult, ...]]
]


class Card(metaclass=abc.ABCMeta):
    value: ClassVar[int]
    description: ClassVar[str]
    steps: ClassVar[Tuple[Type[move.MoveStep]]]  # indicates the steps yielded by play()
    cancellable: ClassVar[bool] = True

    @property
    def name(self):
        """Name of the card"""
        return self.__class__.__name__

    def __str__(self) -> str:
        return f"{self.name} ({self.value})"

    def __repr__(self) -> str:
        return f"<{self} at {id(self):#X}>"

    def check_move(self, owner, card):
        """Check if the owner can play a given card if it has this one in their hand"""
        pass

    @abc.abstractmethod
    def play(self, owner: "RoundPlayer") -> MoveStepGenerator:
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
        # the do-nothing implementation
        self._validate_move(owner)
        return ()
        # noinspection PyUnreachableCode
        yield

    def discard_effects(self, owner: "RoundPlayer") -> Tuple[move.MoveResult, ...]:
        """Apply the effects of discarding this card from the player's hand"""
        return ()

    @classmethod
    def collect_extra_points(cls, game_round: "Round") -> CounterType["RoundPlayer"]:
        """
        After a round has ended, collect any extra points to award to players.

        This behaviour is defined by each type of card, that's why it's implemented
        as a classmethod.
        """
        assert game_round.ended
        return Counter()

    # noinspection PyMethodMayBeStatic
    def _validate_move(self, owner: "RoundPlayer") -> None:
        valid8.validate("owner", owner)


class Spy(Card):
    value = 0
    description = (
        "At the end of the round, if you are the only player still in the round who "
        "played or discarded a Spy, gain 1 token of affection."
    )
    steps = ()

    def play(self, owner: "RoundPlayer") -> MoveStepGenerator:
        return super().play(owner)

    def discard_effects(self, owner: "RoundPlayer") -> Tuple[move.MoveResult, ...]:
        game_round = owner.round
        game_round.spy_players.add(owner)
        return ()

    @classmethod
    def collect_extra_points(cls, game_round: "Round") -> Dict["RoundPlayer", int]:
        points = super().collect_extra_points(game_round)
        alive_spy_players = [
            player for player in game_round.spy_players if player.alive
        ]
        if len(alive_spy_players) == 1:
            points.update({alive_spy_players[0]: 1})
        return points


class Guard(Card):
    value = 1
    description = (
        "Name a non-Guard card and choose another player. If that player has that "
        "card, he or she is out of the round."
    )
    steps = (move.OpponentChoice, move.CardGuess)

    def play(self, owner: "RoundPlayer") -> MoveStepGenerator:
        self._validate_move(owner)
        opponent = (yield from move.OpponentChoice(owner, self)).choice
        if opponent is move.OpponentChoice.NO_TARGET:
            return ()

        guess = (yield from move.CardGuess(owner, self)).choice

        # execute move:
        results = []
        if guess == CardType(target_card := opponent.hand.card):
            results.append(move.CorrectCardGuess(owner, self, opponent, guess))
            opponent.eliminate()
            results.append(move.PlayerEliminated(owner, self, opponent, target_card))
        else:
            results.append(move.WrongCardGuess(owner, self, opponent, guess))

        return tuple(results)


class Priest(Card):
    value = 2
    description = "Look at another player's hand."
    steps = (move.OpponentChoice,)

    def play(self, owner: "RoundPlayer") -> MoveStepGenerator:
        self._validate_move(owner)
        opponent: RoundPlayer = (yield from move.OpponentChoice(owner, self)).choice
        if opponent is move.OpponentChoice.NO_TARGET:
            return ()
        return (move.ShowOpponentCard(owner, self, opponent, opponent.hand.card),)


class Baron(Card):
    value = 3
    description = (
        "You and another player secretly compare hands. The player with the lower "
        "value is out of the round. In case of a tie, nothing happens."
    )
    steps = (move.OpponentChoice,)

    def play(self, owner: "RoundPlayer") -> MoveStepGenerator:
        self._validate_move(owner)
        opponent = (yield from move.OpponentChoice(owner, self)).choice
        if opponent is move.OpponentChoice.NO_TARGET:
            return ()

        results = [
            move.CardComparison(
                owner, self, opponent, owner.hand.card, opponent.hand.card
            )
        ]
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
            last_card = eliminated.hand.card
            eliminated.eliminate()
            results.append(move.PlayerEliminated(owner, self, eliminated, last_card))

        return tuple(results)


class Handmaid(Card):
    value = 4
    description = "Until your next turn, you can't be targeted with any card."
    steps = ()

    def play(self, owner: "RoundPlayer") -> MoveStepGenerator:
        self._validate_move(owner)
        owner.immune = True
        return (move.ImmunityGranted(owner, self),)
        # noinspection PyUnreachableCode
        yield


class Prince(Card):
    value = 5
    description = (
        "Choose any player (including yourself) to discard his or her hand and draw a "
        "new card."
    )
    steps = (move.PlayerChoice,)

    def play(self, owner: "RoundPlayer") -> MoveStepGenerator:
        self._validate_move(owner)
        player = (yield from move.PlayerChoice(owner, self)).choice

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
    description = (
        "Draw 2 cards. Keep 1 card and put the other 2 on the bottom of the deck in "
        "any order."
    )
    steps = (move.ChooseOneCard, move.ChooseOrderForDeckBottom)
    cancellable = False

    def play(self, owner: "RoundPlayer") -> MoveStepGenerator:
        self._validate_move(owner)

        deck = owner.round.deck
        try:
            # don't take cards from deck yet so that if something raises, the deck
            # will remain intact
            options = (owner.hand.card, *deck.stack[-2:])
            choice = (yield from move.ChooseOneCard(owner, self, options)).choice
            owner.hand.replace(choice)
            leftover = set(options) - {choice}
            order = (
                yield from move.ChooseOrderForDeckBottom(owner, self, tuple(leftover))
            ).choice

            # actually take cards from deck
            for card in reversed(options[1:]):
                _ = deck.take()
                assert _ is card
            for card in order:
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
    description = "Trade hands with another player of your choice."
    steps = (move.OpponentChoice,)

    def play(self, owner: "RoundPlayer") -> MoveStepGenerator:
        self._validate_move(owner)
        opponent = (yield from move.OpponentChoice(owner, self)).choice
        if opponent is move.OpponentChoice.NO_TARGET:
            return ()
        opponent.hand.replace(owner.hand.replace(opponent.hand.card))
        return (move.CardsSwapped(owner, self, opponent),)


class Countess(Card):
    value = 8
    description = (
        "If you have this card and the Prince or King is in your hand, you must "
        "discard this card."
    )
    steps = ()

    def play(self, owner: "RoundPlayer") -> MoveStepGenerator:
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
    description = "If you discard this card, you are out of this round."
    steps = ()

    def play(self, owner: "RoundPlayer") -> MoveStepGenerator:
        self._validate_move(owner)
        return ()
        # noinspection PyUnreachableCode
        yield

    def discard_effects(self, owner: "RoundPlayer") -> Tuple[move.MoveResult, ...]:
        if owner.alive:
            last_card = owner.hand.card or self
            owner.eliminate()
            return (move.PlayerEliminated(owner, self, owner, last_card),)
        else:
            return ()


@functools.total_ordering
class CardType(enum.Enum):
    card_class: Type[Card]

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
        """Allows to get the CardType out of instances and other Card subclasses"""
        if isinstance(value, Card):
            for card_type in cls:
                if isinstance(value, card_type.card_class):
                    return card_type
        elif safe_is_subclass(value, Card):
            for card_type in cls:
                if issubclass(value, card_type.card_class):
                    return card_type
        return None

    def __repr__(self):
        return f"{type(self).__name__}.{self.name}"

    def __lt__(self, other):
        """
        Defines an ordering based on closeness to Princess Annette.

        Card types with higher values win over card types with lower values at the end
        of the round. With one exception: the princess herself always wins any other
        card.

        Thus ``card_type_1 < card_type_2`` means that a card of ``card_type_2`` would
        win over a card of ``card_type_1`` at the end of a round.
        """
        if not isinstance(other, CardType):
            raise TypeError(
                f"Can't compare with < a {type(self).__name__} "
                f"with a {type(other).__name__}"
            )
        return self.card_class.value < other.card_class.value
