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

from __future__ import annotations

__all__: tuple[str, ...] = ("mod",)

import asyncio
import contextlib
import datetime
import inspect
import io
import sys
import textwrap
import traceback
import typing

import asyncpg
import hikari
import humanize
import tanjun
import yuyo

from core.psql import pool as pool_
from core.utils import cache, consts, format, traits

STDOUT: typing.Final[hikari.Snowflakeish] = hikari.Snowflake(789614938247266305)
DURATIONS: dict[str, int] = {
    "Seconds": 1,
    "Minutes": 60,
    "Hours": 3600,
    "Days": 86400,
    "Months": 2629800,
    "Weeks": 604800,
    "Years": 31557600,
}


@tanjun.with_owner_check
@tanjun.as_message_command("reload")
async def reload(ctx: tanjun.MessageContext) -> None:
    ctx.client.reload_modules(f"core.components")
    await ctx.respond(f"Reloaded modules")


async def sleep_for(
    timer: datetime.timedelta,
    ctx: tanjun.SlashContext,
    member: hikari.InteractionMember,
    pool: pool_.PgxPool,
    hash: traits.HashRunner[str, hikari.Snowflake, hikari.Snowflake],
) -> None:
    assert ctx.guild_id is not None
    while True:
        await asyncio.sleep(timer.total_seconds())
        await pool.execute("DELETE FROM mutes WHERE member_id = $1", member.id)
        mute_role = await hash.get("mutes", ctx.guild_id)
        await member.remove_role(mute_role)
        await ctx.respond(f"{member.mention} has been unmuted.")


async def _set_channel_perms(
    ctx: tanjun.SlashContext, role_id: hikari.Snowflake
) -> None:
    assert ctx.guild_id
    try:
        async with ctx.rest.trigger_typing(ctx.channel_id):
            channels = await ctx.rest.fetch_guild_channels(ctx.guild_id)
            try:
                await asyncio.gather(
                    *(
                        channel.edit_overwrite(
                            role_id,
                            target_type=hikari.PermissionOverwriteType.ROLE,
                            deny=(
                                hikari.Permissions.SEND_MESSAGES
                                | hikari.Permissions.SEND_MESSAGES_IN_THREADS
                                | hikari.Permissions.SPEAK
                                | hikari.Permissions.ADD_REACTIONS
                                | hikari.Permissions.CONNECT
                                | hikari.Permissions.CREATE_PUBLIC_THREADS
                                | hikari.Permissions.CREATE_PRIVATE_THREADS
                            ),
                        )
                        for channel in channels
                    )
                )
            except hikari.ForbiddenError:
                await ctx.respond("I don't have permissions to edit channels.")
                return
    except hikari.HikariError:
        await ctx.respond("Couldn't change channels permissions.")
        raise


async def _done(
    ctx: tanjun.SlashContext,
    role: hikari.Role,
    guild: hikari.Guild,
    hash: traits.HashRunner[str, hikari.Snowflake, hikari.Snowflake],
) -> tuple[None]:
    pendings: list[asyncio.Future[None]] = []
    for task in (
        _set_channel_perms(ctx, role.id),
        hash.set("mutes", guild.id, role.id),
    ):
        pendings.append(asyncio.create_task(task))
    return await asyncio.gather(*pendings)


async def _create_mute_role(
    ctx: tanjun.SlashContext,
    bot: hikari.GatewayBot,
    hash: traits.HashRunner[str, hikari.Snowflake, hikari.Snowflake],
) -> None:
    assert ctx.guild_id is not None
    try:
        # TODO: Check cache first?
        guild = await ctx.rest.fetch_guild(ctx.guild_id)
        if not guild:
            # DMs
            return

        roles = await guild.fetch_roles()

        if any((r := role) and r.name == "Muted" for role in roles):
            await ctx.respond(
                "A role named `Muted` already exists, You want to set it as default mute role?"
                f" Yes, Or No"
            )

            try:
                maybe_setit = await bot.wait_for(
                    hikari.GuildMessageCreateEvent,
                    20,
                    lambda m: m.channel_id == ctx.channel_id
                    and m.author_id == ctx.author.id,
                )
            except asyncio.TimeoutError:
                pass

            if maybe_setit.content in {"Yes", "yes", "y"}:
                await _done(ctx, r, guild, hash)
                await ctx.respond(f"Set mute role to {r.mention}.")
                return

            elif maybe_setit.content in {"No", "no", "n"}:
                await ctx.respond("Returning.")
                return

            else:
                await ctx.respond("Unrecognized answer..")
                return

        # No muted role.
        else:
            try:
                role = await ctx.rest.create_role(
                    guild.id,
                    name="Muted",
                )
            except hikari.HikariError as exc:
                await ctx.respond(f"Couldn't create role: {exc!s}")
                return
            await _done(ctx, role, guild, hash)
            await ctx.respond("Created the mute role.")
            return

    except Exception:
        raise RuntimeError(
            f"Couldn't create mute role for guild {ctx.get_guild().name}"
        )


