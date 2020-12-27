import asyncio
import logging

from loveletter_multiplayer.client import LoveletterClient
from loveletter_multiplayer.logging import setup_logging
from loveletter_multiplayer.utils import StoppableAsyncioThread


HOST = "127.0.0.1"
PORT = 48888


async def run_clients(clients):
    connections = await asyncio.gather(*[c.connect(HOST, PORT) for c in clients])
    await asyncio.gather(*connections, return_exceptions=True)


def main():
    setup_logging(logging.DEBUG)
    host = LoveletterClient("Host", is_host=True)
    clients = [host]
    usernames = ["Alice", "Bob", "Charlie", "Eve"]
    clients.extend(LoveletterClient(username) for username in usernames)
    clients_thread = StoppableAsyncioThread(
        name="ClientsThread", target=run_clients, args=(clients,)
    )
    clients_thread.start()
    clients_thread.join()


if __name__ == "__main__":
    main()
