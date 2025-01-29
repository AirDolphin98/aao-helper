import asyncio

import discord
from discord import app_commands
from discord.ext import tasks
from typing import Optional
import re
import random
import types
import datetime as datetime_module  # stupid aspect of datetime being also an object
from datetime import datetime, timezone, timedelta

from announcement import *
from params import *
from rank_grant import *
from embed_maker import *
from showcase import *
from exhibition import *
from thread_auto_manage import *
from hall_of_fame import *

# Ensure we have a good entropy pool to get started
random.seed(int.from_bytes(os.urandom(128), 'big'))


@tree.command(description="Randomly assign sides for 2-5 players")
@app_commands.checks.bot_has_permissions(send_messages=True)
@app_commands.describe(
    player_one='Player one\'s name',
    player_two='Player two\'s name',
    player_three='Player three\'s name',
    player_four='Player four\'s name',
    player_five='Player five\'s name',
)
async def sides(interaction: discord.Interaction, player_one: str, player_two: str, player_three: Optional[str] = None,
                player_four: Optional[str] = None, player_five: Optional[str] = None):
    if DEBUG:
        print("sides command received")
    players = [player_one, player_two, player_three, player_four, player_five]
    if DEBUG:
        print(f"players: {players}")
    players = [x for x in players if x]
    if DEBUG:
        print(f"players: {players}")
    random.shuffle(players)
    if DEBUG:
        print(f"players: {players}")
    amount = len(players)
    if DEBUG:
        print(f"amount: {amount}")
    g = amount - 2
    if DEBUG:
        print(f"g: {g}")
    game_sides = [
        ['<:axis:665257614002749482>', '<:allies:665257668797267989>'],
        ['<:allies:665257668797267989>', '<:germany_aa:660218154286448676>', '<:japan_aa:660218154638901279>'],
        ['<:us_r:1180308567694250055>', '<:united_kingdom:660218154378854401>', '<:germany_aa:660218154286448676>',
         '<:japan_aa:660218154638901279>'],
        ['<:soviet_union:660218154227859457>', '<:germany_aa:660218154286448676>',
         '<:united_kingdom:660218154378854401>', '<:japan_aa:660218154638901279>',
         '<:united_states:660218154160619533>'],
    ]
    if DEBUG:
        res = '\n'.join(a + b for a, b in zip(game_sides[g], players))
        print(f"res: {res}\n\n")
        await interaction.response.send_message(res)
    else:
        await interaction.response.send_message('\n'.join(a + b for a, b in zip(game_sides[g], players)))


# Roll a six sided die. Optional user-input argument `amount`. if not specified, defaults to 1
@tree.command(description='Rolls selected amount of d6 dice, or one d6 die if no integer is specified')
@app_commands.checks.bot_has_permissions(send_messages=True)
@app_commands.describe(amount='Amount of dice to roll. Leave empty for one')
async def dice(interaction: discord.Interaction, amount: Optional[int]):
    if DEBUG:
        print("dice command received")

    amount = amount if amount else 1
    # Empty list for each of the six dice
    output = [0,0,0,0,0,0]
    # i is an iterator used to repeat rolling a die `amount` of times
    i = 0
    while i < amount:
        # Uses 0,5 rather than 1,6 because lists (arrays) are indexed starting from 0
        # This effectively means the die roll outputs are incremented by one (in theory, not in the code)
        die = random.randint(0,5)
        output[die] += 1
        i += 1

    # List for emoji, to be zipped with the `output` next ...
    emoji = [
        "<:dice_one:665298149274943550>",
        "<:dice_two:711992588709920779>",
        "<:dice_three:711992763209744415>",
        "<:dice_four:711992276724744253>",
        "<:dice_five:711992019349799005>",
        "<:dice_six:665298304732495892>"
    ]

    res: str = ""
    for item in zip(emoji,output):
        res += f"{str(item[0])} {str(item[1])}\n"

    if DEBUG:
        print(f'res: {res}')

    await interaction.response.send_message(res)