mutes = (
    tanjun.slash_command_group("mute", "Commands related to muting members.")
    .add_check(tanjun.GuildCheck())
    .add_check(tanjun.AuthorPermissionCheck(hikari.Permissions.MUTE_MEMBERS))
)
mute_roles_group = mutes.with_command(
    tanjun.slash_command_group("role", "Commands to manages the mute role.")
).add_check(tanjun.AuthorPermissionCheck(hikari.Permissions.MANAGE_ROLES))


@mute_roles_group.with_command
@tanjun.as_slash_command("create", "Creates the mute role.")
async def create_mute_role(
    ctx: tanjun.SlashContext,
    hash: traits.HashRunner[str, hikari.Snowflake, hikari.Snowflake] = tanjun.inject(
        type=traits.HashRunner
    ),
    bot: hikari.GatewayBot = tanjun.inject(type=hikari.GatewayBot),
) -> None:
    await _create_mute_role(ctx, bot, hash)


# TODO: Check for role positions.
@mutes.with_command
@tanjun.with_member_slash_option("member", "The member to mute.")
@tanjun.with_str_slash_option(
    "unit", "The duration unit to be muted.", choices=consts.iter(DURATIONS)
)
@tanjun.with_float_slash_option("duration", "The time duration to be muted")
@tanjun.with_str_slash_option(
    "reason", "A reason given for why the member was muted.", default="UNDEFINED"
)
@tanjun.as_slash_command("member", "Mute someone given a duration.")
async def mute(
    ctx: tanjun.SlashContext,
    member: hikari.InteractionMember,
    unit: str,
    duration: float,
    reason: str,
    pool: pool_.PgxPool = tanjun.inject(type=pool_.PoolT),
    hash: traits.HashRunner[str, hikari.Snowflake, hikari.Snowflake] = tanjun.inject(
        type=traits.HashRunner
    ),
) -> None:
    assert ctx.guild_id is not None

    if not (mute_role := await hash.get("mutes", ctx.guild_id)):
        await ctx.respond("No mute role found. Type `/mute role create` to create one.")
        return

    try:
        total_time = DURATIONS[unit] * duration
        await pool.execute(
            "INSERT INTO mutes(member_id, guild_id, author_id, muted_at, duration, why) "
            "VALUES($1, $2, $3, $4, $5, $6)",
            member.id,
            ctx.guild_id,
            ctx.author.id,
            datetime.datetime.today().timestamp(),
            total_time,
            reason,
        )
    except asyncpg.exceptions.UniqueViolationError:
        unlocked_at = float(
            await pool.fetchval(
                "SELECT muted_at FROM mutes WHERE member_id = $1", member.id
            )
        )
        date = humanize.naturaldelta(
            datetime.datetime.now() - datetime.datetime.fromtimestamp(unlocked_at)
        )
        await ctx.respond(f"This member is already been muted for {date}.")
        return
    else:
        await member.add_role(mute_role)
        d = datetime.timedelta(seconds=total_time)
        await ctx.respond(
            f"Member {member.user.username} has been muted for {format.friendly_date(d, minimum_unit='SECONDS')}"
        )
        asyncio.create_task(sleep_for(d, ctx, member, pool, hash))


