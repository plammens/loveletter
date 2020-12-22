import asyncio
from typing import Optional

from .json import MessageDeserializer
from .message import Message


MESSAGE_SEPARATOR = b"\0"


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
        return deserializer.deserialize(serialized)
    except asyncio.IncompleteReadError as exc:
        if exc.partial == b"":
            return None  # end of stream
        else:
            raise
