import json
from copy import copy
from enum import Enum
from hashlib import sha256
from json import JSONDecodeError
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Literal,
    Optional,
    Type,
    Union,
)

from pydantic import BaseModel, Extra, Field, validator
from typing_extensions import TypeAlias

from .abstract import BaseContent
from .execution.instance import InstanceContent
from .execution.program import ProgramContent
from .item_hash import ItemHash, ItemType


class Chain(str, Enum):
    """Supported chains"""

    AVAX = "AVAX"
    BSC = "BSC"
    CSDK = "CSDK"
    DOT = "DOT"
    ETH = "ETH"
    NEO = "NEO"
    NULS = "NULS"
    NULS2 = "NULS2"
    SOL = "SOL"
    TEZOS = "TEZOS"


class HashType(str, Enum):
    """Supported hash functions"""

    sha256 = "sha256"


class MessageType(str, Enum):
    """Message types supported by Aleph"""

    post = "POST"
    aggregate = "AGGREGATE"
    store = "STORE"
    program = "PROGRAM"
    instance = "INSTANCE"
    forget = "FORGET"


class MongodbId(BaseModel):
    """PyAleph returns an internal MongoDB id"""

    oid: str = Field(alias="$oid")

    class Config:
        extra = Extra.forbid


class ChainRef(BaseModel):
    """Some POST messages have a 'ref' field referencing other content"""

    chain: Chain
    channel: Optional[str] = None
    item_content: str
    item_hash: ItemHash
    item_type: ItemType
    sender: str
    signature: str
    time: float
    type = "POST"


class MessageConfirmationHash(BaseModel):
    binary: str = Field(alias="$binary")
    type: str = Field(alias="$type")

    class Config:
        extra = Extra.forbid


class MessageConfirmation(BaseModel):
    """Format of the result when a message has been confirmed on a blockchain"""

    chain: Chain
    height: int
    hash: Union[str, MessageConfirmationHash]
    # These two optional fields are introduced in recent versions of CCNs. They should
    # remain optional until the corresponding CCN upload (0.4.0) is widely uploaded.
    time: Optional[float] = None
    publisher: Optional[str] = Field(
        default=None, description="The address that published the transaction."
    )

    class Config:
        extra = Extra.forbid


class AggregateContentKey(BaseModel):
    name: str

    class Config:
        extra = Extra.forbid


class PostContent(BaseContent):
    """Content of a POST message"""

    content: Optional[Any] = Field(
        default=None, description="User-generated content of a POST message"
    )
    ref: Optional[Union[str, ChainRef]] = Field(
        default=None,
        description="Other message referenced by this one",
    )
    type: str = Field(description="User-generated 'content-type' of a POST message")

    @validator("type")
    def check_type(cls, v, values):
        if v == "amend":
            ref = values.get("ref")
            if not ref:
                raise ValueError("A 'ref' is required for POST type 'amend'")
        return v

    class Config:
        extra = Extra.forbid


class AggregateContent(BaseContent):
    """Content of an AGGREGATE message"""

    key: Union[str, AggregateContentKey] = Field(
        description="The aggregate key can be either a string of a dict containing the key in field 'name'"
    )
    content: Dict = Field(description="The content of an aggregate must be a dict")

    class Config:
        extra = Extra.forbid


class StoreContent(BaseContent):
    """Content of a STORE message"""

    item_type: ItemType
    item_hash: ItemHash
    size: Optional[int] = None  # Generated by the node on storage
    content_type: Optional[str] = None  # Generated by the node on storage
    ref: Optional[str] = None
    domains: Optional[List[str]] = Field(
        description="Custom domains to link. @see https://docs.aleph.im/computing/domains/ fore more details",
    )

    class Config:
        extra = Extra.allow


class ForgetContent(BaseContent):
    """Content of a FORGET message"""

    hashes: List[ItemHash]
    aggregates: List[ItemHash] = Field(default_factory=list)
    reason: Optional[str] = None

    def __hash__(self):
        # Convert List to Tuple for hashing
        values = copy(self.__dict__)
        values["hashes"] = tuple(values["hashes"])
        return hash(self.__class__) + hash(values.values())


