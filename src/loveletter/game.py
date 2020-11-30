from typing import Sequence

import valid8

from loveletter.player import Player


class Game:
    players: Sequence[Player]

    def __init__(self, num_players: int):
        valid8.validate(
            "num_players", num_players, instance_of=int, min_value=2, max_value=4
        )
        self.players = [Player(self, i) for i in range(num_players)]
