import dataclasses
import enum
import json
from typing import Any, Dict

from loveletter.utils import collect_subclasses
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
        return json_string.encode() + b"\0"

    def default(self, o: Any) -> Any:
        if isinstance(o, Message):
            return self._make_serializable(o)
        elif isinstance(o, enum.Enum):
            return o.value
        else:
            return super().default(o)

    @staticmethod
    def _make_serializable(message: Message):
        return {"type": message.type.value} | dataclasses.asdict(message)


class MessageDeserializer(json.JSONDecoder):
    """
    Deserializes the results of :class:`MessageSerializer` into an equivalent Message.
    """

    def __init__(self):
        super().__init__(object_hook=self._reconstruct_message)

    def deserialize(self, message: bytes) -> Message:
        # noinspection PyTypeChecker
        return self.decode(message.rstrip(b"\0").decode())

    _type_map = {cls.type: cls for cls in collect_subclasses(Message, msg)}

    @classmethod
    def _reconstruct_message(cls, json_dict: Dict[str, Any]):
        # get the enum member from the value
        message_type = Message.Type(json_dict.pop("type"))
        message_class = cls._type_map[message_type]
        # noinspection PyArgumentList
        # dataclass handles instantiation with keyword arguments
        # (value to enum member conversion will be done by EnumPostInitMixin):
        return message_class(**json_dict)
