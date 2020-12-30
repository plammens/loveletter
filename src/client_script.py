"""
Sample script to run a few `LoveletterClient`s concurrently and play a game.
"""

import asyncio
import logging
from typing import List

import more_itertools

from loveletter_multiplayer import (
    GuestClient,
    HostClient,
    LoveletterClient,
    RemoteEvent,
)
from loveletter_multiplayer.logging import setup_logging
from loveletter_multiplayer.utils import StoppableAsyncioThread
from test_loveletter.utils import autofill_step


HOST = "127.0.0.1"
PORT = 48888


async def run_clients(clients: List[LoveletterClient]):
    host: HostClient = more_itertools.one(filter(lambda c: c.is_host, clients))  # noqa
    connections = await asyncio.gather(
        *[c.connect(HOST, PORT) for c in clients], return_exceptions=True
    )
    successful = (
        (client, conn)
        for client, conn in zip(clients, connections)
        if not isinstance(conn, BaseException)
    )
    clients, connections = map(list, more_itertools.unzip(successful))

    this_task = asyncio.current_task()

    async def watch_connections(conns: List[asyncio.Task]):
        try:
            await asyncio.gather(*conns)
        except Exception as e:
            this_task.get_coro().throw(e)

    watcher = asyncio.create_task(watch_connections(connections))
    try:
        await host.ready()
        games = await asyncio.gather(*(c.wait_for_game() for c in clients))
        gens = [g.track_remote() for g in games]

        e = None
        while True:
            filled = autofill_step(e)
            try:
                events = await asyncio.gather(*(g.asend(filled) for g in gens))
            except StopAsyncIteration:
                break
            e = next(e for e in events if not isinstance(e, RemoteEvent))

        print("Game results:")
        print("State:", host.game.state)
        print("Points:", host.game.points)

        await host.send_shutdown()
        await watcher
    finally:
        watcher.cancel()


def main():
    setup_logging(logging.DEBUG)
    host = HostClient("Host")
    clients = [host]
    usernames = ["Alice", "Bob", "Charlie", "Eve"]
    clients.extend(GuestClient(username) for username in usernames)
    clients_thread = StoppableAsyncioThread(
        name="ClientsThread", target=run_clients, args=(clients,)
    )
    clients_thread.start()
    clients_thread.join()


if __name__ == "__main__":
    main()
