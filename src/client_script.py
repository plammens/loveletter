import asyncio
import logging

from loveletter_multiplayer.client import client
from loveletter_multiplayer.logging import setup_logging


HOST = "127.0.0.1"
PORT = 48888


async def main():
    setup_logging(logging.DEBUG)

    tasks = []
    for i in range(10):
        tasks.append(asyncio.create_task(client(i, HOST, PORT)))

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