@tree.command(description="Ping all non-Staff, non-bot members who don't have Commanders role.")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(
    limit='A cap on the number of mentions if Automod is a concern'
)
async def list_non_commanders_mem_pings(interaction: discord.Interaction, limit: Optional[int] = None):
    if interaction.channel_id != SERVER_COMM_CH:
        await interaction.response.send_message("Only callable in #server-commands channel so as not to mass ping", ephemeral=True)
        return
    server_comm_ch = interaction.guild.get_channel_or_thread(SERVER_COMM_CH)
    if not server_comm_ch:
        await interaction.response.send_message("No #server-commands channel found", ephemeral=True)
        return
    commanders_role = interaction.guild.get_role(COMMANDERS_ROLE_ID)
    staff_role = interaction.guild.get_role(STAFF_ROLE_ID)
    if not commanders_role or not staff_role:
        await interaction.response.send_message("Error: either Commanders or Staff role not valid. Check program params", ephemeral=True)
        return
    roleless = []
    for mem in interaction.guild.members:
        if commanders_role not in mem.roles and not (staff_role in mem.roles or mem.bot):
            roleless.append(mem)
    report = ""
    header = "Members (not Staff or bot) missing Commanders role:\n"
    err_msg = "Truncated--too many members missing Commanders role..."
    for i, mem in enumerate(roleless):
        report_ = report + mem.mention + "\n"
        if len(report_) >= 2000 - len(err_msg) - len(header) or (limit and i >= limit - 1):
            report += err_msg
            break
        else:
            report = report_
    await interaction.response.send_message(header + report)


class ConfirmDefaultsView(discord.ui.View):
    temp = None  # stores generated temp role; useful if execution is interrupted yet bot is not restarted

    def __init__(self, ch_list: list):
        super().__init__()
        self.ch_list = ch_list

    @discord.ui.button(
        label="Begin",
        style=discord.ButtonStyle.primary
    )
    async def button_callback(self, interaction: discord.Interaction, button):
        await interaction.response.defer()
        button.disabled = True
        await interaction.followup.edit_message(interaction.message.id, view=self)
        interaction_channel = interaction.channel
        if not type(self).temp or type(self).temp not in interaction.guild.roles:
            type(self).temp = await interaction.guild.create_role(name="temp", reason="/push_channels_as_default")
        for ch in self.ch_list:
            await ch.set_permissions(interaction.guild.default_role, read_messages=False)
            await ch.set_permissions(type(self).temp, read_messages=True)
        
        templess_mems = [mem for mem in interaction.guild.members if type(self).temp not in mem.roles]
        mem_count = len(interaction.guild.members)
        init_count = mem_count - len(templess_mems)
        init_tenth = init_count * 10 // mem_count

        def prog_str(tenth):
            return f"Channels to publish have been set private. Now assigning temp role to all server members.\nProgress:\n\n{'O ' * tenth + '- ' * (10 - tenth)}{tenth}/10"
        prog_msg = await interaction.followup.send(prog_str(init_tenth), wait=True)

        async def long_add_temp(count, tenth):
            for mem in templess_mems:
                await mem.add_roles(type(self).temp)
                count += 1
                if count >= mem_count*(tenth+1)/10:
                    tenth += 1
                    await prog_msg.edit(content=prog_str(tenth))
            for ch in self.ch_list:
                await ch.set_permissions(interaction.guild.default_role, read_messages=True)
            await type(self).temp.delete(reason="/push_channels_as_default")
            await interaction_channel.send("Channels should now be public and temp role deleted. Onboarding default for these channels should now be checked for each and every existing member!")

        asyncio.create_task(long_add_temp(init_count, init_tenth))


@tree.command(description="Uses trick to fix Discord's broken Onboarding and push show channel setting onto users")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
@app_commands.describe(
    channel_ids='IDs or #mentions of channels or categories for Onboarding correction'
)
async def push_channels_as_default(interaction: discord.Interaction, channel_ids: str):
    ch_ids = re.findall(r"(\d+)", channel_ids)
    good_chs = []
    bad_chs = ""
    categories_note = ""
    for c_id in ch_ids:
        ch = interaction.guild.get_channel(int(c_id))
        if not ch or ch.type not in [discord.ChannelType.text, discord.ChannelType.forum, discord.ChannelType.category]:
            bad_chs += "\n" + c_id
            continue
        else:
            if ch.type == discord.ChannelType.category:
                categories_note = "\n\nThis will NOT correct members' default setting of categories, even if that is checked in server settings Onboarding. It will just apply this correction to ***SYNCED*** channels within the category. In other words, you still need to call this command whenever new channels are added to a category (or uncategorized for that matter) in the future."
            good_chs.append(ch)
    msg = ("First of all, be sure to set the channels as default in the server settings -> Onboarding -> Default Channels (as distinct from your personal Browse Channels!) so that ***FUTURE*** new members from now on can see them. If you don't do this, those future members will still have problems."
           + categories_note
           + "\n\nThis operation may take a while, proportional to how many members are in the server. The channels will be hidden for at least some members until it's over."
           + ("\n\nSome channel IDs were invalid and will not be processed if you proceed:" if bad_chs else "") + bad_chs)
    await interaction.response.send_message(msg, view=ConfirmDefaultsView(good_chs), ephemeral=True)


