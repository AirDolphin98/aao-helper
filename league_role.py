
from params import *
from discord import app_commands
import datetime as datetime_module  # stupid aspect of datetime being also an object
from datetime import datetime, timezone, timedelta


LEAGUE_ROLE_ID = 880252578477244417 #A&A League
LEAGUE_ORG_ID = 874798614122234006 #League Organizer
LEAGUE_CHANNEL_ID = 874084922636255253 #aa-league
AUTO_EXPIRATION_DAYS = 65
EXPIRATION_SAFETY_CAP = 10 #max number of users to auto-remove at once to prevent accidents

"""Debugging in A&AO Test Server"""
if DEBUG:
    LEAGUE_ROLE_ID = 1464455589122936968 #A&A League
    LEAGUE_ORG_ID = 1097804496660340757 #League Org
    LEAGUE_CHANNEL_ID = 942543145365803139 #league
    AUTO_EXPIRATION_DAYS = 0.001 #about 1.44 minutes
""""""


def add_to_league_db(user_id: int):
    now_ts = datetime.now(tz=timezone.utc).timestamp()
    cur.execute(
        """
        INSERT OR REPLACE INTO league_members (user_id, last_updated)
        VALUES (?, ?)
        """,
        (user_id, now_ts)
    )
    conn.commit()


def update_league_db(before: discord.Member, after: discord.Member): # Not only enables regular role add/removal to update db, but is crucial for other functions in this file to work
    if LEAGUE_ROLE_ID in [role.id for role in before.roles] and LEAGUE_ROLE_ID not in [role.id for role in after.roles]:
        # league role removed
        cur.execute("DELETE FROM league_members WHERE user_id = ?", (after.id,))
        conn.commit()
    elif LEAGUE_ROLE_ID in [role.id for role in after.roles] and LEAGUE_ROLE_ID not in [role.id for role in before.roles]:
        # league role added
        add_to_league_db(after.id)


async def expire_league_roles(guild: discord.Guild):
    now = datetime.now(tz=timezone.utc)
    expired_users = []
    for row in cur.execute("SELECT user_id, last_updated FROM league_members"):
        user_id, last_updated_ts = row
        last_updated = datetime.fromtimestamp(last_updated_ts, tz=timezone.utc)
        if (now - last_updated) > timedelta(days=AUTO_EXPIRATION_DAYS):
            member = guild.get_member(user_id)
            if member:
                expired_users.append(member)
    if expired_users:
        server_comm_ch = guild.get_channel_or_thread(SERVER_COMM_CH)
        if len(expired_users) <= EXPIRATION_SAFETY_CAP:
            for member in expired_users:
                await member.remove_roles(guild.get_role(LEAGUE_ROLE_ID), reason=f"Auto-remove due to lack of ping for {AUTO_EXPIRATION_DAYS} days.")
            if server_comm_ch:
                await server_comm_ch.send(f"Auto-removed league role from:\n{"\n".join(member.name for member in expired_users)}\ndue to lack of ping for {AUTO_EXPIRATION_DAYS} days.")
        else:
            if server_comm_ch:
                await server_comm_ch.send(f"Too many inactive league members detected: {len(expired_users)} users (max {EXPIRATION_SAFETY_CAP}). Auto-removal skipped.")
    

async def update_league_on_ping(msg: discord.Message):
    if not isinstance(msg.author, discord.Member):
        return
    if LEAGUE_ORG_ID in [role.id for role in msg.author.roles] \
    and msg.channel.type in [discord.ChannelType.public_thread, discord.ChannelType.private_thread] \
    and msg.channel.parent.id == LEAGUE_CHANNEL_ID:
        missing_users = []
        for user in msg.mentions:
            if not isinstance(user, discord.Member):
                continue
            if LEAGUE_ROLE_ID not in [role.id for role in user.roles]:
                await user.add_roles(msg.guild.get_role(LEAGUE_ROLE_ID), reason=f"Auto-add due to league org ping in league thread: {msg.channel.name}")
                missing_users.append(user)
            else:
                add_to_league_db(user.id) # update last_updated timestamp even if they already have the role
        if missing_users:            
            server_comm_ch = msg.guild.get_channel_or_thread(SERVER_COMM_CH)
            if server_comm_ch:
                await server_comm_ch.send(f"Auto-added league role to:\n{"\n".join(user.name for user in missing_users)}\ndue to league org ping in league thread: {msg.channel.name}")
        await expire_league_roles(msg.guild)


@tree.command(name="align_league_db", description="Aligns league_members database with exactly who has league role right now.")
@app_commands.checks.has_any_role(MOD_ROLE_ID, LEAGUE_ORG_ID)
async def align_league_db(interaction: discord.Interaction):
    db_user_ids = {row[0] for row in cur.execute("SELECT user_id FROM league_members")}
    for member in interaction.guild.get_role(LEAGUE_ROLE_ID).members:
        if member.id not in db_user_ids:
            add_to_league_db(member.id)
        else:
            db_user_ids.remove(member.id)
    for user_id in db_user_ids:
        cur.execute("DELETE FROM league_members WHERE user_id = ?", (user_id,))
    conn.commit()
    await interaction.response.send_message("League database updated to = current role holders. Do /print_league_db to view the updated database contents.", ephemeral=True)
    server_comm_ch = interaction.guild.get_channel_or_thread(SERVER_COMM_CH)
    if server_comm_ch:
        await server_comm_ch.send(f"{interaction.user.name} ran /align_league_db to match the league_members database to the current role holders. Run /print_league_db to view the updated database contents.")


@tree.command(name="print_league_db", description="Prints out the league_members database.")
@app_commands.checks.has_any_role(MOD_ROLE_ID, LEAGUE_ORG_ID)
async def print_league_db(interaction: discord.Interaction):
    rows = cur.execute("SELECT user_id, last_updated FROM league_members").fetchall()
    if not rows:
        await interaction.response.send_message("No entries in the league_members database.", ephemeral=True)
        return
    output = f"league_members database:    Total: {len(rows)} members\nUsername    Last Updated (UTC)\n"
    for user_id, last_updated in rows:
        last_updated = datetime.fromtimestamp(last_updated, tz=timezone.utc)
        output += f"{interaction.guild.get_member(user_id).name}    {last_updated.strftime('%Y-%m-%d %H:%M:%S')}\n"
        if len(output) > 1900:
            await interaction.response.send_message(output, ephemeral=True)
            output = ""
    await interaction.response.send_message(output, ephemeral=True)