import abc
import copy
import dataclasses
import enum
import json
from typing import Any, ClassVar, Dict, List, Optional, Tuple, Type, Union

from loveletter.cardpile import CardPile
from loveletter.cards import Card
from loveletter.game import Game
from loveletter.gameevent import GameInputRequest
from loveletter.round import Round
from loveletter.roundplayer import RoundPlayer
from loveletter.utils import collect_subclasses
from . import message as msg
from .message import Message
from ..utils import full_qualname, import_from_qualname, instance_attributes


JsonType = Union[None, bool, int, float, str, Dict[str, "JsonType"], List["JsonType"]]
SerializableObject = Dict[str, Any]

MESSAGE_TYPE_KEY = "_msgtype_"
DATACLASS_KEY = "_dataclass_"
FALLBACK_KEY = "_class_"
FALLBACK_TYPES = (GameInputRequest, CardPile, Card)


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
        elif (placeholder_type := Placeholder.get_placeholder_type(o)) is not None:
            return placeholder_type.from_game_obj(o).to_serializable()
        elif isinstance(o, enum.Enum):
            return o.value
        elif isinstance(o, FALLBACK_TYPES):
            return self._make_serializable_fallback(o)
        else:
            return super().default(o)

    @staticmethod
    def _make_dataclass_serializable(obj):
        cls = type(obj)
        fields = {DATACLASS_KEY: full_qualname(cls)}
        for f in dataclasses.fields(obj):
            fields[f.name] = getattr(obj, f.name)
        return fields

    @staticmethod
    def _make_message_serializable(message: Message):
        # special case to save some bytes
        d = MessageSerializer._make_dataclass_serializable(message)
        del d[DATACLASS_KEY]
        return {MESSAGE_TYPE_KEY: message.type} | d

    @staticmethod
    def _make_serializable_fallback(obj):
        return {FALLBACK_KEY: full_qualname(type(obj))} | obj.__dict__


class MessageDeserializer(json.JSONDecoder):
    """
    Deserializes the results of :class:`MessageSerializer` into an equivalent Message.
    """

    def __init__(self, game: Optional[Game] = None, fill_placeholders=True):
        """
        Construct a configured message deserializer.

        :param game: Game used as the context to reconstruct unserializable game
                     objects.
        :param fill_placeholders: Whether to "evaluate" the placeholders as part of the
                                  deserialization. If False, the placeholder objects
                                  will be left as-is and the caller is responsible to
                                  fill them when appropriate.
        """
        super().__init__(object_hook=self._reconstruct_object)
        self.game = game
        self.fill_placeholders = fill_placeholders

    def deserialize(self, message: bytes) -> Message:
        # noinspection PyTypeChecker
        return self.decode(message.rstrip(b"\0").decode())

    _type_map = {
        cls.type: cls
        for cls in collect_subclasses(Message, msg)
        if hasattr(cls, "type")  # only concrete subclasses
    }

    def _reconstruct_object(self, json_obj: dict) -> Any:
        if dataclass_path := json_obj.pop(DATACLASS_KEY, None):
            return self._reconstruct_dataclass_obj(dataclass_path, json_obj)
        elif message_type := json_obj.pop(MESSAGE_TYPE_KEY, None):
            return self._reconstruct_message(message_type, json_obj)
        elif Placeholder.is_placeholder(json_obj):
            return self._reconstruct_from_placeholder(json_obj)
        elif class_path := json_obj.pop(FALLBACK_KEY, None):
            return self._reconstruct_fallback(class_path, json_obj)
        else:
            return json_obj

    @staticmethod
    def _reconstruct_message(
        message_type: Message.Type, json_obj: SerializableObject
    ) -> Message:
        message_type = Message.Type(message_type)
        message_class = MessageDeserializer._type_map[message_type]
        return message_class(**json_obj)

    @staticmethod
    def _reconstruct_dataclass_obj(
        dataclass_path: str, json_obj: SerializableObject
    ) -> Any:
        dataclass = import_from_qualname(dataclass_path)
        return dataclass(**json_obj)

    def _reconstruct_from_placeholder(self, json_obj: SerializableObject):
        if self.game is None:
            raise ValueError("Can't fill placeholder without a game context")
        placeholder = Placeholder.from_serializable(json_obj)
        return placeholder.fill(self.game) if self.fill_placeholders else placeholder

    @staticmethod
    def _reconstruct_fallback(class_path: str, json_obj: SerializableObject) -> Any:
        cls = import_from_qualname(class_path)
        obj = cls.__new__(cls)
        obj.__dict__.update(json_obj)
        return obj


