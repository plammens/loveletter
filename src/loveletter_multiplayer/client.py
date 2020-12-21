import asyncio
import logging

from loveletter_multiplayer.logging import setup_logging
from loveletter_multiplayer.message import MessageDeserializer

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 48888


deserializer = MessageDeserializer()


async def client(i):
    reader, writer = await asyncio.open_connection(host=HOST, port=PORT)
    logger.info(f"Client {i} connected to {writer.get_extra_info('peername')}")

    message = await reader.read()
    if message:
        message = deserializer.deserialize(message)
        logger.debug(f"Client {i} received: {message}")

    writer.close()
    await writer.wait_closed()


async def main():
    setup_logging(logging.DEBUG)

    tasks = []
    for i in range(10):
        tasks.append(asyncio.create_task(client(i)))

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
