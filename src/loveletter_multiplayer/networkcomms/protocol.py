import asyncio
import logging
from typing import Optional

from . import MessageSerializer
from .json import MessageDeserializer
from .message import Message


logger = logging.getLogger(__name__)


MESSAGE_SEPARATOR = b"\0"


async def send_message(
    writer: asyncio.StreamWriter, message: Message, serializer=MessageSerializer()
):
    logger.debug("Sending to %s: %s", writer.get_extra_info("peername"), message)
    serialized = serializer.serialize(message)
    logger.debug("Sending bytes: %s", serialized)
    writer.write(serialized)
    await writer.drain()


async def receive_message(
    reader: asyncio.StreamReader, deserializer=MessageDeserializer()
) -> Optional[Message]:
    """
    Read a single message from a stream.

    If there is nothing else in the stream (i.e. the connection has been closed),
    returns None. If only a partial message could be read, raises an
    IncompleteReadError.

    :param reader: Stream reader from which to get a message.
    :param deserializer: Deserializer object to construct a message object out of the
                         bytes sequence.
    :return: The read message if any, None if at EOT.
    """
    try:
        serialized = await reader.readuntil(MESSAGE_SEPARATOR)
        logger.debug("Received bytes: %s", serialized)
        message = deserializer.deserialize(serialized)
        logger.debug("Parsed message: %s", message)
        return message
    except asyncio.IncompleteReadError as exc:
        if exc.partial == b"":
            return None  # end of stream
        else:
            logger.error("Received incomplete message: %s", exc.partial)
            raise
