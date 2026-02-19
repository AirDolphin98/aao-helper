
# Some of this code is copied from the original Discord MoveBot
# https://github.com/HumanikaRafeki/DiscordMoveBot/blob/master/move_bot.py


from params import *
import discord
from discord import app_commands
from typing import List, Optional
import re
import asyncio


async def move_msgs(dest_ch: discord.abc.GuildChannel, messages: List[discord.Message], link_first_msg: bool = True):
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

    if link_first_msg:
        await dest_ch.send(f"Messages moved from {messages[0].jump_url}")
    for msg in messages:
        msg_content = msg.clean_content or msg.system_content or '[message was empty]'
        msg_wbhk_name = None
        if msg.webhook_id:
            for wbhk in wbhks:
                if wbhk.id == msg.webhook_id:
                    msg_wbhk_name = wbhk.name
                    break
        # prefix with message timestamp unless sent by webhook with recognized name, meaning it was already a moved message
        msg_time_prefix = '' if msg_wbhk_name and msg_wbhk_name in webhook_names else f'[{msg.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")}] '

        sub_msgs = []
        if len(msg_time_prefix + msg_content) <= MESSAGE_LIMIT: # save some processing if message doesn't even need to be split
            sub_msgs.append(msg_time_prefix + msg_content)
        else:
            current_chunk = msg_time_prefix
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
            edited_suffix = '\n-# *(edited)*'
            if len(sub_msgs[-1]) + len(edited_suffix) > MESSAGE_LIMIT:
                sub_msgs.append(edited_suffix)
            else:
                sub_msgs[-1] += edited_suffix
        
        try:
            for i, sub_msg in enumerate(sub_msgs):
                await webhook.send(
                    content=sub_msg,
                    username=msg.author.display_name,
                    avatar_url=msg.author.display_avatar.url,
                    embeds=msg.embeds if i==len(sub_msgs)-1 else [],
                    files=[await attachment.to_file(filename=attachment.filename, spoiler=attachment.is_spoiler(), description=attachment.description if attachment.description else None) for attachment in msg.attachments] if i==len(sub_msgs)-1 else [],
                    wait=True,
                )
                await asyncio.sleep(RATE_LIMIT_GAP)
        except:
            for i, sub_msg in enumerate(sub_msgs):
                await webhook.send(
                    content=sub_msg,
                    username=msg.author.display_name,
                    avatar_url=msg.author.display_avatar.url,
                    embeds=msg.embeds if i==len(sub_msgs)-1 else [],
                    wait=True,
                )
                await asyncio.sleep(RATE_LIMIT_GAP)
            await dest_ch.send(f"[attachments in above message could not be moved]")



@tree.command(description="Move messages from one channel to another. Must be called within the channel to move messages from.")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(read_message_history=True, manage_messages=True)
@app_commands.describe(
    to_channel_id="ID or # of the channel or thread to move messages to",
    from_message_id="ID of the earliest message to move. If only this is provided, only this message will be moved.",
    up_to_message_id="ID of the latest message to move (optional, defaults to only the one message)",
    user_filter="@mention (press space at end) or user ID of the only user(s) to include. Precede with '-' to exclude users instead (optional, defaults to all users)",
    delete_original="Delete original messages after moving (yes/no, default no)",
)
@app_commands.choices(delete_original=[
    app_commands.Choice(name="yes", value="yes"),
    app_commands.Choice(name="no", value="no"),
])
async def move_messages(
    interaction: discord.Interaction,
    to_channel_id: str,
    from_message_id: str,
    up_to_message_id: Optional[str] = None,
    user_filter: Optional[str] = None,
    delete_original: Optional[app_commands.Choice[str]] = "no",
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
    if from_msg.created_at > to_msg.created_at:
        await interaction.response.send_message("'To' message must be after 'From' message. Please check the message IDs and try again.", ephemeral=True)
        return

    if to_msg is None or from_message_id == up_to_message_id:
        messages = [from_msg]
    else:
        working_msgs = [message async for message in src_ch.history(after=from_msg, before=to_msg, oldest_first=True)]
        messages_between = working_msgs.copy()
        while working_msgs:
            asyncio.sleep(RATE_LIMIT_GAP * 10)
            last_msg = working_msgs[-1]
            working_msgs = [message async for message in src_ch.history(after=last_msg, before=to_msg, oldest_first=True)]
            messages_between += working_msgs
        messages = [from_msg] + messages_between + [to_msg]

    if not messages:
        await interaction.response.send_message("Error: No messages found. There may be an unusual bug.", ephemeral=True)
        return
    
    if user_filter:
        exclude = False
        if '-' in user_filter.strip()[1:]:
            await interaction.response.send_message("Invalid user filter syntax. Use only one `-` at the start to exclude users; do not put `-` anywhere else.", ephemeral=True)
            return
        if user_filter.strip().startswith('-'):
            exclude = True
        users = []
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
        if exclude:
            messages = [msg for msg in messages if msg.author not in users]
        else:
            messages = [msg for msg in messages if msg.author in users]
    
    await move_msgs(dest_ch, messages, link_first_msg=True)

    if delete_original.value == "yes":
        for msg in messages:
            try:
                await msg.delete()
                await asyncio.sleep(RATE_LIMIT_GAP)
            except:
                pass # if message was already deleted or can't be deleted, just ignore and keep going
            
        

@tree.command(description="Test channel.history contents")
@app_commands.describe(
    from_msg_id="ID of the earliest message to fetch",
    up_to_msg_id="ID of the latest message to fetch",
    limit="Maximum number of messages to fetch (default 100)"
)
async def test_history(interaction: discord.Interaction, from_msg_id: str, up_to_msg_id: str, limit: int = 100):
    src_ch = interaction.channel
    try:
        from_msg_id = int(from_msg_id)  # necessary in case message_id exceeds int53 limit so slash command would reject an int input
    except ValueError:
        await interaction.response.send_message("Must enter a valid from message ID.", ephemeral=True)
        return
    try:
        up_to_msg_id = int(up_to_msg_id)  # necessary in case message_id exceeds int53 limit so slash command would reject an int input
    except ValueError:
        await interaction.response.send_message("Must enter a valid up to message ID.", ephemeral=True)
        return

    from_msg = await src_ch.fetch_message(from_msg_id)
    to_msg = await src_ch.fetch_message(up_to_msg_id)

    messages = [message async for message in src_ch.history(after=from_msg, before=to_msg, oldest_first=True, limit=limit)]

    print('\n\n-\n'.join([message.content for message in messages]))
    
    await interaction.response.send_message(f"Found {len(messages)} messages between {from_msg.jump_url} and {to_msg.jump_url}")