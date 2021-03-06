import pytest
import pytest_cases

from loveletter.game import Game
from loveletter.round import Round
from test_loveletter.unit.test_game_cases import PLAYER_LIST_CASES


@pytest_cases.fixture()
@pytest.mark.parametrize("num_players", (2, 3, 4), ids=lambda n: f"Round({n})")
def new_round(num_players) -> Round:
    return Round(num_players)


@pytest_cases.fixture()
def started_round(new_round: Round):
    new_round.start()
    return new_round


# todo: ongoing_round with autoplay


@pytest_cases.fixture()
def current_player(started_round):
    return started_round.current_player


game_round = pytest_cases.fixture_union("game_round", [new_round, started_round])


@pytest_cases.fixture()
@pytest.mark.parametrize(
    "players", argvalues=PLAYER_LIST_CASES, ids=lambda x: f"Game(<{len(x)} players>)"
)
def new_game(players) -> Game:
    return Game(players)


@pytest_cases.fixture()
def started_game(new_game: Game) -> Game:
    new_game.start()
    return new_game
