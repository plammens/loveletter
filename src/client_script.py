import asyncio
import logging

from loveletter_multiplayer.client import LoveletterClient
from loveletter_multiplayer.logging import setup_logging


HOST = "127.0.0.1"
PORT = 48888


async def start_clients(clients):
    tasks = [c.connect(HOST, PORT) for c in clients]
    await asyncio.gather(*tasks, return_exceptions=True)


def main():
    usernames = ["Alice", "Bob", "Charlie", "Anakhand", "Eve"]
    setup_logging(logging.DEBUG)
    clients = [LoveletterClient(username) for username in usernames]
    asyncio.run(start_clients(clients))


if __name__ == "__main__":
    main()
