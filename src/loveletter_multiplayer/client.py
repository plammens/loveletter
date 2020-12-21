import asyncio
import logging

from loveletter_multiplayer.message import MessageDeserializer

logger = logging.getLogger(__name__)

deserializer = MessageDeserializer()


async def client(i, host, port):
    reader, writer = await asyncio.open_connection(host=host, port=port)
    logger.info(f"Client {i} connected to {writer.get_extra_info('peername')}")

    message = await reader.read()
    if message:
        message = deserializer.deserialize(message)
        logger.debug(f"Client {i} received: {message}")

    writer.close()
    await writer.wait_closed()
