import asyncio
import logging
from typing import Optional

from .json import MESSAGE_SEPARATOR, MessageDeserializer, MessageSerializer
from .message import Message


LOGGER = logging.getLogger(__name__)
LOGGING_LEVEL = logging.DEBUG // 2


async def send_message(
    writer: asyncio.StreamWriter, message: Message, serializer=MessageSerializer()
):
    LOGGER.log(
        LOGGING_LEVEL, "Sending to %s: %s", writer.get_extra_info("peername"), message
    )
    serialized = serializer.serialize(message)
    LOGGER.log(LOGGING_LEVEL, "Sending bytes: %s", serialized)
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
        LOGGER.log(LOGGING_LEVEL, "Received bytes: %s", serialized)
        message = deserializer.deserialize(serialized)
        LOGGER.log(LOGGING_LEVEL, "Parsed message: %s", message)
        return message
    except asyncio.IncompleteReadError as exc:
        if exc.partial == b"":
            return None  # end of stream
        else:
            LOGGER.error("Received incomplete message: %s", exc.partial)
            raise


class LoveletterMultiplayerError(RuntimeError):
    pass


class LogonError(LoveletterMultiplayerError):
    pass


class ProtocolError(LoveletterMultiplayerError):
    """Raised when one of the two sides didn't follow the protocol."""

    pass


class UnexpectedMessageError(ProtocolError):
    pass


class ConnectionClosedError(ProtocolError):
    pass


class RestartSession(BaseException):
    """
    Used to indicate that a client session should be restarted.

    Not a "normal" exception, hence this inherits from BaseException and not Exception
    (similarly to StopIteration, asyncio.CancelledError, etc.).
    """

    pass