@tanjun.with_owner_check(halt_execution=True)
@tanjun.with_greedy_argument("query", converters=str)
@tanjun.with_parser
@tanjun.as_message_command("sql")
async def run_sql(
    ctx: tanjun.MessageContext,
    query: str,
    pool: pool_.PoolT = tanjun.injected(type=pool_.PoolT),
) -> None:
    """Run sql code to the database pool."""

    query = format.parse_code(code=query)
    print(query)
    result: None | list[asyncpg.Record] = None

    try:
        result = await pool.fetch(query)
        # SQL Code error
    except asyncpg.exceptions.PostgresSyntaxError:
        await ctx.respond(format.with_block(sys.exc_info()[1]))
        return

        # Tables doesn't exists.
    except asyncpg.exceptions.UndefinedTableError:
        await ctx.respond(format.with_block(sys.exc_info()[1]))
        return

    if not result:
        await ctx.respond("Nothing found.")
        return

    await ctx.respond(format.with_block(result))


@tanjun.with_guild_check
@tanjun.with_own_permission_check(
    hikari.Permissions.KICK_MEMBERS,
    error_message="Bot doesn't have permissions to kick members.",
)
@tanjun.with_author_permission_check(hikari.Permissions.KICK_MEMBERS)
@tanjun.with_str_slash_option(
    "reason", "The reason to kick the member.", converters=(str,), default=None
)
@tanjun.with_member_slash_option("member", "The member to kick.")
@tanjun.as_slash_command("kick", "Kick someone out of the guild.")
async def kick(
    ctx: tanjun.abc.SlashContext,
    member: hikari.Member | None,
    /,
    reason: hikari.UndefinedOr[str],
) -> None:

    try:
        guild = await ctx.fetch_guild()
    except hikari.HikariError:
        guild = ctx.get_guild()

    if guild:
        try:
            member = await ctx.rest.fetch_member(guild.id, member.id)
        except hikari.HTTPError:
            member = ctx.cache.get_member(guild.id, member.id)

        await guild.kick(member.id, reason=reason)
    to_respond = [f"Member {member.username}#{member.discriminator} has been kicked"]
    if reason:
        to_respond += f" For {reason}."
    await ctx.respond("".join(to_respond))


@tanjun.with_owner_check
@tanjun.as_message_command("close", "shutdown")
async def close_bot(
    _: tanjun.MessageContext,
    bot: hikari.GatewayBot = tanjun.inject(type=hikari.GatewayBot),
) -> None:
    try:
        await bot.close()
    except Exception:
        raise


@tanjun.with_guild_check
@tanjun.with_own_permission_check(
    hikari.Permissions.BAN_MEMBERS,
    error_message="Bot doesn't have permissions to ban members.",
)
@tanjun.with_author_permission_check(hikari.Permissions.BAN_MEMBERS)
@tanjun.with_str_slash_option("reason", "An optional reason for the ban.")
@tanjun.with_member_slash_option("member", "The member to ban.")
@tanjun.as_slash_command("ban", "Ban someone from the guild.")
async def ban(
    ctx: tanjun.abc.SlashContext,
    member: hikari.Member | None,
    /,
    reason: hikari.UndefinedOr[str],
) -> None:

    try:
        guild = await ctx.fetch_guild()
    except hikari.HikariError:
        guild = ctx.get_guild()

    if guild:
        try:
            member = await ctx.rest.fetch_member(guild.id, member.id)
        except hikari.HTTPError:
            member = ctx.cache.get_member(guild.id, member.id)

        await guild.ban(member.id, reason=reason)
    to_respond = [f"Member {member.username}#{member.discriminator} has been banned"]
    if reason:
        to_respond += f" for {reason}."
    await ctx.respond("".join(to_respond))


