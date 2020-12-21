import dataclasses
import enum
import json
from typing import Any, Dict

from . import message as msg
from .message import Message


class MessageSerializer(json.JSONEncoder):
    """
    Serializes :class:`Message` objects as byte sequences ready for transmission.

    Enum members are serialized using their values.
    """

    def __init__(self):
        super().__init__(ensure_ascii=False, indent=None, separators=(",", ":"))

    def serialize(self, message: Message) -> bytes:
        json_string = self.encode(message)
        return json_string.encode()

    def default(self, o: Any) -> Any:
        if isinstance(o, Message):
            return self._make_serializable(o)
        elif isinstance(o, enum.Enum):
            return o.value
        else:
            return super().default(o)

    @staticmethod
    def _make_serializable(message: Message):
        d = dataclasses.asdict(message)
        d["type"] = message.type.value
        return d


class MessageDeserializer(json.JSONDecoder):
    """
    Deserializes the results of :class:`MessageSerializer` into an equivalent Message.
    """

    def __init__(self):
        super().__init__(object_hook=self._reconstruct_message)

    def deserialize(self, message: bytes) -> Message:
        if not message:
            return message
        # noinspection PyTypeChecker
        return self.decode(message.decode())

    _type_map = {
        Message.Type.ERROR: msg.ErrorMessage,
    }

    @classmethod
    def _reconstruct_message(cls, json_dict: Dict[str, Any]):
        # get the enum member from the value
        message_type = Message.Type(json_dict.pop("type"))
        message_class = cls._type_map[message_type]
        # noinspection PyArgumentList
        # dataclass handles instantiation with keyword arguments
        # (value to enum member conversion will be done by EnumPostInitMixin):
        return message_class(**json_dict)