class Placeholder(metaclass=abc.ABCMeta):
    """
    A placeholder serialization and deserialization protocol.

    Some game objects can't be serialized or would be too expensive to serialize and
    deserialize every time. Instead, a placeholder can be used: each client has a local
    copy of the game (the "game context"), and when a message that includes such an
    object has to be sent, it is replaced by a placeholder, and on the other side of the
    conversation, the placeholder is replaced again with the local copy of the object
    it represents (by fetching it from the game context).
    """

    KEY = "_placeholder_"

    #: types of objects that will be mapped to this placeholder type
    game_obj_types: ClassVar[Tuple[Type, ...]]

    def __init__(self, data: SerializableObject):
        """
        Make a placeholder of this type.

        :param data: Extra data needed to fill the placeholder during deserialization.
        """
        self.data = data

    _types: List[Type["Placeholder"]] = []

    @staticmethod
    def get_placeholder_type(obj) -> Optional[Type["Placeholder"]]:
        """Get the placeholder type for an object, or None if none can be used."""
        for cls in Placeholder._types:
            if isinstance(obj, cls.game_obj_types):
                return cls
        else:
            return None

    @classmethod
    def from_game_obj(cls, game_obj) -> "Placeholder":
        """Construct a placeholder of this type for the given game object."""
        if not isinstance(game_obj, cls.game_obj_types):
            raise TypeError(f"Can't use {cls.__name__} for {game_obj}")
        return cls(cls._extra_data(game_obj))

    def to_serializable(self) -> SerializableObject:
        """Return a JSON to_serializable version of the placeholder."""
        return {Placeholder.KEY: self.to_type_id()} | self.data

    @staticmethod
    def is_placeholder(json_obj: SerializableObject):
        """Check whether the given JSON object represents a placeholder."""
        return Placeholder.KEY in json_obj

    @staticmethod
    def from_serializable(serializable: SerializableObject):
        """Reconstruct the placeholder object given its serializable form."""
        cls = Placeholder.from_type_id(serializable.pop(Placeholder.KEY))
        return cls(serializable)

    @abc.abstractmethod
    def fill(self, game: Game) -> Any:
        """Fill a placeholder of this type given the game context."""
        pass

    @staticmethod
    def register(cls):
        """Class decorator to register a placeholder type."""
        if not issubclass(cls, Placeholder) or not hasattr(cls, "game_obj_types"):
            raise TypeError(cls)
        Placeholder._types.append(cls)
        return cls

    @classmethod
    def to_type_id(cls) -> int:
        """A numeric ID for this placeholder type."""
        return Placeholder._types.index(cls)

    @staticmethod
    def from_type_id(type_id: int) -> Type["Placeholder"]:
        """Get the placeholder type from its numeric ID."""
        return Placeholder._types[type_id]

    @classmethod
    def _extra_data(cls, game_obj) -> SerializableObject:
        """Subclasses override this to add extra data needed to reconstruct the obj."""
        return {}


@Placeholder.register
class GamePlaceholder(Placeholder):
    game_obj_types = (Game,)

    def fill(self, game: Game):
        return game


@Placeholder.register
class RoundPlaceholder(Placeholder):
    game_obj_types = (Round,)

    def fill(self, game: Game):
        return game.current_round


class PlayerPlaceHolder(Placeholder, metaclass=abc.ABCMeta):
    @classmethod
    def _extra_data(cls, game_obj) -> SerializableObject:
        return {"id": game_obj.id}


@Placeholder.register
class GamePlayerPlaceholder(PlayerPlaceHolder):
    game_obj_types = (Game.Player,)

    def fill(self, game: Game):
        return game.players[self.data["id"]]


@Placeholder.register
class RoundPlayerPlaceholder(PlayerPlaceHolder):
    game_obj_types = (RoundPlayer,)

    def fill(self, game: Game):
        return game.current_round.players[self.data["id"]]


def fill_placeholders(obj, game: Game):
    """
    Recursively replace all placeholder sub-objects by filling them.

    :return: Shallow copy of the object with filled placeholders, or the same object
             unmodified if no placeholders were found.
    """

    if isinstance(obj, Placeholder):
        return obj.fill(game)
    elif isinstance(obj, (tuple, list, set)):
        filled = type(obj)(fill_placeholders(x, game) for x in obj)
        modified = not all(x is y for x, y in zip(obj, filled))
        return filled if modified else obj
    elif isinstance(obj, dict):
        # noinspection PyArgumentList
        filled = type(obj)(
            (fill_placeholders(k, game), fill_placeholders(v, game))
            for k, v in obj.items()
        )
        modified = not all(
            k1 is k2 and v1 is v2
            for (k1, v1), (k2, v2) in zip(obj.items(), filled.items())
        )
        return filled if modified else obj
    else:
        return _fill_placeholders_attrs(obj, game)


def _fill_placeholders_attrs(obj, game):
    filled_values = {}
    for name, attr in instance_attributes(obj).items():
        filled = fill_placeholders(attr, game)
        if filled is not attr:
            filled_values[name] = filled
    if not filled_values:
        return obj

    if dataclasses.is_dataclass(obj):
        return dataclasses.replace(obj, **filled_values)
    else:
        obj_copy = copy.copy(obj)
        for name, value in filled_values.items():
            setattr(obj_copy, name, value)
        return obj_copy