# This command perform rest calls to get an up-to-date
# data instead of the cache.
@tanjun.with_owner_check
@tanjun.with_argument("id", default=None, converters=(int,))
@tanjun.with_parser
@tanjun.as_message_command("guild")
async def fetch_guild(
    ctx: tanjun.MessageContext, id: hikari.Snowflakeish | int | None
) -> None:

    id = id or ctx.guild_id if ctx.guild_id else 411804307302776833
    backoff = yuyo.Backoff(2)
    async for _ in backoff:
        try:
            guild = await ctx.rest.fetch_guild(hikari.Snowflake(id))
            guild_owner = await guild.fetch_owner()

        except hikari.ForbiddenError as exc:
            # not in guild most likely or missin access.
            await ctx.respond(exc.message + ".")
            return

        # Ratelimited... somehow.
        except hikari.RateLimitedError as exc:
            backoff.set_next_backoff(exc.retry_after)

        # 5xx, continue.
        except hikari.InternalServerError:
            pass

        # Other errors. break.
        else:
            embed = hikari.Embed(title=guild.name, description=guild.id)
            if ctx.cache:
                guild_snowflakes = set(ctx.cache.get_available_guilds_view().keys())
                users_snowflakes = set(ctx.cache.get_users_view().keys())
            if guild.icon_url:
                embed.set_thumbnail(guild.icon_url)
            (
                embed.add_field(
                    "Information",
                    f"Members: {len(guild.get_members())}\n"
                    f"Created at: {tanjun.from_datetime(guild.created_at, style='R')}\n"
                    f"Cached: {guild.id in guild_snowflakes or False}",  # type: ignore
                ).add_field(
                    "Owner",
                    f"Name: {guild_owner.username}\n"
                    f"ID: {guild_owner.id}\n"
                    f"Cached: {ctx.author.id in users_snowflakes or False}",  # type: ignore
                )
            )
            await ctx.respond(embed=embed)
            return


@tanjun.with_owner_check
@tanjun.as_message_command("guilds")
async def get_guilds(ctx: tanjun.MessageContext) -> None:
    guilds = ctx.cache.get_available_guilds_view()
    embed = hikari.Embed(
        description=format.with_block(
            "\n".join(
                f"{id}::{guild.name}::{len(guild.get_members())}"
                for id, guild in guilds.items()
            ),
            lang="css",
        )
    )
    await ctx.respond(embed=embed)


@tanjun.with_owner_check
@tanjun.with_greedy_argument("body", converters=(str,))
@tanjun.with_parser
@tanjun.as_message_command("eval")
async def eval_command(
    ctx: tanjun.MessageContext,
    body: str,
    /,
    bot: hikari.GatewayBot = tanjun.inject(type=hikari.GatewayBot),
) -> None:
    """Evaluates python code"""
    env = {
        "ctx": ctx,
        "bot": bot,
        "hikari": hikari,
        "tanjun": tanjun,
        "asyncio": asyncio,
        "source": inspect.getsource,
    }

    def cleanup_code(content: str) -> str:
        """Automatically removes code blocks from the code."""
        # remove ```py\n```
        if content.startswith("```") and content.endswith("```"):
            return "\n".join(content.split("\n")[1:-1])

        return content.strip("` \n")

    env.update(globals())

    body = cleanup_code(body)
    stdout = io.StringIO()
    err = out = None

    to_compile = f'async def func():\n{textwrap.indent(body, "  ")}'

    def paginate(text: str) -> list[str]:
        """Simple generator that paginates text."""
        last = 0
        pages: set[str] = set()
        for curr in range(0, len(text)):
            if curr % 1980 == 0:
                pages.add(text[last:curr])
                last = curr
                appd_index = curr
        if appd_index != len(text) - 1:
            pages.add(text[last:curr])
        return list(filter(lambda a: a != "", pages))

    try:
        exec(to_compile, env)
    except Exception as e:
        err = await ctx.respond(f"```py\n{e.__class__.__name__}: {e}\n```")
        return await ctx.message.add_reaction("\u2049")

    func = env["func"]
    try:
        with contextlib.redirect_stdout(stdout):
            ret = await func()  # type: ignore
    except Exception as e:
        value = stdout.getvalue()
        err = await ctx.respond(f"```py\n{value}{traceback.format_exc()}\n```")
    else:
        value = stdout.getvalue()
        if ret is None:
            if value:
                try:
                    out = await ctx.respond(f"```py\n{value}\n```")
                except Exception:
                    paginated_text = paginate(value)
                    for page in paginated_text:
                        if page == paginated_text[-1]:
                            out = await ctx.respond(f"```py\n{page}\n```")
                            break
                        await ctx.respond(f"```py\n{page}\n```")
        else:
            try:
                out = await ctx.respond(f"```py\n{value}{ret}\n```")
            except:
                paginated_text = paginate(f"{value}{ret}")
                for page in paginated_text:
                    if page == paginated_text[-1]:
                        out = await ctx.respond(f"```py\n{page}\n```")
                        break
                    await ctx.respond(f"```py\n{page}\n```")

    if out:
        await ctx.message.add_reaction("\u2705")
    elif err:
        await ctx.message.add_reaction("\u2049")
    else:
        await ctx.message.add_reaction("\u2705")


