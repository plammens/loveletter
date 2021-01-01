import abc
import dataclasses
import enum
import json
from typing import Any, ClassVar, Dict, List, Optional, Tuple, Type, Union

import more_itertools as mitt
import valid8

from loveletter.cardpile import CardPile
from loveletter.cards import Card
from loveletter.game import Game
from loveletter.gameevent import GameInputRequest
from loveletter.round import Round
from loveletter.roundplayer import RoundPlayer
from loveletter.utils import safe_is_subclass
from .message import Message
from ..utils import (
    full_qualname,
    import_from_qualname,
    instance_attributes,
    recursive_apply,
)


JsonType = Union[None, bool, int, float, str, Dict[str, "JsonType"], List["JsonType"]]
SerializableObject = Dict[str, Any]

MESSAGE_SEPARATOR = b"\0"

# noinspection SpellCheckingInspection
MESSAGE_TYPE_KEY = "_msgtype_"
DATACLASS_KEY = "_dataclass_"
ENUM_KEY = "_enum_"
SET_KEY = "_set_"
TYPE_KEY = "_type_"
VALID8_KEY = "_valid8_"
FALLBACK_KEY = "_class_"
FALLBACK_TYPES = (GameInputRequest, CardPile, Card, RoundPlayer.Hand)


class MessageSerializer(json.JSONEncoder):
    """
    Serializes :class:`Message` objects as byte sequences ready for transmission.

    Enum members are serialized using their values.
    """

    def __init__(self):
        super().__init__(ensure_ascii=False, indent=None, separators=(",", ":"))

    def encode(self, o: Any) -> str:
        o = self._prepare_dicts(o)
        return super().encode(o)

    def _prepare_dicts(self, o):
        return recursive_apply(
            o,
            predicate=lambda x: isinstance(x, dict),
            function=lambda d: {self.encode(k): v for k, v in d.items()},
        )

    def serialize(self, message: Message) -> bytes:
        json_string = self.encode(message)
        return json_string.encode() + MESSAGE_SEPARATOR

    def default(self, o: Any) -> JsonType:
        if isinstance(o, dict):
            return {self.encode(k): v for k, v in o.items()}
        elif isinstance(o, enum.Enum):
            return self._make_enum_member_serializable(o)
        elif isinstance(o, (set, frozenset)):
            return self._make_set_serializable(o)
        elif isinstance(o, type):
            if safe_is_subclass(o, valid8.ValidationError):
                return self._make_valid8_serializable(o)
            else:
                return self._make_type_serializable(o)
        elif isinstance(o, Message):
            return self._make_message_serializable(o)
        elif dataclasses.is_dataclass(o) and not isinstance(o, type):
            return self._make_dataclass_serializable(o)
        elif (placeholder_type := Placeholder.get_placeholder_type(o)) is not None:
            return placeholder_type.from_game_obj(o).to_serializable()
        elif isinstance(o, FALLBACK_TYPES):
            return self._make_serializable_fallback(o)
        else:
            return super().default(o)

    @staticmethod
    def _make_enum_member_serializable(member) -> SerializableObject:
        return {ENUM_KEY: full_qualname(type(member)), "value": member.value}

    @staticmethod
    def _make_set_serializable(o) -> SerializableObject:
        return {SET_KEY: full_qualname(type(o)), "elements": list(o)}

    @staticmethod
    def _make_type_serializable(o) -> SerializableObject:
        return {TYPE_KEY: full_qualname(o)}

    @staticmethod
    def _make_valid8_serializable(
        error_type: Type[valid8.ValidationError],
    ) -> SerializableObject:
        qualname = full_qualname(error_type)
        extra = {}
        try:
            import_from_qualname(qualname)
        except ImportError:
            # this is a dynamically generated type
            bases = error_type.__bases__
            base = mitt.first(
                b for b in bases if safe_is_subclass(b, valid8.ValidationError)
            )
            additional = mitt.first(
                b for b in bases if b is not base and safe_is_subclass(b, Exception)
            )
            qualname = full_qualname(base)
            extra["additional"] = full_qualname(additional)
        return {VALID8_KEY: qualname} | extra

    @staticmethod
    def _make_dataclass_serializable(obj) -> SerializableObject:
        cls = type(obj)
        fields = {DATACLASS_KEY: full_qualname(cls)}
        for f in dataclasses.fields(obj):
            fields[f.name] = getattr(obj, f.name)
        return fields

    @staticmethod
    def _make_message_serializable(message: Message) -> SerializableObject:
        # special case to save some bytes
        d = MessageSerializer._make_dataclass_serializable(message)
        del d[DATACLASS_KEY]
        # The Message hierarchy has EnumPostInitMixin which takes care of enum members,
        # so we can reduce the size of the message by just sending the value
        d = {MESSAGE_TYPE_KEY: message.to_type_id()} | d
        for field in dataclasses.fields(message):
            if isinstance(field.type, enum.EnumMeta):
                d[field.name] = getattr(message, field.name).value
        return d

    @staticmethod
    def _make_serializable_fallback(obj) -> SerializableObject:
        return {FALLBACK_KEY: full_qualname(type(obj))} | instance_attributes(obj)


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
        return self.decode(message.rstrip(MESSAGE_SEPARATOR).decode())

    def _reconstruct_object(self, json_obj: dict) -> Any:
        if (enum_path := json_obj.pop(ENUM_KEY, None)) is not None:
            return self._reconstruct_enum_member(enum_path, json_obj)
        elif (set_type_path := json_obj.pop(SET_KEY, None)) is not None:
            return self._reconstruct_set(set_type_path, json_obj)
        elif (class_path := json_obj.pop(TYPE_KEY, None)) is not None:
            return self._reconstruct_type(class_path)
        elif (class_path := json_obj.pop(VALID8_KEY, None)) is not None:
            return self._reconstruct_valid8(class_path, json_obj)
        elif (dataclass_path := json_obj.pop(DATACLASS_KEY, None)) is not None:
            return self._reconstruct_dataclass_obj(dataclass_path, json_obj)
        elif (message_type := json_obj.pop(MESSAGE_TYPE_KEY, None)) is not None:
            return self._reconstruct_message(message_type, json_obj)
        elif Placeholder.is_placeholder(json_obj):
            return self._reconstruct_from_placeholder(json_obj)
        elif (class_path := json_obj.pop(FALLBACK_KEY, None)) is not None:
            return self._reconstruct_fallback(class_path, json_obj)
        else:
            # regular dict
            return {self.decode(k): v for k, v in json_obj.items()}

    @staticmethod
    def _reconstruct_enum_member(
        enum_path: str, json_obj: SerializableObject
    ) -> enum.Enum:
        enum_class = import_from_qualname(enum_path)
        return enum_class(json_obj["value"])

    @staticmethod
    def _reconstruct_set(set_type_path: str, json_obj: SerializableObject) -> set:
        set_type = import_from_qualname(set_type_path)
        return set_type(json_obj["elements"])

    @staticmethod
    def _reconstruct_type(class_path: str) -> type:
        return import_from_qualname(class_path)

    @staticmethod
    def _reconstruct_valid8(
        class_path: str, json_obj: SerializableObject
    ) -> Type[valid8.ValidationError]:
        import valid8.entry_points

        base = import_from_qualname(class_path)
        if (additional := json_obj.pop("additional", None)) is not None:
            additional = import_from_qualname(additional)
            return valid8.entry_points.add_base_type_dynamically(base, additional)
        else:
            return base

    @staticmethod
    def _reconstruct_valid8(
        class_path: str, json_obj: SerializableObject
    ) -> Type[valid8.ValidationError]:
        import valid8.entry_points

        base = import_from_qualname(class_path)
        if (additional := json_obj.pop("additional", None)) is not None:
            additional = import_from_qualname(additional)
            return valid8.entry_points.add_base_type_dynamically(base, additional)
        else:
            return base

    def _reconstruct_message(
        self, message_type: int, json_obj: SerializableObject
    ) -> Message:
        message_class = Message.from_type_id(message_type)
        return self._gcd_reconstruct_dataclass_obj(message_class, json_obj)

    def _reconstruct_dataclass_obj(
        self, dataclass_path: str, json_obj: SerializableObject
    ) -> Any:
        dataclass = import_from_qualname(dataclass_path)
        return self._gcd_reconstruct_dataclass_obj(dataclass, json_obj)

    @staticmethod
    def _gcd_reconstruct_dataclass_obj(dataclass, json_obj: SerializableObject):
        fields = dataclasses.fields(dataclass)
        init_fields = {f.name: json_obj[f.name] for f in fields if f.init}
        other_fields = {n: json_obj[n] for n in set(json_obj) - set(init_fields)}
        instance = dataclass(**init_fields)
        try:
            for name, value in other_fields.items():
                setattr(instance, name, value)
        except dataclasses.FrozenInstanceError:
            for name, value in other_fields.items():
                object.__setattr__(instance, name, value)
        return instance

    def _reconstruct_from_placeholder(self, json_obj: SerializableObject):
        if self.game is None:
            raise ValueError("Can't fill placeholder without a game context")
        placeholder = Placeholder.from_serializable(json_obj)
        return placeholder.fill(self.game) if self.fill_placeholders else placeholder

    @staticmethod
    def _reconstruct_fallback(class_path: str, json_obj: SerializableObject) -> Any:
        cls = import_from_qualname(class_path)
        obj = object.__new__(cls)
        for name, value in json_obj.items():
            object.__setattr__(obj, name, value)
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
    return recursive_apply(
        obj,
        predicate=lambda x: isinstance(x, Placeholder),
        function=lambda placeholder: placeholder.fill(game),
    )