class BaseMessage(BaseModel):
    """Base template for all messages"""

    id_: Optional[MongodbId] = Field(
        alias="_id",
        default=None,
        description="MongoDB metadata",
        exclude=True,
    )
    chain: Chain = Field(description="Blockchain used for this message")

    sender: str = Field(description="Address of the sender")
    type: MessageType = Field(description="Type of message (POST, AGGREGATE or STORE)")
    channel: Optional[str] = Field(
        default=None,
        description="Channel of the message, one application ideally has one channel",
    )
    confirmations: Optional[List[MessageConfirmation]] = Field(
        default=None, description="Blockchain confirmations of the message"
    )
    confirmed: Optional[bool] = Field(
        default=None,
        description="Indicates that the message has been confirmed on a blockchain",
    )
    signature: Optional[str] = Field(
        description="Cryptographic signature of the message by the sender"
    )
    size: Optional[int] = Field(
        default=None, description="Size of the content"
    )  # Almost always present
    time: float = Field(description="Unix timestamp when the message was published")
    item_type: ItemType = Field(description="Storage method used for the content")
    item_content: Optional[str] = Field(
        default=None,
        description="JSON serialization of the message when 'item_type' is 'inline'",
    )
    hash_type: Optional[HashType] = Field(
        default=None, description="Hashing algorithm used to compute 'item_hash'"
    )
    item_hash: ItemHash = Field(description="Hash of the content (sha256 by default)")
    content: BaseContent = Field(description="Content of the message, ready to be used")

    forgotten_by: Optional[List[str]]

    @validator("item_content")
    def check_item_content(cls, v: Optional[str], values):
        item_type = values["item_type"]
        if v is None:
            return None
        elif item_type == ItemType.inline:
            try:
                json.loads(v)
            except JSONDecodeError:
                raise ValueError(
                    "Field 'item_content' does not appear to be valid JSON"
                )
        else:
            raise ValueError(
                f"Field 'item_content' cannot be defined when 'item_type' == '{item_type}'"
            )
        return v

    @validator("item_hash")
    def check_item_hash(cls, v, values):
        item_type = values["item_type"]
        if item_type == ItemType.inline:
            item_content: str = values["item_content"]

            # Double check that the hash function is supported
            hash_type = values["hash_type"] or HashType.sha256
            assert hash_type.value == HashType.sha256

            computed_hash: str = sha256(item_content.encode()).hexdigest()
            if v != computed_hash:
                raise ValueError(
                    f"'item_hash' do not match 'sha256(item_content)'"
                    f", expecting {computed_hash}"
                )
        elif item_type == ItemType.ipfs:
            # TODO: CHeck that the hash looks like an IPFS multihash
            pass
        else:
            assert item_type == ItemType.storage
        return v

    @validator("confirmed")
    def check_confirmed(cls, v, values):
        confirmations = values["confirmations"]
        if v is True and not bool(confirmations):
            raise ValueError("Message cannot be 'confirmed' without 'confirmations'")
        return v

    class Config:
        extra = Extra.forbid
        exclude = {"id_", "_id"}


class PostMessage(BaseMessage):
    """Unique data posts (unique data points, events, ...)"""

    type: Literal[MessageType.post]
    content: PostContent


class AggregateMessage(BaseMessage):
    """A key-value storage specific to an address"""

    type: Literal[MessageType.aggregate]
    content: AggregateContent


class StoreMessage(BaseMessage):
    type: Literal[MessageType.store]
    content: StoreContent


class ForgetMessage(BaseMessage):
    type: Literal[MessageType.forget]
    content: ForgetContent

    @validator("forgotten_by")
    def cannot_be_forgotten(cls, v: Optional[List[str]], values) -> Optional[List[str]]:
        assert values
        if v:
            raise ValueError("This type of message may not be forgotten")
        return v