# Originally, These commands are used to manage and test the cache
# not for actually caching stuff.
@tanjun.with_owner_check
@tanjun.as_message_command_group("cache")
async def cacher(
    ctx: tanjun.MessageContext,
) -> None:
    # This will always not respond.
    assert not ctx.has_responded


@cacher.with_command
@tanjun.with_greedy_argument("value")
@tanjun.with_argument("key")
@tanjun.with_parser
@tanjun.as_message_command("put")
async def put(
    ctx: tanjun.MessageContext,
    key: typing.Any,
    value: typing.Any,
    cache_: cache.Memory[typing.Any, typing.Any] = tanjun.inject(type=cache.Memory),
) -> None:
    cache_.put(key, value)
    await ctx.respond(f"Cached {key} to {value}")


@cacher.with_command
@tanjun.with_greedy_argument("key")
@tanjun.with_parser
@tanjun.as_message_command("get")
async def get(
    ctx: tanjun.MessageContext,
    key: typing.Any,
    cache_: cache.Memory[typing.Any, typing.Any] = tanjun.inject(type=cache.Memory),
) -> None:
    await ctx.respond(cache_.get(key, "NOT_FOUND"))


@cacher.with_command
@tanjun.with_greedy_argument("key")
@tanjun.with_parser
@tanjun.as_message_command("del")
async def remove(
    ctx: tanjun.MessageContext,
    key: typing.Any,
    cache_: cache.Memory[typing.Any, typing.Any] = tanjun.inject(type=cache.Memory),
) -> None:
    try:
        del cache_[key]
        await ctx.respond("Ok")
    except KeyError:
        await ctx.respond("Key not found in cache.")
        return


@cacher.with_command
@tanjun.as_message_command("items")
async def cache_items(
    ctx: tanjun.MessageContext,
    cache_: cache.Memory[typing.Any, typing.Any] = tanjun.inject(type=cache.Memory),
) -> None:
    await ctx.respond(format.with_block(cache_.view()))


@cacher.with_command
@tanjun.as_message_command("clear")
async def cache_clear(
    ctx: tanjun.MessageContext,
    cache_: cache.Memory[typing.Any, typing.Any] = tanjun.inject(type=cache.Memory),
) -> None:
    cache_.clear()
    await ctx.respond(cache_.view())


async def when_join_guilds(event: hikari.GuildJoinEvent) -> None:
    guild = await event.fetch_guild()
    guild_owner = await guild.fetch_owner()
    embed = hikari.Embed(
        title=f"{guild.name} | {guild.id}",
        description="Joined a guild.",
        timestamp=datetime.datetime.utcnow().astimezone(datetime.timezone.utc),
    )
    if guild.icon_url:
        embed.set_thumbnail(guild.icon_url)
    (
        embed.add_field("Member count", str(len(guild.get_members())))
        .add_field("Created at", tanjun.from_datetime(guild.created_at, style="R"))
        .add_field("Owner", f"Name: {guild_owner.username}\n" f"ID: {guild_owner.id}")
    )
    await event.app.rest.create_message(STDOUT, embed=embed)


async def when_leave_guilds(event: hikari.GuildLeaveEvent) -> None:
    guild = event.old_guild
    if guild:
        embed = hikari.Embed(
            title=f"{guild.name} | {guild.id}",
            description="Left a guild.",
            timestamp=datetime.datetime.utcnow().astimezone(datetime.timezone.utc),
        ).add_field("Created at", tanjun.from_datetime(guild.created_at, style="R"))
        await event.app.rest.create_message(STDOUT, embed=embed)
        return
    await event.app.rest.create_message(
        STDOUT, f"Left from `UNDEFINED` guild {event.guild_id}"
    )


mod = (
    tanjun.Component(name="Moderation", strict=True)
    .add_listener(hikari.GuildJoinEvent, when_join_guilds)
    .add_listener(hikari.GuildLeaveEvent, when_leave_guilds)
    .load_from_scope()
    .make_loader()
)