# Helper function for refactoring
async def message_checks(message: discord.Message):
    if "<@644511391302025226>" in message.content or "<@!644511391302025226>" in message.content:  # SpectacularVernacular -> SadPuppies
        await message.reply("Did you mean <@!948208421054865410>?")

    if re.search("aa1942calc.com/#/[a-zA-Z0-9-_]+", message.content.lower()):
        if message.embeds:
            await message.edit(suppress=True)


last_msgs = {}


@bot.event
async def on_message(message: discord.Message):
    await message_checks(message)

    shake_thread_on_msg(message)

    channel_id = message.channel.id

    ## anti-spam auto-ban
    if not (message.author.bot or message.author.get_role(STAFF_ROLE_ID) or message.author.get_role(BEAMDOG_ROLE_ID)):
        prev = last_msgs.get(message.author.id)
        limit = 5
        if prev and len(message.content) > 4 and message.content == prev[-1].content and all(
                    channel_id != msg.channel.id for msg in prev):
            prev.append(message)
            if len(prev) >= limit:
                guild = message.author.guild
                bots_channel = guild.get_channel(SERVER_COMM_CH)
                if len(message.author.roles) <= 1:  # only Commanders role
                    await message.author.ban(reason=f"spammed {limit} times")
                    dm_message = f"You have been banned from the server {guild.name} for spamming in channels. This is to guard against link scams. However, if your message was not a scam, you should be unbanned shortly.\n\nIf you have recovered and secured your account, send a friend request to the Discord user '{guild.owner.name}' and you may be unbanned."
                    await message.author.send(dm_message)
                    await bots_channel.send(
                        f"Banned {message.author.mention} who joined <t:{round(message.author.joined_at.timestamp())}:f> for spamming {limit} times \nMessage: {'`' + message.clean_content() + '`'}\n\nSent to user in DMs: {dm_message}")
                else:
                    await bots_channel.send(
                        f"{guild.get_role(MOD_ROLE_ID).mention} {guild.get_role(STAFF_ROLE_ID).mention} Potential spam detected from member {message.author.mention} who has multiple roles")
        else:
            last_msgs[message.author.id] = [message]
    ##

    if message.content.startswith("/sync") and message.author.guild_permissions.manage_guild:
        bot.tree.copy_global_to(guild=message.guild)
        synced = await bot.tree.sync(guild=message.guild)
        await message.reply(f"Synced {len(synced)} app commands in guild {message.guild}")


@bot.event
async def on_message_edit(before, after):
    await message_checks(after)

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await rank_reaction_add(payload)


@bot.event
async def on_member_join(member: discord.Member):
    await asyncio.sleep(60)
    await clean_member_roles(member)


# Don't know how to make this work, so just put it in on_message
@bot.command()
@commands.guild_only()
@commands.is_owner()
async def sync(ctx):
    ctx.bot.tree.copy_global_to(guild=ctx.guild)
    synced = await ctx.bot.tree.sync(guild=ctx.guild)
    await ctx.message.reply(f"Synced with {len(synced)} guilds")


@bot.event
async def on_ready():
    print(f"{bot.user.name} has connected to Discord!")
    if not unarchiver.is_running():
        unarchiver.start()
    if not forum_closer.is_running():
        forum_closer.start()
    if not auto_update_season.is_running():
        auto_update_season.start()


# For persistent views
async def setup_hook_with_views(self):
    self.add_view(ExhibitionStartView())


bot.setup_hook = types.MethodType(setup_hook_with_views, bot)

# Start the bot
bot.run(TOKEN)
