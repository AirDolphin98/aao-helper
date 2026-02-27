
# Some of this code is copied from or based on the original Discord MoveBot
# https://github.com/HumanikaRafeki/DiscordMoveBot/blob/master/move_bot.py


from params import *
import discord
from discord import app_commands
from typing import List, Optional
import discord.utils
import re
import json
import asyncio
from discord.ext import tasks
import datetime as datetime_module  # stupid aspect of datetime being also an object
from datetime import datetime, timezone, timedelta


DELETE_LIMIT = 50
BACKUP_LOOP_MINS = 30
if DEBUG:
    DELETE_LIMIT = 5
    BACKUP_LOOP_MINS = 1


kill_flag = datetime.fromtimestamp(0, tz=timezone.utc)  # using a timestamp instead of a boolean to allow for automatic reset of kill flag after certain duration
class IntentionalKillProcessOfMoveOrDeleteMessages(Exception):
    pass
KILL_DURATION = 30 # seconds, to try to ensure that a program has enough time to run in between checks of the kill flag, while also not leaving the kill flag set for too long which
def check_kill_flag():
    global kill_flag
    if datetime.now(timezone.utc) - kill_flag < timedelta(seconds=KILL_DURATION):
        raise IntentionalKillProcessOfMoveOrDeleteMessages()


async def move_msgs(dest_ch: discord.TextChannel | discord.Thread, messages: List[discord.Message]):
    webhook_names = ['Move messages, by AAO Helper'] # If name change, PREPEND to list, do not remove old names
    webhook = None
    wbhks = await dest_ch.guild.webhooks()
    for wbhk in wbhks:
        if wbhk.name == webhook_names[0]: # webhook for sending moved message must be newest name
            webhook = wbhk
            break
    wb_dest_ch = dest_ch.parent if isinstance(dest_ch, discord.Thread) else dest_ch
    if webhook is None:
        webhook = await wb_dest_ch.create_webhook(name=webhook_names[0], reason='Required webhook for Move messages to function.')
    else:
        if webhook.channel != wb_dest_ch:
            await webhook.edit(channel=wb_dest_ch)

    def get_msg_content(msg: discord.Message):
        if msg.reference and msg.message_snapshots:
            msg_snap = msg.message_snapshots[0]
            return f"-# > forwarded from: {msg.reference.jump_url} -- {discord.utils.format_dt(msg_snap.created_at, style='S')}\n{msg_snap.content}"
        msg_poll_text = f"-# [Poll]\n> {msg.poll.question}\n" + "\n".join([f"- {answer.text}" for answer in msg.poll.answers]) if msg.poll else None
        return msg.content or msg_poll_text or msg.system_content or '' # shouldn't need to worry about sending empty content as long as there's msg_prefix with the timestamp
    
    for msg in messages:
        check_kill_flag()
        msg_wbhk_name = None
        if msg.webhook_id:
            for wbhk in wbhks:
                if wbhk.id == msg.webhook_id:
                    msg_wbhk_name = wbhk.name
                    break
        # prefix with message timestamp unless sent by webhook with recognized name, meaning it was already a moved message
        if msg_wbhk_name and msg_wbhk_name in webhook_names:
            msg_prefix = ''
        else:
            msg_prefix = "-# [SYSTEM MESSAGE]\n" if msg.is_system() else ''
            if msg.reference and msg.reference.type == discord.MessageReferenceType.reply:
                try:
                    ref_msg = await msg.channel.fetch_message(msg.reference.message_id)
                    ref_msg_content = get_msg_content(ref_msg)
                    msg_prefix += f"-# > reply to: {ref_msg.author.display_name} {ref_msg.jump_url} -- {ref_msg_content[:50]} {'...' if len(ref_msg_content) > 50 else ''}\n"
                except:
                    msg_prefix += f"-# > reply to: *Original message was deleted or could not be retrieved*\n"
            msg_prefix += f"-# [{discord.utils.format_dt(msg.created_at, style='S')}]\n"

        sub_msgs = []
        msg_content = get_msg_content(msg)
        if len(msg_prefix + msg_content) <= MESSAGE_LIMIT: # save some processing if message doesn't even need to be split
            sub_msgs.append(msg_prefix + msg_content)
        else:
            current_chunk = msg_prefix
            split_content_unlimit = re.split(r'(\s+)', msg_content) # split by whitespace but keep the whitespace as separate tokens to preserve spacing
            split_content = []
            for token in split_content_unlimit:
                for i in range(0, len(token), MESSAGE_LIMIT):
                    split_content.append(token[i:i+MESSAGE_LIMIT]) # further split tokens that are themselves longer than the message limit

            for token in split_content:
                if len(current_chunk) + len(token) > MESSAGE_LIMIT:
                    sub_msgs.append(current_chunk)
                    current_chunk = token
                else:
                    current_chunk += token
        
        if msg.edited_at:
            edited_suffix = f"\n-# *(edited {discord.utils.format_dt(msg.edited_at, style='S')})*"
            if len(sub_msgs[-1]) + len(edited_suffix) > MESSAGE_LIMIT:
                sub_msgs.append(edited_suffix)
            else:
                sub_msgs[-1] += edited_suffix

        reactions = msg.reactions
        async def add_reacts(sent_msg: discord.Message, reactions: List[discord.Reaction]):
            for reaction in reactions:
                try:
                    await sent_msg.add_reaction(reaction.emoji)
                except:
                    pass # if reaction can't be added (e.g. custom emoji from another server), just ignore and keep going
        
        msg_or_snap = msg.message_snapshots[0] if msg.message_snapshots else msg
        if isinstance(dest_ch, discord.Thread):
            try:
                async def send_with_attachments():
                    for i, sub_msg in enumerate(sub_msgs):
                        await asyncio.sleep(RATE_LIMIT_GAP)
                        sent_msg = await webhook.send(
                            content=sub_msg,
                            thread=dest_ch,
                            username=msg.author.display_name,
                            avatar_url=msg.author.display_avatar.url,
                            embeds=msg_or_snap.embeds if i==len(sub_msgs)-1 else [],
                            files=[await attachment.to_file(filename=attachment.filename, spoiler=attachment.is_spoiler(), description=attachment.description if attachment.description else None) for attachment in msg_or_snap.attachments] if i==len(sub_msgs)-1 else [],
                            wait=True,
                            allowed_mentions=discord.AllowedMentions.none()
                        )
                        if i == len(sub_msgs)-1:
                            await add_reacts(sent_msg, reactions)
                await send_with_attachments()
            except:
                print(f"AAO Helper: Failed to move attachments for message {msg.id}. Trying attachments again.")
                try:
                    await send_with_attachments()
                except:
                    print(f"AAO Helper: Failed again to move attachments for message {msg.id}. Moving message without attachments.")
                    for i, sub_msg in enumerate(sub_msgs):
                        await asyncio.sleep(RATE_LIMIT_GAP)
                        sent_msg = await webhook.send(
                            content=sub_msg,
                            thread=dest_ch,
                            username=msg.author.display_name,
                            avatar_url=msg.author.display_avatar.url,
                            embeds=msg_or_snap.embeds if i==len(sub_msgs)-1 else [],
                            wait=True,
                            allowed_mentions=discord.AllowedMentions.none()
                        )
                        if i == len(sub_msgs)-1:
                            await add_reacts(sent_msg, reactions)
                    await dest_ch.send(f"-# [attachments in above message could not be moved]")
        else:
            try:
                async def send_with_attachments():
                    for i, sub_msg in enumerate(sub_msgs):
                        await asyncio.sleep(RATE_LIMIT_GAP)
                        sent_msg = await webhook.send(
                            content=sub_msg,
                            username=msg.author.display_name,
                            avatar_url=msg.author.display_avatar.url,
                            embeds=msg_or_snap.embeds if i==len(sub_msgs)-1 else [],
                            files=[await attachment.to_file(filename=attachment.filename, spoiler=attachment.is_spoiler(), description=attachment.description if attachment.description else None) for attachment in msg_or_snap.attachments] if i==len(sub_msgs)-1 else [],
                            wait=True,
                            allowed_mentions=discord.AllowedMentions.none()
                        )
                        if i == len(sub_msgs)-1:
                            await add_reacts(sent_msg, reactions)
                await send_with_attachments()
            except:
                print(f"AAO Helper: Failed to move attachments for message {msg.id}. Trying attachments again.")
                try:
                    await send_with_attachments()
                except:
                    print(f"AAO Helper: Failed again to move attachments for message {msg.id}. Moving message without attachments.")
                    for i, sub_msg in enumerate(sub_msgs):
                        await asyncio.sleep(RATE_LIMIT_GAP)
                        sent_msg = await webhook.send(
                            content=sub_msg,
                            username=msg.author.display_name,
                            avatar_url=msg.author.display_avatar.url,
                            embeds=msg_or_snap.embeds if i==len(sub_msgs)-1 else [],
                            wait=True,
                            allowed_mentions=discord.AllowedMentions.none()
                        )
                        if i == len(sub_msgs)-1:
                            await add_reacts(sent_msg, reactions)
                    await dest_ch.send(f"-# [attachments in above message could not be moved]")

        cur.execute(  # no effect if not a channel pair that's being backed up. Keeps most recently backed up message up-to-date in case of crash
            """UPDATE channel_backups SET last_msg_timestamp = ? WHERE src_channel_id = ? AND dest_channel_id = ?""", 
            (msg.created_at.timestamp(), msg.channel.id, dest_ch.id)
        )
        conn.commit()


