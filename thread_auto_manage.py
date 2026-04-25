
from params import *
from discord import app_commands
from discord.ext import tasks
from typing import Optional
import datetime as datetime_module  # stupid aspect of datetime being also an object
from datetime import datetime, timezone, timedelta
import asyncio


last_shaken = {}


def shake_thread_on_msg(msg: discord.Message):
    if not isinstance(msg.channel, discord.Thread):
        return
    cur.execute(
        "SELECT * FROM threads_persist WHERE channelthread_id = ? OR channelthread_id = ?",
        (msg.channel.id, msg.channel.parent_id)
    )
    if cur.fetchall():
        last_shaken[msg.channel.id] = datetime.now(timezone.utc)


@tasks.loop(minutes=5.0)
@app_commands.checks.bot_has_permissions(manage_threads=True)
async def unarchiver():
    async def shake_thread(thread: discord.Thread):
        aad = thread.auto_archive_duration
        aad_padded = aad - 360 # much larger than 5 minutes to help account for bot outages
        if datetime.now(timezone.utc) - last_shaken.get(thread.id, datetime.min.replace(tzinfo=timezone.utc)) < timedelta(minutes=aad_padded):
            return
        hist_last = [m async for m in thread.history(limit=1)]
        last_msg = hist_last[0] if hist_last else thread  # depends on both message and thread having created_at
        if datetime.now(timezone.utc) - last_msg.created_at > timedelta(minutes=aad_padded):
#            temp = 4320 if aad == 10080 else 10080
#            await thread.edit(auto_archive_duration=temp)
#            await thread.edit(auto_archive_duration=aad)
            bump_msg = await thread.send("Bump")
            await bump_msg.delete(delay=1.0)
            last_shaken[thread.id] = datetime.now(timezone.utc)

    cur.execute("SELECT channelthread_id FROM threads_persist")
    all_threads = [t[0] for t in cur.fetchall()]
    if not all_threads:
        return
    for guild in bot.guilds:
        for ch_id in all_threads:
            ch_th = guild.get_channel_or_thread(ch_id)
            if not ch_th:
                continue
            elif ch_th.type in [discord.ChannelType.text]:
                for th in ch_th.threads:
                    await shake_thread(th)
            elif isinstance(ch_th, discord.Thread):
                await shake_thread(ch_th)
            else:
                print(f"Unsupported channel type with ID {ch_id}")


@unarchiver.before_loop
async def before_unarchiver():
    await bot.wait_until_ready()
    if not DEBUG:
        await asyncio.sleep(900) # helps reduce spam in Discord's audit log, since last_shaken dict is empty when bot is restarted


@tree.command(description="Toggles whether a thread or channel is kept unarchived")
@app_commands.checks.has_role(STAFF_ROLE_ID)
@app_commands.checks.bot_has_permissions(manage_threads=True)
async def auto_unarchive(interaction: discord.Interaction):
    c_id = interaction.channel_id  # Can be thread id or channel id if not thread
    ch_th = interaction.guild.get_channel_or_thread(c_id)

    if ch_th.type not in [discord.ChannelType.text] and not isinstance(ch_th, discord.Thread):
        await interaction.response.send_message("Must be text channel or thread.", ephemeral=True)
        return

    cur.execute(
        "SELECT * FROM threads_persist WHERE channelthread_id = ?",
        (c_id,)
    )
    if cur.fetchall():
        cur.execute(
            "DELETE FROM threads_persist WHERE channelthread_id = ?",
            (c_id,)
        )
        conn.commit()
        await interaction.response.send_message("No longer thread-unarchiving automatically")
    else:
        cur.execute(
            "INSERT INTO threads_persist (channelthread_id) VALUES (?)",
            (c_id,)
        )
        conn.commit()
        await interaction.response.send_message("Now thread-unarchiving automatically")