class ProgramMessage(BaseMessage):
    type: Literal[MessageType.program]
    content: ProgramContent

    @validator("content")
    def check_content(cls, v, values):
        item_type = values["item_type"]
        if item_type == ItemType.inline:
            item_content = json.loads(values["item_content"])
            if v.dict(exclude_none=True) != item_content:
                # Print differences
                vdict = v.dict(exclude_none=True)
                for key, value in item_content.items():
                    if vdict[key] != value:
                        print(f"{key}: {vdict[key]} != {value}")
                raise ValueError("Content and item_content differ")
        return v


class InstanceMessage(BaseMessage):
    type: Literal[MessageType.instance]
    content: InstanceContent


AlephMessage: TypeAlias = Union[
    PostMessage,
    AggregateMessage,
    StoreMessage,
    ProgramMessage,
    InstanceMessage,
    ForgetMessage,
]

AlephMessageType: TypeAlias = Union[
    Type[PostMessage],
    Type[AggregateMessage],
    Type[StoreMessage],
    Type[ProgramMessage],
    Type[InstanceMessage],
    Type[ForgetMessage],
]

message_classes: List[AlephMessageType] = [
    PostMessage,
    AggregateMessage,
    StoreMessage,
    ProgramMessage,
    InstanceMessage,
    ForgetMessage,
]

ExecutableContent: TypeAlias = Union[InstanceContent, ProgramContent]
ExecutableMessage: TypeAlias = Union[InstanceMessage, ProgramMessage]


def parse_message(message_dict: Dict) -> AlephMessage:
    """Returns the message class corresponding to the type of message."""
    for message_class in message_classes:
        message_type: MessageType = MessageType(
            message_class.__annotations__["type"].__args__[0]
        )
        if message_dict["type"] == message_type:
            return message_class.parse_obj(message_dict)
    else:
        raise ValueError(f"Unknown message type {message_dict['type']}")


def add_item_content_and_hash(message_dict: Dict, inplace: bool = False):
    if not inplace:
        message_dict = copy(message_dict)

    message_dict["item_content"] = json.dumps(
        message_dict["content"], separators=(",", ":")
    )
    message_dict["item_hash"] = sha256(
        message_dict["item_content"].encode()
    ).hexdigest()
    return message_dict


def create_new_message(
    message_dict: Dict,
    factory: Optional[AlephMessageType] = None,
) -> AlephMessage:
    """Create a new message from a dict.
    Computes the 'item_content' and 'item_hash' fields.
    """
    message_content = add_item_content_and_hash(message_dict)
    if factory:
        return factory.parse_obj(message_content)
    else:
        return parse_message(message_content)


def create_message_from_json(
    json_data: str,
    factory: Optional[AlephMessageType] = None,
) -> AlephMessage:
    """Create a new message from a JSON encoded string.
    Computes the 'item_content' and 'item_hash' fields.
    """
    message_dict = json.loads(json_data)
    message_content = add_item_content_and_hash(message_dict, inplace=True)
    if factory:
        return factory.parse_obj(message_content)
    else:
        return parse_message(message_content)


def create_message_from_file(
    filepath: Path, factory: Optional[AlephMessageType] = None, decoder=json
) -> AlephMessage:
    """Create a new message from an encoded file.
    Expects json by default, but allows other decoders with a method `.load()`
    that takes a file descriptor.
    Computes the 'item_content' and 'item_hash' fields.
    """
    with open(filepath) as fd:
        message_dict = decoder.load(fd)
    message_content = add_item_content_and_hash(message_dict, inplace=True)
    if factory:
        return factory.parse_obj(message_content)
    else:
        return parse_message(message_content)


class MessagesResponse(BaseModel):
    """Response from an Aleph node API."""

    messages: List[AlephMessage]
    pagination_page: int
    pagination_total: int
    pagination_per_page: int
    pagination_item: str

    class Config:
        extra = Extra.forbid
