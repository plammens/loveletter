import dataclasses
import enum
import json
from typing import Any, Union

from loveletter.utils import collect_subclasses
from . import message as msg
from .message import Message
from ..utils import import_from_qualname


MESSAGE_TYPE_KEY = "_msgtype_"
DATACLASS_KEY = "_dataclass_"

JsonType = Union[bool, int, float, str, dict, list, tuple, None]


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

    def default(self, o: Any) -> JsonType:
        if isinstance(o, Message):
            return self._make_message_serializable(o)
        elif dataclasses.is_dataclass(o) and not isinstance(o, type):
            return self._make_dataclass_serializable(o)
        elif isinstance(o, enum.Enum):
            return o.value
        else:
            return super().default(o)

    @staticmethod
    def _make_dataclass_serializable(obj):
        cls = type(obj)
        fields = {DATACLASS_KEY: ".".join((cls.__module__, cls.__qualname__))}
        for f in dataclasses.fields(obj):
            fields[f.name] = getattr(obj, f.name)
        return fields

    @staticmethod
    def _make_message_serializable(message: Message):
        # special case to save some bytes
        d = MessageSerializer._make_dataclass_serializable(message)
        del d[DATACLASS_KEY]
        return {MESSAGE_TYPE_KEY: message.type} | d


class MessageDeserializer(json.JSONDecoder):
    """
    Deserializes the results of :class:`MessageSerializer` into an equivalent Message.
    """

    def __init__(self):
        super().__init__(object_hook=self._reconstruct_object)

    def deserialize(self, message: bytes) -> Message:
        # noinspection PyTypeChecker
        return self.decode(message.rstrip(b"\0").decode())

    _type_map = {
        cls.type: cls
        for cls in collect_subclasses(Message, msg)
        if hasattr(cls, "type")  # only concrete subclasses
    }

    @staticmethod
    def _reconstruct_object(json_obj: dict) -> Any:
        if dataclass_path := json_obj.pop(DATACLASS_KEY, None):
            dataclass = import_from_qualname(dataclass_path)
            return dataclass(**json_obj)
        elif message_type := json_obj.pop(MESSAGE_TYPE_KEY, None):
            message_type = Message.Type(message_type)
            message_class = MessageDeserializer._type_map[message_type]
            return message_class(**json_obj)
        else:
            return json_obj
