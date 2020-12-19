import loveletter.game
from loveletter.game import Game, GameState
from loveletter.gameevent import GameEvent, GameInputRequest
from loveletter.gamenode import GameNodeState
from loveletter.round import RoundState
from test_loveletter.utils import autofill_step


def test_eventGenerator_yieldsCorrectTypes(new_game: Game):
    def is_game_start(e: GameEvent):
        return isinstance(e, GameState) and e.type == GameState.Type.ROUND

    def is_round_end(e: GameEvent):
        return isinstance(e, GameNodeState) and e.type == RoundState.Type.ROUND_END

    game_generator = new_game.play()
    event = next(game_generator)
    # all input requests until the round starts
    while not is_game_start(event):
        assert isinstance(event, GameInputRequest)
        event = game_generator.send(autofill_step(event))

    # until the round ends, repeat: round -> player move choice -> move steps -> results
    while True:
        # starts with round event
        assert isinstance(event, loveletter.game.PlayingRound)

        # now all of the round events
        event = next(game_generator)
        while not is_round_end(event):
            event = game_generator.send(autofill_step(event))

        # advance (perhaps finish the game)
        try:
            event = next(game_generator)
        except StopIteration as e:
            results = e.value
            break

    assert tuple(r.type for r in results) == (GameNodeState.Type.END,)
