
import discord
from discord import app_commands
from typing import Optional

from params import *


@tree.command(description="Assign showcase roles by pinging members in a showcase channel (follow-up message)")
@app_commands.checks.has_role(STAFF_ROLE_ID)
@app_commands.checks.bot_has_permissions(manage_roles=True)
async def showcase_give_role(interaction: discord.Interaction):
    showcase_dict = SHOWCASE_CHANNELS.get(interaction.channel_id)
    if not showcase_dict:
        await interaction.response.send_message("Must be in a showcase channel.", ephemeral=True)
        return
    showcase_role_id = showcase_dict.get('role')
    if not showcase_role_id:
        await interaction.response.send_message("Role for this channel must be manually assigned (if it exists).", ephemeral=True)
        return
    showcase_role = interaction.guild.get_role(showcase_role_id)
    if not showcase_role:
        await interaction.response.send_message("ERROR: Showcase role not found.", ephemeral=True)
        return
    
    clear_instr = "Slash command `/showcase_clear_role` can be invoked to clear showcase role."
    if showcase_role.members:
        await interaction.response.send_message("A showcase seems to be ongoing already. " + clear_instr, ephemeral=True)
        return
    
    cancel_word = "cancel"  # lowercase

    def check(msg: discord.Message):
        return msg.channel.id == interaction.channel_id and msg.author.id == interaction.user.id and (
                msg.mentions or cancel_word in msg.content.lower())
    
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(f"@ Mention all players to give showcase role to. Make sure to ping YOURSELF too if you are included. Or type `{cancel_word}` to cancel the command.")
    message = await bot.wait_for('message', timeout=600.0, check=check)

    if cancel_word in message.content.lower():
        await interaction.followup.send("Command canceled.", ephemeral=True)
        await message.delete()
        return
    
    member_mentions = [m for m in message.mentions if interaction.guild.get_member(m.id)]
    for mem in member_mentions:
        await mem.add_roles(showcase_role, reason=f"/{interaction.command.name} called by {interaction.user.name}.")
    await interaction.followup.send(f"Showcase role given to {len(member_mentions)} players. " + clear_instr, ephemeral=True)


gallery_msgs = ["Welcome back, thanks for the showcase!"]

@tree.command(description="Clear showcase roles for a showcase channel")
@app_commands.checks.has_role(STAFF_ROLE_ID)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.describe(
    gallery_ping_message="Message to send in gallery channel along with pings of all showcase players"
)
@app_commands.choices(gallery_ping_message=[app_commands.Choice(name=msg, value=msg) for msg in gallery_msgs])
async def showcase_clear_role(interaction: discord.Interaction, gallery_ping_message: Optional[app_commands.Choice[str]] = None):
    showcase_dict = SHOWCASE_CHANNELS.get(interaction.channel_id)
    if not showcase_dict:
        await interaction.response.send_message("Must be in a showcase channel.", ephemeral=True)
        return
    showcase_role = interaction.guild.get_role(showcase_dict['role'])
    if not showcase_role:
        await interaction.response.send_message("ERROR: Showcase role not found.", ephemeral=True)
        return
    
    if not showcase_role.members:
        await interaction.response.send_message("No players found with showcase role.", ephemeral=True)
        return
    
    players = showcase_role.members
    player_pings = ' '.join([user.mention for user in players])
    for user in players:
        await user.remove_roles(showcase_role, reason=f"/{interaction.command.name} called by {interaction.user.name}.")

    server_comm_ch = interaction.guild.get_channel_or_thread(SERVER_COMM_CH)
    if gallery_ping_message:
        gallery_id = showcase_dict['gallery']
        if gallery_id:
            gallery = interaction.guild.get_channel(gallery_id)
            if gallery:
                await gallery.send(f"{gallery_ping_message.value}\n\n{player_pings}")
            else:
                if server_comm_ch:
                    await server_comm_ch.send("WARNING: Gallery channel id stored in program data not found in server.")
    if server_comm_ch:
        await server_comm_ch.send(f"{interaction.user.name} cleared showcase role for #{interaction.channel.name}")
    await interaction.response.send_message(f"Showcase role cleared for {len(players)} players.", ephemeral=True)


@tree.command(description="Moves showcase channel between cache and main category")
@app_commands.checks.has_role(STAFF_ROLE_ID)
@app_commands.checks.bot_has_permissions(manage_channels=True)
async def toggle_showcase(interaction: discord.Interaction):
    showcase_dict = SHOWCASE_CHANNELS.get(interaction.channel_id)
    if not showcase_dict:
        await interaction.response.send_message("Must be in a showcase channel.", ephemeral=True)
        return

    showcase = interaction.guild.get_channel(interaction.channel_id)
    gallery = interaction.guild.get_channel(showcase_dict['gallery'])
    active = interaction.guild.get_channel(showcase_dict['active'])
    archive = interaction.guild.get_channel(ARCHIVE_CATEGORY)
    if not showcase or not active or not archive or not active.type == discord.ChannelType.category or not archive.type == discord.ChannelType.category:
        await interaction.response.send_message("Invalid data stored for showcase channel.", ephemeral=True)
        return
    if showcase.category == archive:
        if gallery:
            await gallery.edit(category=active)
        await showcase.edit(category=active)
        await interaction.response.send_message("Moved channel to active category!", ephemeral=True)
    else:
        if gallery:
            await gallery.edit(category=archive)
        await showcase.edit(category=archive)
        await interaction.response.send_message("Moved channel to archive category!", ephemeral=True)
