# -*- cofing: utf-8 -*-
# MIT License
#
# Copyright (c) 2021 - Present nxtlo
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import typing as __typing

import asyncpg as __asyncpg

from core.utils import traits as __traits

class PgxPool(__traits.PoolRunner):
    def __call__(
        self,
    ) -> __typing.Coroutine[None, None, __typing.Union[__asyncpg.pool.Pool, None]]: ...
    @property
    # This returns this class itself.
    def pool(self) -> PgxPool: ...
    @classmethod
    async def create_pool(cls, *, build: bool = ...) -> PgxPool: ...
    async def execute(
        self,
        sql: str,
        /,
        *args: __typing.Any,
        timeout: __typing.Union[float, None] = ...,
    ) -> None: ...
    async def fetch(
        self,
        sql: str,
        /,
        *args: __typing.Any,
        timeout: __typing.Union[float, None] = ...,
    ) -> list[__typing.Any]: ...
    async def fetchrow(
        self, sql: str, /, *args: __typing.Any, timeout: __typing.Any[float, None] = ...
    ) -> list[__typing.Any] | dict[str, __typing.Any]: ...
    async def fetchval(
        self,
        sql: str,
        /,
        *args: __typing.Any,
        column: __typing.Union[int, None] = ...,
        timeout: __typing.Union[float, None] = ...,
    ) -> __typing.Any: ...
    async def close(self) -> None: ...
    @staticmethod
    def tables() -> str: ...

PoolT = __typing.NewType("PoolT", PgxPool)