@tasks.loop(hours=6.0)
@app_commands.checks.bot_has_permissions(manage_threads=True)
async def forum_closer():
    cur.execute("SELECT forum_id, days_wait, lock FROM forum_posts_close")
    all_forums = cur.fetchall()
    if not all_forums:
        return
    for guild in bot.guilds:
        for f_id, days, lock in all_forums:
            forum = guild.get_channel_or_thread(f_id)
            if not forum:
                continue
            elif forum.type not in [discord.ChannelType.forum]:
                print(f"Error: channel with ID {f_id} not forum type")
                continue
            else:
                for th in forum.threads:
                    hist_last = [m async for m in th.history(limit=1)]
                    last_msg = hist_last[0] if hist_last else th  # depends on both message and thread having created_at
                    if datetime.now(timezone.utc) - last_msg.created_at > timedelta(days=days):
                        if lock:
                            await th.edit(archived=True, locked=True)
                        else:
                            await th.edit(archived=True)


@forum_closer.before_loop
async def before_forum_closer():
    await bot.wait_until_ready()


@tree.command(description="Toggles whether a forum's posts auto-close some time after last message")
@app_commands.checks.has_role(STAFF_ROLE_ID)
@app_commands.checks.bot_has_permissions(manage_threads=True)
@app_commands.describe(
    forum_id='ID of forum to manage',
    days_wait='Days to wait before closing (can be decimal number)',
    lock='Whether to lock post as well'
)
@app_commands.choices(lock=[app_commands.Choice(name="True", value=1), app_commands.Choice(name="False", value=0)])
async def auto_close_forum_posts(interaction: discord.Interaction, forum_id: str, days_wait: Optional[float] = 14.0,
                                 lock: app_commands.Choice[int] = 0):
    try:
        forum_id = int(forum_id)  # necessary in case forum_id exceeds int53 limit so slash command would reject an int input
    except ValueError:
        await interaction.response.send_message("Must enter a valid forum channel ID.", ephemeral=True)
        return
    if isinstance(lock, app_commands.Choice):
        lock = lock.value
    ch = interaction.guild.get_channel_or_thread(forum_id)
    if not ch or ch.type not in [discord.ChannelType.forum]:
        await interaction.response.send_message("Must enter a valid forum channel ID.", ephemeral=True)
        return

    cur.execute(
        "SELECT forum_id FROM forum_posts_close WHERE forum_id = (?)",
        (forum_id,)
    )
    if cur.fetchall():
        cur.execute(
            "DELETE FROM forum_posts_close WHERE forum_id = (?)",
            (forum_id,)
        )
        conn.commit()
        await interaction.response.send_message(f"Toggled: no longer closing posts in {ch.mention} automatically")
    else:
        cur.execute(
            "INSERT INTO forum_posts_close (forum_id, days_wait, lock) VALUES (?, ?, ?)",
            (forum_id, days_wait, lock)
        )
        conn.commit()
        await interaction.response.send_message(f"Now closing posts in {ch.mention} automatically{', with lock posts' if lock else ''}")


@tree.command(description="Lists channels and threads set to auto unarchive, and forum channels set to auto close")
@app_commands.checks.has_role(STAFF_ROLE_ID)
async def list_auto_managed_channels(interaction: discord.Interaction):
    cur.execute("SELECT channelthread_id FROM threads_persist")
    threads = cur.fetchall()
    cur.execute("SELECT forum_id, days_wait, lock FROM forum_posts_close")
    forums = cur.fetchall()
    msg = "Channels and threads set to auto unarchive:\n"
    if threads:
        for t in threads:
            ch_th = interaction.guild.get_channel_or_thread(t[0])
            if ch_th:
                msg += f"{ch_th.mention}\n"
    else:
        msg += "*None*\n"
    msg += "\nForum channels set to auto close:"
    if forums:
        for f in forums:
            ch = interaction.guild.get_channel_or_thread(f[0])
            if ch:
                msg += f"\n{ch.mention} after {f[1]} days{' and lock' if f[2] else ''}"
    else:
        msg += "\n*None*"
    await interaction.response.send_message(msg, ephemeral=True)