@tree.command(description="Move messages from one channel to another. Must be called within the channel to move messages from.")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(read_message_history=True, manage_messages=True)
@app_commands.describe(
    to_channel_id="ID or # of the channel or thread to move messages to. Must be same server if deleting original messages.",
    from_message_id="ID of the earliest message to move. If only this is provided, only this message will be moved.",
    up_to_message_id="ID of the latest message to move (optional, defaults to only the one message)",
    user_filter="@mention (press space at end) or user ID of the only user(s) to include. Precede with '-' to exclude users instead (optional, defaults to all users)",
    delete_original=f"Delete original messages after moving. Limit {DELETE_LIMIT} (yes/no, default no)",
)
@app_commands.choices(delete_original=[
    app_commands.Choice(name="yes", value=1),
    app_commands.Choice(name="no", value=0),
])
async def move_messages(
    interaction: discord.Interaction,
    to_channel_id: str,
    from_message_id: str,
    up_to_message_id: Optional[str] = None,
    user_filter: Optional[str] = None,
    delete_original: Optional[app_commands.Choice[int]] = None,
):
    try:
        check_kill_flag()
    except IntentionalKillProcessOfMoveOrDeleteMessages:
        await interaction.response.send_message(f"Please wait for a grace period of {KILL_DURATION} seconds after using the `/kill_process` command.", ephemeral=True)
        return
    src_ch = interaction.channel
    del_orig = delete_original.value if delete_original else 0
    try:
        to_channel_id = int(to_channel_id)  # necessary in case channel_id exceeds int53 limit so slash command would reject an int input
    except ValueError:
        if re.findall(r"<#(\d+)>", to_channel_id):
            to_channel_id = int(re.findall(r"<#(\d+)>", to_channel_id)[0])
        else:
            await interaction.response.send_message("Must enter a valid destination channel ID.", ephemeral=True)
            return
    try:
        from_message_id = int(from_message_id)  # necessary in case message_id exceeds int53 limit so slash command would reject an int input
    except ValueError:
        await interaction.response.send_message("Must enter a valid from message ID.", ephemeral=True)
        return
    try:
        up_to_message_id = int(up_to_message_id) if up_to_message_id else None  # necessary in case message_id exceeds int53 limit so slash command would reject an int input
    except ValueError:
        await interaction.response.send_message("Must enter a valid up to message ID.", ephemeral=True)
        return
    for guild in bot.guilds:
        dest_ch = guild.get_channel_or_thread(to_channel_id)
        if dest_ch:
            dest_guild = guild
            break
    if dest_ch is None:
        await interaction.response.send_message("Destination channel not found. Please check the channel ID and try again.", ephemeral=True)
        return
    if not isinstance(dest_ch, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message("Destination must be a text channel or thread.", ephemeral=True)
        return
    if not dest_ch.permissions_for(dest_guild.me).manage_webhooks:
        await interaction.response.send_message("Need Manage Webhooks permission in the destination channel to move messages.", ephemeral=True)
        return
    if del_orig and dest_ch.guild != src_ch.guild:
        await interaction.response.send_message("Cannot delete original messages if destination channel is in a different server. Please uncheck delete option or choose a destination channel in the same server.", ephemeral=True)
        return
    
    cur.execute(
        "SELECT * FROM channel_backups WHERE src_channel_id = ? AND dest_channel_id = ?",
        (src_ch.id, dest_ch.id)
    )
    if cur.fetchone() and del_orig:
        await interaction.response.send_message("Cannot delete original messages because this pair of channels is a backup pipeline. Move command canceled.", ephemeral=True)
        return

    try:
        from_msg = await src_ch.fetch_message(from_message_id)
    except discord.NotFound:
        await interaction.response.send_message("'From' message not found in current channel. Please check the message ID and try again.", ephemeral=True)
        return
    try:
        to_msg = await src_ch.fetch_message(up_to_message_id) if up_to_message_id else None
    except discord.NotFound:
        await interaction.response.send_message("'To' message not found in current channel. Please check the message ID and try again.", ephemeral=True)
        return
    if to_msg and from_msg.created_at > to_msg.created_at:
        await interaction.response.send_message("'To' message must be after 'From' message. Please check the message IDs and try again.", ephemeral=True)
        return

    users = []
    exclude = False
    if user_filter:
        if '-' in user_filter.strip()[1:]:
            await interaction.response.send_message("Invalid user filter syntax. Use only one `-` at the start to exclude users; do not put `-` anywhere else.", ephemeral=True)
            return
        if user_filter.strip().startswith('-'):
            exclude = True
        user_ids = re.findall(r"(\d+)", user_filter)
        for u_id in user_ids:
            if len(u_id) < 12:
                await interaction.response.send_message(f"Number received as user_id `{u_id}` was under 12 digits (arbitrary sanity check). If this was actually correct, please enter the number padded with leading 0's.", ephemeral=True)
                return
            user = bot.get_user(int(u_id))
            if not user:
                await interaction.response.send_message(f"No user found with ID `{u_id}`. Please check the user ID and try again.", ephemeral=True)
                return
            users.append(user)
    
    await interaction.response.defer(ephemeral=True) # the following code may take a while, so must defer response so that interaction does not time out
    msgs_deleted = 0
    delete_aborted = False
    async def move_and_delete(messages: List[discord.Message], msgs_deleted, delete_aborted):
        if users:
            if exclude:
                messages = [msg for msg in messages if msg.author not in users]
            else:
                messages = [msg for msg in messages if msg.author in users]
        await move_msgs(dest_ch, messages)
        if del_orig and not delete_aborted:
            for msg in messages:
                check_kill_flag()
                if msgs_deleted >= DELETE_LIMIT:
                    delete_aborted = True
                    break
                await asyncio.sleep(RATE_LIMIT_GAP)
                try:
                    await msg.delete()
                    msgs_deleted += 1
                except:
                    pass # if message was already deleted or can't be deleted, just ignore and keep going
        return msgs_deleted, delete_aborted
    
    dest_start_msg = await dest_ch.send(f"Messages moved from {from_msg.jump_url}")
    for guild in bot.guilds:
        server_comm_ch = guild.get_channel_or_thread(SERVER_COMM_CH)
        if server_comm_ch:
            break
    try:
        if to_msg is None or from_message_id == up_to_message_id:
            msgs_deleted, delete_aborted = await move_and_delete([from_msg], msgs_deleted, delete_aborted)
            num_msgs = 1
        else:
            num_msgs = 0
            messages = [from_msg] + [message async for message in src_ch.history(after=from_msg, before=to_msg, oldest_first=True)]
            while messages:  # loop to move messages in batches, in case problems arise from moving too many messages at once
                msgs_deleted, delete_aborted = await move_and_delete(messages, msgs_deleted, delete_aborted)
                num_msgs += len(messages)
                last_msg = messages[-1]
                messages = [message async for message in src_ch.history(after=last_msg, before=to_msg, oldest_first=True)]
            msgs_deleted, delete_aborted = await move_and_delete([to_msg], msgs_deleted, delete_aborted)
            num_msgs += 1
    except IntentionalKillProcessOfMoveOrDeleteMessages:
        if server_comm_ch:
            await server_comm_ch.send(f"The `/move_messages` command by {interaction.user.name} from {from_msg.jump_url} to {dest_start_msg.jump_url} was intentionally stopped before completion by the `/kill_process` command.")
        print(f"AAO Helper: Move messages was interrupted from channel `#{src_ch.name}` ({src_ch.id}) in server **{src_ch.guild.name}** to channel `#{dest_ch.name}` ({dest_ch.id}) in server **{dest_ch.guild.name}**.")
        await interaction.followup.send(f"This process was intentionally stopped before completion by the `/kill_process` command.", ephemeral=True)
        return
    
    delete_aborted_str = f' up to the delete limit of {DELETE_LIMIT} messages' if delete_aborted else ''
    if server_comm_ch:
        await server_comm_ch.send(f"{interaction.user.name} moved {num_msgs} message{'' if num_msgs == 1 else 's'} from {from_msg.jump_url} to {dest_start_msg.jump_url} using the `/move_messages` command{' and deleted the original messages' if del_orig else ''}{delete_aborted_str}.")
    print(f"AAO Helper: {interaction.user.name} moved {num_msgs} message{'' if num_msgs == 1 else 's'} from channel `#{src_ch.name}` ({src_ch.id}) in server **{src_ch.guild.name}** to channel `#{dest_ch.name}` ({dest_ch.id}) in server **{dest_ch.guild.name}** using the `/move_messages` command{' and deleted the original messages' if del_orig else ''}{delete_aborted_str}.")
    await interaction.followup.send(f"Successfully moved {num_msgs} message{'' if num_msgs == 1 else 's'} to {dest_start_msg.jump_url}{' and deleted the original messages' if del_orig else ''}{delete_aborted_str}.", ephemeral=True)


@tree.command(description=f"Delete multiple messages in a channel up to {DELETE_LIMIT} messages at a time. Must be Mod to use.")
@app_commands.checks.has_role(MOD_ROLE_ID)
@app_commands.checks.bot_has_permissions(read_message_history=True, manage_messages=True)
@app_commands.describe(
    from_message_id="ID of the earliest message to delete",
    up_to_message_id="ID of the latest message to delete",
    user_filter="@mention (press space at end) or user ID of the only user(s) to include. Precede with '-' to exclude users instead (optional, defaults to all users)",
)
async def bulk_delete_messages(
    interaction: discord.Interaction,
    from_message_id: str,
    up_to_message_id: str,
    user_filter: Optional[str] = None,
):
    try:
        check_kill_flag()
    except IntentionalKillProcessOfMoveOrDeleteMessages:
        await interaction.response.send_message(f"Please wait for a grace period of {KILL_DURATION} seconds after using the `/kill_process` command.", ephemeral=True)
        return
    channel = interaction.channel
    try:
        from_message_id = int(from_message_id)  # necessary in case message_id exceeds int53 limit so slash command would reject an int input
    except ValueError:
        await interaction.response.send_message("Must enter a valid from message ID.", ephemeral=True)
        return
    try:
        up_to_message_id = int(up_to_message_id)  # necessary in case message_id exceeds int53 limit so slash command would reject an int input
    except ValueError:
        await interaction.response.send_message("Must enter a valid up to message ID.", ephemeral=True)
        return
    try:
        from_msg = await channel.fetch_message(from_message_id)
    except discord.NotFound:
        await interaction.response.send_message("'From' message not found in current channel. Please check the message ID and try again.", ephemeral=True)
        return
    try:
        to_msg = await channel.fetch_message(up_to_message_id)
    except discord.NotFound:
        await interaction.response.send_message("'To' message not found in current channel. Please check the message ID and try again.", ephemeral=True)
        return
    if from_msg.created_at >= to_msg.created_at:
        await interaction.response.send_message("'To' message must be after 'From' message. Please check the message IDs and try again.", ephemeral=True)
        return
    
    users = []
    exclude = False
    if user_filter:
        if '-' in user_filter.strip()[1:]:
            await interaction.response.send_message("Invalid user filter syntax. Use only one `-` at the start to exclude users; do not put `-` anywhere else.", ephemeral=True)
            return
        if user_filter.strip().startswith('-'):
            exclude = True
        user_ids = re.findall(r"(\d+)", user_filter)
        for u_id in user_ids:
            if len(u_id) < 12:
                await interaction.response.send_message(f"Number received as user_id `{u_id}` was under 12 digits (arbitrary sanity check). If this was actually correct, please enter the number padded with leading 0's.", ephemeral=True)
                return
            user = bot.get_user(int(u_id))
            if not user:
                await interaction.response.send_message(f"No user found with ID `{u_id}`. Please check the user ID and try again.", ephemeral=True)
                return
            users.append(user)
    
    await interaction.response.defer(ephemeral=True) # the following code may take a while, so must defer response so that interaction does not time out
    msgs_deleted = 0
    if users:
        if exclude:
            messages = [msg for msg in messages if msg.author not in users]
        else:
            messages = [msg for msg in messages if msg.author in users]
    msg_fetch = [message async for message in channel.history(after=from_msg, before=to_msg, limit=DELETE_LIMIT-1, oldest_first=True)]
    to_endpoint = [to_msg] if len(msg_fetch) < DELETE_LIMIT-1 else []
    messages = [from_msg] + msg_fetch + to_endpoint
    for msg in messages:
        try:
            check_kill_flag()
        except IntentionalKillProcessOfMoveOrDeleteMessages:
            print(f"AAO Helper: Bulk delete messages was interrupted in channel `#{channel.name}` ({channel.id}) in server **{channel.guild.name}**.")
            break
        if msgs_deleted >= DELETE_LIMIT:
            break
        await asyncio.sleep(RATE_LIMIT_GAP)
        try:
            await msg.delete()
            msgs_deleted += 1
        except:
            pass # if message was already deleted or can't be deleted, just ignore and keep going
    
    delete_limit_str = f' The delete limit of {DELETE_LIMIT} was reached so some intended messages may not have been deleted.' if msgs_deleted >= DELETE_LIMIT else ''
    for guild in bot.guilds:
        server_comm_ch = guild.get_channel_or_thread(SERVER_COMM_CH)
        if server_comm_ch:
            await server_comm_ch.send(f"{interaction.user.name} bulk deleted {msgs_deleted} messages from {from_msg.jump_url} using the `/bulk_delete_messages` command.")
    print(f"AAO Helper: {interaction.user.name} bulk deleted {msgs_deleted} messages from channel `#{channel.name}` ({channel.id}) in server **{channel.guild.name}**.")
    await interaction.followup.send(f"Successfully deleted {msgs_deleted} messages.{delete_limit_str}", ephemeral=True)



@tasks.loop(minutes=BACKUP_LOOP_MINS)
async def backup_channels():
    try:
        check_kill_flag()
    except IntentionalKillProcessOfMoveOrDeleteMessages:
        await asyncio.sleep(KILL_DURATION)
    cur.execute("SELECT src_channel_id, dest_channel_id, last_msg_timestamp, last_backup_timestamp, backup_interval, channel_and_guild_names FROM channel_backups")
    channels_to_backup = cur.fetchall()
    for guild in bot.guilds:
        server_comm_ch = guild.get_channel_or_thread(SERVER_COMM_CH)
        if server_comm_ch: 
            break
    async def deal_error(error_msg, src_ch_id, dest_ch_id):
        cur.execute("DELETE FROM channel_backups WHERE src_channel_id = ? AND dest_channel_id = ?", (src_ch_id, dest_ch_id))
        conn.commit()
        print(f"AAO Helper: Removed the backup from channel `#{src_ch_name}` ({src_ch_id}) in server **{src_guild_name}** to channel `#{dest_ch_name}` ({dest_ch_id}) in server **{dest_guild_name}** due to error: {error_msg}")
        if server_comm_ch:
            await server_comm_ch.send(error_msg + "\n*This backup pipeline has been removed to prevent error spam.*")
    try:
        for src_ch_id, dest_ch_id, last_msg_timestamp, last_backup_timestamp, backup_interval, channel_and_guild_names in channels_to_backup:
            src_ch = None
            dest_ch = None
            src_ch_name, src_guild_name, dest_ch_name, dest_guild_name = json.loads(channel_and_guild_names) # list, not tuple
            for guild in bot.guilds:
                if not src_ch:
                    src_ch = guild.get_channel_or_thread(src_ch_id)
                if not dest_ch:
                    dest_ch = guild.get_channel_or_thread(dest_ch_id)
            if not src_ch and not dest_ch:
                await deal_error(f"Both channels for the backup pipeline from channel `#{src_ch_name}` ({src_ch_id}) in server **{src_guild_name}** to channel `#{dest_ch_name}` ({dest_ch_id}) in server **{dest_guild_name}** could not be found.", src_ch_id, dest_ch_id)
                continue
            if src_ch:
                src_ch_name = src_ch.name
                src_guild_name = src_ch.guild.name
                if not src_ch.permissions_for(guild.me).read_message_history:
                    await deal_error(f"Missing read message history permission for channel `#{src_ch_name}` ({src_ch_id}) in server **{src_guild_name}**. The destination channel was expected to be channel `#{dest_ch_name}` ({dest_ch_id}) in server **{dest_guild_name}**.", src_ch_id, dest_ch_id)
                    continue
            else:
                await deal_error(f"Source channel `#{src_ch_name}` ({src_ch_id}) in server **{src_guild_name}** could not be found. The destination channel was expected to be channel `#{dest_ch_name}` ({dest_ch_id}) in server **{dest_guild_name}**.", src_ch_id, dest_ch_id)
                continue
            if dest_ch:
                dest_ch_name = dest_ch.name
                dest_guild_name = dest_ch.guild.name
                if not dest_ch.permissions_for(guild.me).manage_webhooks:
                    await deal_error(f"Missing manage webhooks permission for channel `#{dest_ch_name}` ({dest_ch_id}) in server **{dest_guild_name}**. The source channel was expected to be channel `#{src_ch_name}` ({src_ch_id}) in server **{src_guild_name}**.", src_ch_id, dest_ch_id)
                    continue
            else:
                await deal_error(f"Destination channel `#{dest_ch_name}` ({dest_ch_id}) in server **{dest_guild_name}** could not be found. The source channel was expected to be channel `#{src_ch_name}` ({src_ch_id}) in server **{src_guild_name}**.", src_ch_id, dest_ch_id)
                continue
            if datetime.now(timezone.utc) - datetime.fromtimestamp(last_backup_timestamp, tz=timezone.utc) < timedelta(days=backup_interval):
                continue
            
            
            print(f"AAO Helper: Starting backup from channel `#{src_ch_name}` ({src_ch_id}) in server **{src_guild_name}** to channel `#{dest_ch_name}` ({dest_ch_id}) in server **{dest_guild_name}**.")
            messages_to_backup = [message async for message in src_ch.history(after=datetime.fromtimestamp(last_msg_timestamp, tz=timezone.utc) if last_msg_timestamp else None, oldest_first=True)]
            from_msg = messages_to_backup[0] if messages_to_backup else None
            while messages_to_backup:
                await move_msgs(dest_ch, messages_to_backup)
                last_msg = messages_to_backup[-1]
                messages_to_backup = [message async for message in src_ch.history(after=last_msg, oldest_first=True)]
            cur.execute(
                """UPDATE channel_backups SET last_backup_timestamp = ?, channel_and_guild_names = ? WHERE src_channel_id = ? AND dest_channel_id = ?""", 
                (datetime.now(timezone.utc).timestamp(), json.dumps([src_ch_name, src_guild_name, dest_ch_name, dest_guild_name]), src_ch.id, dest_ch.id)
                )
            conn.commit()
            print(f"AAO Helper: Backup completed from channel `#{src_ch_name}` ({src_ch_id}) in server **{src_guild_name}** to channel `#{dest_ch_name}` ({dest_ch_id}) in server **{dest_guild_name}**.")
            if from_msg and server_comm_ch:  # don't send backup complete message if there were no messages to back up, since that would be spammy
                await server_comm_ch.send(f"Backup complete for channel `#{src_ch_name}` ({src_ch.id}) in server **{src_guild_name}** to channel `#{dest_ch_name}` ({dest_ch.id}) in server **{dest_guild_name}**. Backed up messages starting from: {from_msg.jump_url}")
    except IntentionalKillProcessOfMoveOrDeleteMessages:
        print(f"AAO Helper: Backup was interrupted from channel `#{src_ch.name}` ({src_ch.id}) in server **{src_guild_name}** to channel `#{dest_ch.name}` ({dest_ch.id}) in server **{dest_guild_name}**.")
        pass


@backup_channels.before_loop
async def before_backup_channels():
    await bot.wait_until_ready()


@tree.command(description="Create backup pipeline to regularly save messages from CURRENT channel. Must be Staff to use.")
@app_commands.checks.has_role(STAFF_ROLE_ID)
@app_commands.checks.bot_has_permissions(read_message_history=True, manage_messages=True)
@app_commands.describe(
    to_channel_id="ID or # of the channel or thread to back up messages to",
    backup_interval="Time between automatic backups",
    after_message_id="ID of the message after which (not inclusive) to start auto backups. Defaults to start of channel.",
)
@app_commands.choices(backup_interval=[
    app_commands.Choice(name="1 day", value=1.0),
    app_commands.Choice(name="1 week", value=7.0),
    app_commands.Choice(name="1 month", value=30.0),
])
async def auto_backup_channel(
    interaction: discord.Interaction,
    to_channel_id: str,
    backup_interval: app_commands.Choice[float],
    after_message_id: Optional[str] = None,
):
    src_ch = interaction.channel
    try:
        to_channel_id = int(to_channel_id)  # necessary in case channel_id exceeds int53 limit so slash command would reject an int input
    except ValueError:
        if re.findall(r"<#(\d+)>", to_channel_id):
            to_channel_id = int(re.findall(r"<#(\d+)>", to_channel_id)[0])
        else:
            await interaction.response.send_message("Must enter a valid destination channel ID.", ephemeral=True)
            return
    if to_channel_id == src_ch.id:
        await interaction.response.send_message("Destination channel must be different from current channel.", ephemeral=True)
        return
    try:
        if after_message_id is not None:
            after_message_id = int(after_message_id)  # necessary in case message_id exceeds int53 limit so slash command would reject an int input
    except ValueError:
        await interaction.response.send_message("Must enter a valid 'After' message ID.", ephemeral=True)
        return
    for guild in bot.guilds:
        dest_ch = guild.get_channel_or_thread(to_channel_id)
        if dest_ch:
            dest_guild = guild
            break
    if dest_ch is None:
        await interaction.response.send_message("Destination channel not found. Please check the channel ID and try again.", ephemeral=True)
        return
    if not isinstance(dest_ch, (discord.TextChannel, discord.Thread)):
        await interaction.response.send_message("Destination must be a text channel or thread.", ephemeral=True)
        return
    if not dest_ch.permissions_for(dest_guild.me).manage_webhooks:
        await interaction.response.send_message("Need Manage Webhooks permission in the destination channel to back up messages.", ephemeral=True)
        return

    try:
        after_msg = await src_ch.fetch_message(after_message_id) if after_message_id else None
    except discord.NotFound:
        await interaction.response.send_message("'After' message not found in current channel. Please check the message ID and try again.", ephemeral=True)
        return

    cur.execute(
        "SELECT * FROM channel_backups WHERE src_channel_id = ? AND dest_channel_id = ?",
        (src_ch.id, dest_ch.id)
    )
    if cur.fetchone():
        await interaction.response.send_message(f"A backup pipeline already exists for this pair of channels. Run `/remove_channel_backup` to remove it first.", ephemeral=True)
        return
    
    confirm_word = "PROCEED"  # uppercase, user must type in all caps
    def check(msg: discord.Message):
        return msg.channel.id == interaction.channel_id and msg.author.id == interaction.user.id
    
    await interaction.response.defer(ephemeral=True)
    if after_msg is None and dest_ch.last_message_id:
        await interaction.followup.send(f"WARNING: Since no 'After' message ID was provided, backup will start from the beginning of this channel. However, ***the destination channel is not empty*** which may mean you forgot to provide an 'After' message ID to start backup from a later point. Please type `{confirm_word}` (in all caps) if you want to create the backup pipeline from the beginning anyway.", ephemeral=True)
        input_msg = await bot.wait_for('message', timeout=600.0, check=check)
        input_msg_content = input_msg.content.strip()
        await input_msg.delete()
        if input_msg_content != confirm_word:
            await interaction.followup.send("Backup pipeline creation canceled.", ephemeral=True)
            return

    cur.execute(
        """
        INSERT INTO channel_backups (src_channel_id, dest_channel_id, last_msg_timestamp, last_backup_timestamp, backup_interval, channel_and_guild_names)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (src_ch.id, dest_ch.id, after_msg.created_at.timestamp() if after_msg else 0, 0, backup_interval.value, json.dumps([src_ch.name, src_ch.guild.name, dest_ch.name, dest_guild.name])),
     )
    conn.commit()

    for guild in bot.guilds:
        server_comm_ch = guild.get_channel_or_thread(SERVER_COMM_CH)
        if server_comm_ch:
            break
    if server_comm_ch:
        await server_comm_ch.send(f"{interaction.user.name} created a backup pipeline for channel `#{src_ch.name}` ({src_ch.id}) in server **{src_ch.guild.name}** to channel `#{dest_ch.name}` ({dest_ch.id}) in server **{dest_guild.name}** every {backup_interval.name} using the `/auto_backup_channel` command.")
    print(f"AAO Helper: {interaction.user.name} created a backup for channel `#{src_ch.name}` ({src_ch.id}) in server **{src_ch.guild.name}** to channel `#{dest_ch.name}` ({dest_ch.id}) in server **{dest_guild.name}** every {backup_interval.name}.")
    await interaction.followup.send(f"Backup pipeline created to move messages from {src_ch.mention} to {dest_ch.mention} every {backup_interval.name}. It should start backing up within {BACKUP_LOOP_MINS} minute{'s' if BACKUP_LOOP_MINS != 1 else ''} unless another backup starts or is currently in progress.", ephemeral=True)


@tree.command(description="Remove an automatic backup pipeline between two channels. Must be Mod to use.")
@app_commands.checks.has_role(MOD_ROLE_ID)
@app_commands.describe(
    from_channel_id="ID or # of the channel or thread that messages are being backed up from",
    to_channel_id="ID or # of the channel or thread that messages are being backed up to",
)
async def remove_channel_backup(interaction: discord.Interaction, from_channel_id: str, to_channel_id: str):
    try:
        from_channel_id = int(from_channel_id)  # necessary in case channel_id exceeds int53 limit so slash command would reject an int input
    except ValueError:
        if re.findall(r"<#(\d+)>", from_channel_id):
            from_channel_id = int(re.findall(r"<#(\d+)>", from_channel_id)[0])
        else:
            await interaction.response.send_message("Must enter a valid 'From' channel ID.", ephemeral=True)
            return
    try:
        to_channel_id = int(to_channel_id)  # necessary in case channel_id exceeds int53 limit so slash command would reject an int input
    except ValueError:
        if re.findall(r"<#(\d+)>", to_channel_id):
            to_channel_id = int(re.findall(r"<#(\d+)>", to_channel_id)[0])
        else:
            await interaction.response.send_message("Must enter a valid 'To' channel ID.", ephemeral=True)
            return
    
    cur.execute(
        "SELECT * FROM channel_backups WHERE src_channel_id = ? AND dest_channel_id = ?",
        (from_channel_id, to_channel_id)
    )
    row = cur.fetchone()
    if not row:
        await interaction.response.send_message(f"No backup pipeline found for this pair of channels.", ephemeral=True)
        return
    
    src_ch_name, src_guild_name, dest_ch_name, dest_guild_name = json.loads(row[5])
    
    cur.execute(
        "DELETE FROM channel_backups WHERE src_channel_id = ? AND dest_channel_id = ?",
        (from_channel_id, to_channel_id)
    )
    conn.commit()

    for guild in bot.guilds:
        server_comm_ch = guild.get_channel_or_thread(SERVER_COMM_CH)
        if server_comm_ch:
            break
    if server_comm_ch:
        await server_comm_ch.send(f"{interaction.user.name} removed the backup pipeline for channel `#{src_ch_name}` ({from_channel_id}) in server **{src_guild_name}** to channel `#{dest_ch_name}` ({to_channel_id}) in server **{dest_guild_name}** using the `/remove_channel_backup` command.")
    print(f"AAO Helper: {interaction.user.name} removed the backup from channel `#{src_ch_name}` ({from_channel_id}) in server **{src_guild_name}** to channel `#{dest_ch_name}` ({to_channel_id}) in server **{dest_guild_name}**.")
    await interaction.response.send_message(f"Backup pipeline removed for channel `#{src_ch_name}` ({from_channel_id}) in server **{src_guild_name}** to channel `#{dest_ch_name}` ({to_channel_id}) in server **{dest_guild_name}**.", ephemeral=True)


@tree.command(description="List all active channel backup pipelines. Must be Staff to use.")
@app_commands.checks.has_role(STAFF_ROLE_ID)
async def list_channel_backups(interaction: discord.Interaction):
    cur.execute("SELECT src_channel_id, dest_channel_id, last_backup_timestamp, backup_interval, channel_and_guild_names FROM channel_backups")
    channels_to_backup = cur.fetchall()
    if not channels_to_backup:
        await interaction.response.send_message("No active channel backup pipelines.", ephemeral=True)
        return
    
    msg = f"Active channel backup pipelines ({len(channels_to_backup)} total):\n\n"
    for src_ch_id, dest_ch_id, last_backup_timestamp, backup_interval, channel_and_guild_names in channels_to_backup:
        src_ch_name, src_guild_name, dest_ch_name, dest_guild_name = json.loads(channel_and_guild_names)
        msg += f"From channel `#{src_ch_name}` ({src_ch_id}) in server **{src_guild_name}** to channel `#{dest_ch_name}` ({dest_ch_id}) in server **{dest_guild_name}** backed up every {backup_interval} days. Last backup: {discord.utils.format_dt(datetime.fromtimestamp(last_backup_timestamp), style='S') if last_backup_timestamp else '`Never`'}\n\n"

    await interaction.response.defer(ephemeral=True)
    for chunk in [msg[i:i+MESSAGE_LIMIT] for i in range(0, len(msg), MESSAGE_LIMIT)]:
        await interaction.followup.send(chunk, ephemeral=True)


@tree.command(description=f"Reset time of last backup to Never. Next backup will happen within {BACKUP_LOOP_MINS} mins. Must be Staff to use.")
@app_commands.checks.has_role(STAFF_ROLE_ID)
@app_commands.describe(
    from_channel_id="ID or # of the channel or thread that messages are being backed up from",
    to_channel_id="ID or # of the channel or thread that messages are being backed up to",
)
async def backup_pronto(interaction: discord.Interaction, from_channel_id: str, to_channel_id: str):
    try:
        from_channel_id = int(from_channel_id)  # necessary in case channel_id exceeds int53 limit so slash command would reject an int input
    except ValueError:
        if re.findall(r"<#(\d+)>", from_channel_id):
            from_channel_id = int(re.findall(r"<#(\d+)>", from_channel_id)[0])
        else:
            await interaction.response.send_message("Must enter a valid 'From' channel ID.", ephemeral=True)
            return
    try:
        to_channel_id = int(to_channel_id)  # necessary in case channel_id exceeds int53 limit so slash command would reject an int input
    except ValueError:
        if re.findall(r"<#(\d+)>", to_channel_id):
            to_channel_id = int(re.findall(r"<#(\d+)>", to_channel_id)[0])
        else:
            await interaction.response.send_message("Must enter a valid 'To' channel ID.", ephemeral=True)
            return
    
    cur.execute(
        "SELECT * FROM channel_backups WHERE src_channel_id = ? AND dest_channel_id = ?",
        (from_channel_id, to_channel_id)
    )
    row = cur.fetchone()
    if not row:
        await interaction.response.send_message(f"No backup pipeline found for this pair of channels.", ephemeral=True)
        return
    
    src_ch_name, src_guild_name, dest_ch_name, dest_guild_name = json.loads(row[5])
    
    cur.execute(
        "UPDATE channel_backups SET last_backup_timestamp = ? WHERE src_channel_id = ? AND dest_channel_id = ?",
        (0, from_channel_id, to_channel_id)
    )
    conn.commit()

    for guild in bot.guilds:
        server_comm_ch = guild.get_channel_or_thread(SERVER_COMM_CH)
        if server_comm_ch:
            break
    if server_comm_ch:
        await server_comm_ch.send(f"{interaction.user.name} reset the 'last backup' time for the backup pipeline from channel `#{src_ch_name}` ({from_channel_id}) in server **{src_guild_name}** to channel `#{dest_ch_name}` ({to_channel_id}) in server **{dest_guild_name}** using the `/backup_pronto` command. The next backup will happen within {BACKUP_LOOP_MINS} minute{'s' if BACKUP_LOOP_MINS != 1 else ''} unless another backup starts or is currently in progress.")
    print(f"AAO Helper: {interaction.user.name} reset the backup cycle from channel `#{src_ch_name}` ({from_channel_id}) in server **{src_guild_name}** to channel `#{dest_ch_name}` ({to_channel_id}) in server **{dest_guild_name}**. The next backup will happen within {BACKUP_LOOP_MINS} minute{'s' if BACKUP_LOOP_MINS != 1 else ''} unless another backup runs or is running.")
    await interaction.response.send_message(f"'Last backup' time reset for channel `#{src_ch_name}` ({from_channel_id}) in server **{src_guild_name}** to channel `#{dest_ch_name}` ({to_channel_id}) in server **{dest_guild_name}**. The next backup will happen within {BACKUP_LOOP_MINS} minute{'s' if BACKUP_LOOP_MINS != 1 else ''} unless another backup starts or is currently in progress.", ephemeral=True)


@tree.command(description="Halt the process of moving, deleting, or backing up messages. Must be Staff to use.")
@app_commands.checks.has_role(STAFF_ROLE_ID)
async def kill_process(interaction: discord.Interaction):
    global kill_flag
    kill_flag = datetime.now(timezone.utc)
    for guild in bot.guilds:
        server_comm_ch = guild.get_channel_or_thread(SERVER_COMM_CH)
        if server_comm_ch:
            break
    if server_comm_ch:
        await server_comm_ch.send(f"{interaction.user.name} issued the `kill_process` command for moving, deleting, or backing up messages. Execution was gracefully interrupted if any such processes were running. If auto backup was interrupted, it should resume in {BACKUP_LOOP_MINS} minute{'s' if BACKUP_LOOP_MINS != 1 else ''}.")
    print(f"AAO Helper: {interaction.user.name} halted all processes for moving, deleting, or backing up messages. If auto backup was interrupted, it should resume in {BACKUP_LOOP_MINS} minute{'s' if BACKUP_LOOP_MINS != 1 else ''}.")
    await interaction.response.send_message(f"Kill signal sent. Wait {KILL_DURATION} seconds before attempting a move or delete command again. Auto backup should resume in {BACKUP_LOOP_MINS} minute{'s' if BACKUP_LOOP_MINS != 1 else ''}.", ephemeral=True)