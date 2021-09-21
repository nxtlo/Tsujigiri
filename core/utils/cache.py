from __future__ import annotations

__all__: tuple[str, ...] = ("Memory", "Hash")

import copy
import logging
import typing

import aioredis

from . import traits
from .interfaces import HashView

_LOG: typing.Final[logging.Logger] = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

# Memory types.
MKeyT = typing.TypeVar("MKeyT")
MValueT = typing.TypeVar("MValueT")

# Hash types.
HashT = typing.TypeVar("HashT")
FieldT = typing.TypeVar("FieldT")
ValueT = typing.TypeVar("ValueT")

class Hash(traits.HashRunner, typing.Generic[traits.HashT, traits.FieldT, traits.ValueT]):
    # For some reason its not showing the inherited class docs.

    """A Basic generic Implementation of redis hash.

    Example
    -------
    ```py
    async def func() -> None:
        cache: Hash[str, hikari.SnowFlake, hikari.Member]
        rest_member = await rest.fetch_members()
        for member in rest_members:
            cache.set("members", member.id, member)
        get_member = await cache.get("members", member.id) -> hikari.Member(...)
    """
    __slots__: typing.Sequence[str] = ("_injector",)

    def __init__(
        self,
        host: str,
        port: int,
        password: str | None = None,
        /,
        *,
        db: str | int = 0,
        ssl: bool = False,
        max_connections: int = 0,
        decode_responses: bool = True,
        **kwargs: typing.Any,
    ) -> None:
        self._injector = aioredis.Redis(
            host=host,
            port=port,
            password=password,  # type: ignore
            retry_on_timeout=True,
            ssl=ssl,
            db=db,
            decode_responses=decode_responses,
            max_connections=max_connections,
            **kwargs,
        )

    async def __execute_command(
        self,
        command: str,
        hash: HashT,
        /,
        *,
        field: FieldT | str = "",  # This is actually required.
        value: ValueT | str = "",
    ) -> typing.Any:
        fmt = "{} {} {} {}".format(command, hash, field, value)
        print(fmt)
        return await self._injector.execute_command(fmt)

    async def set(self, hash: HashT, field: FieldT, value: ValueT) -> None:
        return await self.__execute_command("HSET", hash, field=field, value=value)

    async def setx(self, hash: HashT, field: FieldT) -> typing.Any:
        await self.__execute_command("HSETNX", hash, field=field)

    async def remove(self, hash: HashT) -> bool | None:
        cmd: int = await self.__execute_command("DEL", hash)
        if cmd != 1:
            _LOG.warn(
                f"Result is {bool(cmd)}, Means hash {hash} doesn't exists. returning."
            )
            return None
        return bool(cmd)

    async def len(self, hash: HashT) -> int:
        return await self.__execute_command("HLEN", hash)

    async def all(self, hash: HashT) -> HashView | None:
        coro: dict[typing.Any, typing.Any] = await self.__execute_command("HVALS", hash)
        for k, v in enumerate(coro):
            return HashView(key=k, value=v)
        return None

    async def delete(self, hash: HashT, field: FieldT) -> None:
        return await self.__execute_command("HDEL", hash, field=field)

    async def exists(self, hash: HashT, field: FieldT) -> bool:
        send: int = await self.__execute_command("HEXISTS", hash, field=field)
        return bool(send)

    async def get(self, hash: HashT, field: FieldT) -> ValueT:
        return await self.__execute_command("HGET", hash, field=field)

    def clone(self) -> Hash[HashT, FieldT, ValueT]:
        return copy.deepcopy(self)


class Memory(typing.MutableMapping[MKeyT, MValueT]):
    """A very basic in memory cache that we may api, embeds, etc."""

    __slots__: tuple[str, ...] = ("_map",)

    def __init__(self) -> None:
        self._map: dict[MKeyT, MValueT] = {}

    @property
    def map(self) -> dict[MKeyT, MValueT]:
        return self._map

    def clear(self) -> None:
        self.map.clear()

    def clone(self) -> dict[MKeyT, MValueT]:
        return self.map.copy()

    def __repr__(self) -> str:
        return f"<Cache items {len(self)}"

    def __getitem__(self, k: MKeyT) -> MValueT:
        return self.map[k]

    def __iter__(self) -> typing.Iterator[MKeyT]:
        return iter(self.map)

    def __setitem__(self, k: MKeyT, v: MValueT) -> None:
        self.map[k] = v

    def __delitem__(self, v: MKeyT) -> None:
        del self.map[v]

    def __len__(self) -> int:
        return len(self.map)

    def values(self) -> typing.ValuesView[MValueT]:
        return self._map.values()

    def keys(self) -> typing.KeysView[MKeyT]:
        return self._map.keys()
