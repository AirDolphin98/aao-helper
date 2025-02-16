import discord.ui
from discord import app_commands
from discord.ext import tasks
from typing import Optional
import re
import csv
import datetime as datetime_module  # stupid aspect of datetime being also an object
from datetime import datetime, timezone, timedelta

from params import *

TIME_FORMAT = "%Y/%m/%d %H:%M"
MEDAL_TIME = 2  # Number of seasons until medallion rank expires (mid-season counted as previous)
TOP_TIME = 3  # Number of seasons until Top 10 role expires
SEASON_END_WEEKS = 5.0  # Weeks before a season ends where it counts as already that season end
SEASON_START_WEEKS = 5.0  # Weeks after a new season starts where ranks cannot be assigned for the new season

RANK_LIST = ["Top 10", "Platinum", "Gold", "Silver", "Bronze", "Wood"]  # These must not contain commas for upload_ranks() to work
RANK1_LIST = ["#1 Rank Axis", "#1 Rank Allies"]
REQUEST_RANK_CH = 665017042146951188 #request-rank
RANK_DICT = {
    733500181601058896: RANK_LIST[0],
    659913624315232276: RANK_LIST[1],
    660255916305940480: RANK_LIST[2],
    660255959117201431: RANK_LIST[3],
    660255996391849985: RANK_LIST[4],
    660256022450929734: RANK_LIST[5],
    664624127617007618: RANK1_LIST[0],
    664624098311274506: RANK1_LIST[1]
}
LEGACY_ID_DICT = {
    RANK_LIST[0]: 1008640979357663253,
    RANK1_LIST[0]: 1008643621244895322,
    RANK1_LIST[1]: 1008643621244895322
}
REACTION_DICT = {
    # <:platinum:667881631473860667><:gold:667881111149477905><:silver:667880684244828201><:bronze:667882292622000158><:wood:667880131595075595>
    667881631473860667: RANK_LIST[1],
    667881111149477905: RANK_LIST[2],
    667880684244828201: RANK_LIST[3],
    667882292622000158: RANK_LIST[4],
    667880131595075595: RANK_LIST[5]
}
"""Debugging in A&AO Test Server"""
if DEBUG:
    REQUEST_RANK_CH = 864688826005454899 #general
    RANK_DICT = {
        1265216205459951668: RANK_LIST[0],
        943044793074847755: RANK_LIST[1],
        941353136470253638: RANK_LIST[2],
        943044862503186443: RANK_LIST[3],
        1265216424570257488: RANK_LIST[4],
        1276842768987324457: RANK_LIST[5],
        943969266774978580: RANK1_LIST[0],
        943968858170081301: RANK1_LIST[1]
    }
    LEGACY_ID_DICT = {}
    REACTION_DICT = {
        # <:platinum:940837874746675211> <:gold:940837874927038504><:silver:940837874851512340><:bronze:940837874948001822><:wood:940837874834739250>
        940837874746675211: RANK_LIST[1],
        940837874927038504: RANK_LIST[2],
        940837874851512340: RANK_LIST[3],
        940837874948001822: RANK_LIST[4],
        940837874834739250: RANK_LIST[5]
    }
""""""
RANK_ID_DICT = {v: k for k, v in RANK_DICT.items()}
RANK_CHOICES = [app_commands.Choice(name=rank, value=str(role_id)) for role_id, rank in RANK_DICT.items()]

HEADER_LINE = ["#", "Discord Username", "Rank", "Season #", "Note"]


def is_top_10_role_id(role_id):
    return role_id in [RANK_ID_DICT[RANK_LIST[0]]] + [RANK_ID_DICT[r_name] for r_name in RANK1_LIST]


def height(rank: str) -> int:
    if rank not in RANK_LIST:
        raise ValueError("Rank not in RANK_LIST")
    return len(RANK_LIST) - RANK_LIST.index(rank)


def expiry(rank: str, season_num: int) -> int:
    # assumes mid-season = previous season
    if is_top_10_role_id(RANK_ID_DICT[rank]):
        return season_num + TOP_TIME
    else:
        return season_num + MEDAL_TIME


def expiry_back(role_id: int, current_season: int) -> int:
    if is_top_10_role_id(role_id):
        return current_season - TOP_TIME
    else:
        return current_season - MEDAL_TIME


async def delete_rank(guild: discord.Guild, time_added: float, user_id: int, rank: str, commits=True):
    cur.execute(
        "DELETE FROM ranks_added WHERE time_added = ?",
        (time_added,)
    )
    if commits:
        conn.commit()  # conditional, for faster performance in loop

    rank_id = RANK_ID_DICT.get(rank)
    role = guild.get_role(rank_id) if rank_id else None
    user = guild.get_member(user_id)
    if role and user:
        cur.execute(
            "SELECT * FROM ranks_added WHERE user_id = ? AND rank = ?",
            (user_id, rank)
        )
        if not cur.fetchall():
            await user.remove_roles(role)
        legacy = LEGACY_ID_DICT.get(rank)
        if legacy:
            await user.add_roles(guild.get_role(legacy))
    else:
        err_msg = "Unable to remove role:\n"
        if not rank_id:
            err_msg += f"Rank not found in bot program dictionary: {rank}\n"
        elif not role:
            err_msg += f"Role not found in server: {rank_id} ({rank})\n"
        if not user:
            err_msg += f"User not found in server: {user_id}\n"
        await guild.get_channel_or_thread(SERVER_COMM_CH).send(err_msg)


async def add_record(interaction: discord.Interaction, time_added: float, user_id: int, role_id: int, season_num: int,
                     note: str):
    await interaction.response.defer()
    cur.execute(
        "SELECT season_num, end_timestamp FROM current_season_end WHERE guild_id = ?",
        (interaction.guild_id,)
    )
    current_end = cur.fetchone()
    if not current_end:
        await interaction.followup.send("No current season end stored yet. Use slash command `/set_season_end`.", ephemeral=True)
        return
    c_num, end_ts = current_end
    if not season_num:
        await interaction.followup.send("Error in add_record(): season_num given as 0 or None.", ephemeral=True)
        return
    if season_num > c_num:
        await interaction.followup.send(f"Provided season end number cannot be greater than current season number, which is: {c_num}", ephemeral=True)
        return
    if season_num < expiry_back(role_id, c_num):
        await interaction.followup.send(f"Provided season end number cannot be that far in the past for that rank. Current season: {c_num}", ephemeral=True)
        return
    if datetime.now(timezone.utc) - datetime.fromtimestamp(end_ts, timezone.utc) > timedelta(weeks=SEASON_START_WEEKS):
        await interaction.followup.send("Current season end setting is out of date. Wait for bot to auto-update it (preferred, as it can auto-delete ranks too) or use slash command `/set_season_end`.", ephemeral=True)
        return
    if season_num == c_num:
        if is_top_10_role_id(role_id) and datetime.fromtimestamp(end_ts, timezone.utc) - datetime.now(timezone.utc) > timedelta(seconds=0.0):
            await interaction.followup.send("Cannot grant Top 10 role for current season before season end.", ephemeral=True)
            return
        if datetime.fromtimestamp(end_ts, timezone.utc) - datetime.now(timezone.utc) > timedelta(weeks=SEASON_END_WEEKS):
            season_num -= 1
            await interaction.followup.send("Note: since it's mid-season, the current season will be recorded as the previous season.", ephemeral=True)

    async def add_role(r_id):
        if is_mem:
            await user.add_roles(interaction.guild.get_role(r_id))
        cur.execute(
            "INSERT INTO ranks_added (time_added, user_id, rank, season_num, note) VALUES (?, ?, ?, ?, ?)",
            (time_added, user_id, rank_to_add, season_num, note)
        )
        conn.commit()

    rank_to_add = RANK_DICT[role_id]
    is_mem = bool(interaction.guild.get_member(user_id))
    user = interaction.guild.get_member(user_id) if is_mem else bot.get_user(user_id)

    cur.execute(
        "SELECT rank, season_num FROM ranks_added WHERE user_id = ?",
        (user_id,)
    )
    entries = cur.fetchall()

    confirm_str = ""
    if rank_to_add in RANK1_LIST:
        rank1_to_add_entries = [pair for pair in entries if pair[0] == rank_to_add]  # only care if exact same rank; usu. shouldn't be more than 1, but just in case many redundancies somehow
        if not rank1_to_add_entries:
            await add_role(role_id)
            confirm_str = f"{rank_to_add} rank granted!\n"
        else:
            user_rank_entries = sorted(rank1_to_add_entries, key=lambda pair: expiry(rank_to_add, pair[1]), reverse=True)
            for _, s_n in user_rank_entries:
                e_a = expiry(rank_to_add, season_num)
                e = expiry(rank_to_add, s_n)
                if e_a <= e:
                    if not confirm_str:
                        confirm_str = f"{rank_to_add} rank NOT granted, redundant...\n"
                    break  # this is why user_rank_entries is reverse sorted
                elif e_a > e:
                    r_id = RANK_ID_DICT[rank_to_add]
                    if is_mem and user.get_role(r_id):
                        await user.remove_roles(interaction.guild.get_role(r_id))
                    cur.execute(
                        "DELETE FROM ranks_added WHERE user_id = ? AND rank = ? AND season_num = ?",
                        (user_id, rank_to_add, s_n)
                    )
                    conn.commit()
                    await add_role(role_id)
                    if not confirm_str:
                        confirm_str = f"{rank_to_add} rank granted!\n"
                    confirm_str += f"Redundant {rank_to_add} rank also removed.\n"
    else:
        ranks_entries = [pair for pair in entries if pair[0] in RANK_LIST]
        if not ranks_entries:
            await add_role(role_id)
            confirm_str = f"{rank_to_add} rank granted!\n"
        else:
            user_entries = sorted(ranks_entries, key=lambda pair: (height(pair[0]), expiry(pair[0], pair[1])), reverse=True)
            for rank, s_n in user_entries:
                h_a = height(rank_to_add)
                h = height(rank)
                e_a = expiry(rank_to_add, season_num)
                e = expiry(rank, s_n)
                if h_a <= h and e_a <= e:
                    if not confirm_str:
                        confirm_str = f"{rank_to_add} rank NOT granted, redundant...\n"
                    break  # this is why user_entries is reverse sorted
                elif h_a >= h and e_a >= e:
                    r_id = RANK_ID_DICT[rank]
                    if is_mem and user.get_role(r_id):
                        await user.remove_roles(interaction.guild.get_role(r_id))
                    cur.execute(
                        "DELETE FROM ranks_added WHERE user_id = ? AND rank = ? AND season_num = ?",
                        (user_id, rank, s_n)
                    )
                    conn.commit()
                    await add_role(role_id)
                    if not confirm_str:
                        confirm_str = f"{rank_to_add} rank granted!\n"
                    confirm_str += f"Redundant {rank} rank also removed.\n"
                elif h_a > h and e_a < e or h_a < h and e_a > e:
                    await add_role(role_id)
                    if not confirm_str:
                        confirm_str = f"{rank_to_add} rank granted!\n"

    cur.execute(
        "SELECT rank, season_num, note FROM ranks_added WHERE user_id = ?",
        (user_id,)
    )
    info_str = ""
    for entry in cur.fetchall():
        r, s_n, n = entry
        info_str += f"\n\nRank: {r}\nExpires: {SEASON_START_WEEKS} weeks after end of S{expiry(r, s_n)}\nNote: {n}"

    result_print = f"{confirm_str}User's ranks recorded:\n\nUser: {user.display_name if user else '(deleted_user)'}{info_str}"

    server_comm_ch = interaction.guild.get_channel_or_thread(SERVER_COMM_CH)
    if server_comm_ch:
        await server_comm_ch.send(result_print)
    if interaction.channel_id != SERVER_COMM_CH:
        await interaction.followup.send(result_print, ephemeral=True)


async def add_records(interaction: discord.Interaction, rows: list[tuple[float, int, int, int, str]], current_season_num: int, end_timestamp: float):
    index = 0
    with open(show_ranks_path, 'r+') as a_r, open(deleted_ranks_path, 'r+') as error_trace:
        a_r.truncate(0)
        error_trace.truncate(0)
        added_ranks = csv.writer(a_r)
        added_ranks.writerow(HEADER_LINE)
        error_trace.write("Failed Adds")
        for row in rows:
            time_added, user_id, role_id, season_num, note = row
            time_added += 0.0001 * index
            rank_to_add = RANK_DICT[role_id]
            is_mem = bool(interaction.guild.get_member(user_id))
            user = interaction.guild.get_member(user_id) if is_mem else bot.get_user(user_id)
            username = user.name if user else "(deleted_user)"
            row_str = f"\n{username}, {rank_to_add}, {str(season_num)} -- "
            if not season_num:
                error_trace.write(row_str + "Error in add_record(): season_num given as 0 or None.")
                continue
            if season_num > current_season_num:
                error_trace.write(row_str + f"Provided season end number cannot be greater than current season number, which is: {current_season_num}")
                continue
            if season_num < expiry_back(role_id, current_season_num):
                error_trace.write(row_str + f"Provided season end number cannot be that far in the past for that rank. Current season: {current_season_num}")
                continue
            if datetime.now(timezone.utc) - datetime.fromtimestamp(end_timestamp, timezone.utc) > timedelta(weeks=SEASON_START_WEEKS):
                error_trace.write(row_str + "Current season end setting is out of date. Wait for bot to auto-update it (preferred, as it can auto-delete ranks too) or use slash command `/set_season_end`.")
                continue
            if season_num == current_season_num:
                if is_top_10_role_id(role_id) and datetime.fromtimestamp(end_timestamp, timezone.utc) - datetime.now(timezone.utc) > timedelta(seconds=0.0):
                    error_trace.write(row_str + "Cannot grant Top 10 role for current season before season end.")
                    continue
                if datetime.fromtimestamp(end_timestamp, timezone.utc) - datetime.now(timezone.utc) > timedelta(weeks=SEASON_END_WEEKS):
                    season_num -= 1
                    if index == 0:
                        await interaction.followup.send(
                            "Note: since it's mid-season, the current season will be recorded as the previous season.",
                            ephemeral=True)

            async def add_role(r_id):
                if is_mem:
                    await user.add_roles(interaction.guild.get_role(r_id))
                cur.execute(
                    "INSERT INTO ranks_added (time_added, user_id, rank, season_num, note) VALUES (?, ?, ?, ?, ?)",
                    (time_added, user_id, rank_to_add, season_num, note)
                )
                conn.commit()

            row_to_write = [index, username, rank_to_add, season_num, note]

            cur.execute(
                "SELECT rank, season_num FROM ranks_added WHERE user_id = ?",
                (user_id,)
            )
            entries = cur.fetchall()

            if rank_to_add in RANK1_LIST:
                rank1_to_add_entries = [pair for pair in entries if pair[0] == rank_to_add]  # only care if exact same rank; usu. shouldn't be more than 1, but just in case many redundancies somehow
                if not rank1_to_add_entries:
                    await add_role(role_id)
                    added_ranks.writerow(row_to_write)
                    index += 1
                else:
                    user_rank_entries = sorted(rank1_to_add_entries, key=lambda pair: expiry(rank_to_add, pair[1]), reverse=True)
                    added = False
                    for _, s_n in user_rank_entries:
                        e_a = expiry(rank_to_add, season_num)
                        e = expiry(rank_to_add, s_n)
                        if e_a <= e:
                            error_trace.write(row_str + f"{rank_to_add} rank NOT granted, redundant...")
                            break  # this is why user_rank_entries is reverse sorted
                        elif e_a > e:
                            r_id = RANK_ID_DICT[rank_to_add]
                            if is_mem and user.get_role(r_id):
                                await user.remove_roles(interaction.guild.get_role(r_id))
                            cur.execute(
                                "DELETE FROM ranks_added WHERE user_id = ? AND rank = ? AND season_num = ?",
                                (user_id, rank_to_add, s_n)
                            )
                            conn.commit()
                            await add_role(role_id)
                            if not added:
                                added_ranks.writerow(row_to_write)
                                index += 1
                                added = True
                            error_trace.write(
                                row_str + f"Redundant {rank_to_add} rank removed because {rank_to_add} rank granted.")
            else:
                ranks_entries = [pair for pair in entries if pair[0] in RANK_LIST]
                if not ranks_entries:
                    await add_role(role_id)
                    added_ranks.writerow(row_to_write)
                    index += 1
                else:
                    user_entries = sorted(ranks_entries, key=lambda pair: (height(pair[0]), expiry(pair[0], pair[1])),
                                          reverse=True)
                    added = False
                    for rank, s_n in user_entries:
                        h_a = height(rank_to_add)
                        h = height(rank)
                        e_a = expiry(rank_to_add, season_num)
                        e = expiry(rank, s_n)
                        if h_a <= h and e_a <= e:
                            error_trace.write(row_str + f"{rank_to_add} rank NOT granted, redundant...")
                            break  # this is why user_entries is reverse sorted
                        elif h_a >= h and e_a >= e:
                            r_id = RANK_ID_DICT[rank]
                            if is_mem and user.get_role(r_id):
                                await user.remove_roles(interaction.guild.get_role(r_id))
                            cur.execute(
                                "DELETE FROM ranks_added WHERE user_id = ? AND rank = ? AND season_num = ?",
                                (user_id, rank, s_n)
                            )
                            conn.commit()
                            await add_role(role_id)
                            if not added:
                                added_ranks.writerow(row_to_write)
                                index += 1
                                added = True
                            error_trace.write(row_str + f"Redundant {rank} rank removed because {rank_to_add} rank granted.")
                        elif h_a > h and e_a < e or h_a < h and e_a > e:
                            await add_role(role_id)
                            if not added:
                                added_ranks.writerow(row_to_write)
                                index += 1
                                added = True

    server_comm_ch = interaction.guild.get_channel_or_thread(SERVER_COMM_CH)
    if server_comm_ch:
        await server_comm_ch.send(f"Granted {index} ranks! See file for list", file=discord.File(show_ranks_path))
        await server_comm_ch.send(f"Any failed rank adds are listed in the file below", file=discord.File(deleted_ranks_path))
        await interaction.followup.send(f"Successfully granted ranks. See {server_comm_ch.mention}", ephemeral=True)
    else:
        await interaction.followup.send(f"Granted {index} ranks. See file for list", file=discord.File(show_ranks_path))
        await interaction.followup.send(f"Any failed rank adds are listed in the file below", file=discord.File(deleted_ranks_path))


class NoteTakeModal(discord.ui.Modal):
    def __init__(self, view, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.view = view
        self.add_item(discord.ui.TextInput(label="Add user note", placeholder="Can be anything", max_length=50))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.view.set_note(self.children[0].value)


def season_select_options(season_num: int) -> list[discord.SelectOption]:
    if not season_num:
        return [discord.SelectOption(label="No current season set", value="")]
    return [discord.SelectOption(label=str(season_num), default=True)] + [
        discord.SelectOption(label=str(season_num - x))
        for x in range(1, TOP_TIME + 1)]


pressed_ranks = {}


class GrantRankView(discord.ui.View):
    def __init__(self, user: discord.Member, role_id: int, react_msg_id = None) -> None:
        super().__init__()
        self.time_added = datetime.timestamp(datetime.now(timezone.utc))
        self.user = user
        cur.execute("SELECT season_num FROM current_season_end")
        current_end = cur.fetchone()
        self.seasonNum = current_end[0] if current_end else None
        self.role_id = role_id
        self.react_msg_id = react_msg_id
        self.note = ""

        self.select = discord.ui.Select(
            row=0,
            options=season_select_options(self.seasonNum),
            min_values=1,
            max_values=1,
            placeholder="Select season end (mid-season = previous season)"
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    def set_note(self, note):
        self.note = note

    async def select_callback(self, interaction):
        await interaction.response.defer()
        self.seasonNum = int(self.select.values[0]) if self.select.values[0] else None

    @discord.ui.button(
        row=1,
        label="Submit",
        style=discord.ButtonStyle.primary
    )
    async def button_callback_1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await add_record(interaction, self.time_added, self.user.id, self.role_id, self.seasonNum, self.note)
        if self.react_msg_id:
            pressed_ranks[self.react_msg_id] = RANK_DICT[self.role_id]

    @discord.ui.button(
        row=1,
        label="Add note",
        style=discord.ButtonStyle.secondary
    )
    async def button_callback_2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NoteTakeModal(self, title="Miscellaneous Note"))


class DeleteRanksModal(discord.ui.Modal):
    def __init__(self, row_list, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.row_list = row_list
        self.add_item(discord.ui.TextInput(label="Enter # index of record(s) to delete",
                                           placeholder="Number for single deletion, or #-# for range", max_length=50))

    async def on_submit(self, interaction: discord.Interaction):
        index1, index2 = re.search(r"(\d+)(-\d+)?", self.children[0].value).groups()
        if index1 and index2:
            server_comm_ch = interaction.guild.get_channel_or_thread(SERVER_COMM_CH)
            if not server_comm_ch:
                await interaction.response.send_message("Error: SERVER_COMM_CH not found", ephemeral=True)
                return
            i1, i2 = int(index1), int(index2[1:])
            if i1 >= i2 or i2 >= len(self.row_list):
                await interaction.response.send_message("Invalid range provided", ephemeral=True)
                return
            row_range = self.row_list[i1:i2 + 1]
            if interaction.guild.get_role(MOD_ROLE_ID) not in interaction.user.roles:
                for row in row_range:
                    if datetime.now(timezone.utc) - datetime.fromtimestamp(row[0], timezone.utc) > timedelta(hours=24):
                        await interaction.response.send_message(
                            "Need Mod role to delete any entries older than 24 hours", ephemeral=True)
                        return
            for row in row_range:
                cur.execute(
                    "SELECT user_id FROM ranks_added WHERE time_added = ?",
                    (row[0],)
                )
                user_id = cur.fetchone()[0]
                await delete_rank(interaction.guild, row[0], user_id, row[2], False)
            conn.commit()
            with open(deleted_ranks_path, 'r+') as d_r:
                d_r.truncate(0)
                deleted_ranks = csv.writer(d_r)
                deleted_ranks.writerow(HEADER_LINE)
                for index, row in enumerate(row_range):
                    _, name, rank, num, note = row
                    deleted_ranks.writerow([index, name, rank, num, note])
            await server_comm_ch.send(content="Deleted the following records:", file=discord.File(deleted_ranks_path))
            await interaction.response.send_message(
                f"Deleted {len(row_range)} records. Check {server_comm_ch.mention} for trace.",
                ephemeral=True)
        elif index1:
            i1 = int(index1)
            if i1 >= len(self.row_list):
                await interaction.response.send_message("Invalid index provided", ephemeral=True)
                return
            time_added, name, rank, num, note = self.row_list[i1]
            cur.execute("SELECT user_id FROM ranks_added WHERE time_added = ?", (time_added,))
            user_id = cur.fetchone()[0]
            await delete_rank(interaction.guild, time_added, user_id, rank)
            delete_msg = f"Deleted 1 user rank record.\n\n{','.join(HEADER_LINE)}\n{','.join([index1, name, rank, str(num), note])}"
            if interaction.channel_id != SERVER_COMM_CH:
                await interaction.response.send_message(delete_msg, ephemeral=True)
            await interaction.guild.get_channel_or_thread(SERVER_COMM_CH).send(delete_msg)
        else:
            await interaction.response.send_message("No index number(s) provided", ephemeral=True)


class ShowRanksView(discord.ui.View):
    def __init__(self, row_list: list):
        super().__init__()
        self.row_list = row_list

    @discord.ui.button(
        label="Delete Rows",
        style=discord.ButtonStyle.secondary
    )
    async def button_callback(self, interaction: discord.Interaction, button):
        if not interaction.user.get_role(STAFF_ROLE_ID):
            await interaction.response.send_message("Need Staff role to press this button", ephemeral=True)
            return
        await interaction.response.send_modal(DeleteRanksModal(self.row_list, title="Delete Records"))


# Commands


# Alternative to fancier options
@tree.command(description="Grants rank with accounting for time. Includes #1 ranks. Can do many members at once.")
@app_commands.checks.has_role(STAFF_ROLE_ID)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.describe(
    user_id='@mention (press space at end) or user ID of member(s) to grant rank to',
    rank='Rank to grant member(s)',
    season_num='Which number season end (mid-season = previous season)',
    note='Miscellaneous note to attach to this record'
)
@app_commands.choices(rank=RANK_CHOICES)
async def grant_rank(interaction: discord.Interaction, user_id: str, rank: app_commands.Choice[str], season_num: int,
                     note: str = ""):
    m = re.findall(r"(\d+)", user_id)
    if not m:
        await interaction.response.send_message("Must provide a number for user_id (may be as @mention)", ephemeral=True)
        return
    users = []
    err_users = []
    for u_id in m:
        if len(u_id) < 12:
            err_users.append(f"Number received as user_id `{u_id}` was under 12 digits (arbitrary sanity check). If this was actually correct, please enter the number padded with leading 0's.")
            continue
        if not bot.get_user(int(u_id)):
            err_users.append(f"No user found for user_id `{u_id}`")
            continue
        time_added = datetime.timestamp(datetime.now(timezone.utc))
        users.append((time_added, int(u_id), int(rank.value), season_num, note))

    err_str = "\n\nThe following user_ids were not processed:\n\n" + "\n".join(err_users) if err_users else ""
    if len(users) == 1:
        await add_record(interaction, *users[0])
    elif len(users) > 1:
        cur.execute(
            "SELECT season_num, end_timestamp FROM current_season_end WHERE guild_id = ?",
            (interaction.guild_id,)
        )
        current_end = cur.fetchone()
        if not current_end:
            await interaction.response.send_message("No current season end stored yet. Use slash command `/set_season_end`." + err_str, ephemeral=True)
            return
        c_num, end_ts = current_end
        await add_records(interaction, users, c_num, end_ts)
    await interaction.followup.send(f"Finished executing `/{interaction.command.name}`" + err_str, ephemeral=True)


@tree.command(description="Show current season end date and time")
async def get_season_end(interaction: discord.Interaction):
    cur.execute(
        "SELECT season_num, end_timestamp FROM current_season_end WHERE guild_id = ?",
        (interaction.guild_id,)
    )
    current_end = cur.fetchone()
    if not current_end:
        await interaction.response.send_message(f"No season end setting found for {interaction.guild.name}")
        return
    season_num, end_ts = current_end
    end_datetime = datetime.fromtimestamp(end_ts, timezone.utc)
    await interaction.response.send_message(f"Current season set to S{season_num}, end set to {datetime.strftime(end_datetime, TIME_FORMAT)} UTC")


OVERRIDE_CODE = "beamdog"  # not case-sensitive


@tree.command(description="Edit current season end date and time")
@app_commands.checks.has_any_role(MOD_ROLE_ID, BEAMDOG_ROLE_ID)
@app_commands.describe(
    season_num='Current number season whose end is coming up',
    end_date_time='Day and time (UTC) of season end in "YYYY/MM/DD hh:mm" (24hr) format',
    override_code=f'Code to insist on an unexpected season change. Value to enter: {OVERRIDE_CODE}'
)
async def set_season_end(interaction: discord.Interaction, season_num: int, end_date_time: str, override_code: Optional[str] = None):
    try:
        g_id = interaction.guild_id
        end_datetime = datetime.strptime(end_date_time, TIME_FORMAT).replace(tzinfo=timezone.utc)
        end_timestamp = datetime.timestamp(end_datetime)

        server_comm_ch = interaction.guild.get_channel_or_thread(SERVER_COMM_CH)
        if not server_comm_ch:
            await interaction.response.send_message("Error: SERVER_COMM_CH not found", ephemeral=True)
            return
        cur.execute(
            "SELECT season_num, end_timestamp FROM current_season_end WHERE guild_id = ?",
            (g_id,)
        )
        current_end = cur.fetchone()
        if current_end:
            c_num, end_ts = current_end
            if override_code and override_code.lower() != OVERRIDE_CODE.lower():
                if timedelta(seconds=0.0) < datetime.now(timezone.utc) - datetime.fromtimestamp(end_ts, timezone.utc) < timedelta(weeks=SEASON_START_WEEKS):
                    await interaction.response.send_message(
                        f"Too early to update season. Wait until grace period of {SEASON_START_WEEKS} weeks is over, or use override code.",
                        ephemeral=True)
                    return
                if not (season_num == c_num or season_num == c_num + 1):
                    await interaction.response.send_message(
                        "Season number is neither this season nor next -- typo? Use override code if intended.",
                        ephemeral=True)
                    return
                if datetime.fromtimestamp(end_timestamp, timezone.utc) - datetime.now(timezone.utc) < timedelta(
                        seconds=0.0):
                    await interaction.response.send_message(
                        "End datetime provided is in the past -- typo? Use override code if intended.",
                        ephemeral=True)
                    return

        cur.execute(
            "INSERT OR REPLACE INTO current_season_end (guild_id, season_num, end_timestamp) VALUES (?, ?, ?)",
            (g_id, season_num, end_timestamp)
        )
        conn.commit()
        if not auto_update_season.is_running():
            auto_update_season.start()
        await server_comm_ch.send(
            f"Current season set to S{season_num}, end set to {datetime.strftime(end_datetime, TIME_FORMAT)} UTC")
        await interaction.response.send_message(f"Successfully set season end. See {server_comm_ch.mention}", ephemeral=True)

    except ValueError:
        await interaction.response.send_message("Invalid datetime provided, please check format", ephemeral=True)


def flip_season(end_ts):
    c_dt = datetime.fromtimestamp(end_ts, timezone.utc)
    if c_dt.day > 28:
        raise ValueError("Day is set higher than 28, which will fail for February.")
    new_year = c_dt.year
    new_month = c_dt.month + 6
    if new_month > 12:
        new_month %= 12
        new_year += 1
    new_dt = c_dt.replace(year=new_year, month=new_month)
    return datetime.timestamp(new_dt)


# NOTE: This is set to update the season number some SEASON_START_WEEKS weeks after the season end, because it is simpler this way for the program code, and for the rule of no ranks granted during the first SEASON_START_WEEKS weeks of a season.
@tasks.loop(minutes=30.0)
async def auto_update_season():
    cur.execute("SELECT guild_id, season_num, end_timestamp FROM current_season_end")
    current_ends = cur.fetchall()
    if not current_ends:
        return
    for current_end in current_ends:
        g_id, c_num, end_ts = current_end
        guild = bot.get_guild(g_id)
        new_num = c_num + 1
        new_ts = flip_season(end_ts)
        if datetime.now(timezone.utc) - datetime.fromtimestamp(end_ts, timezone.utc) > timedelta(weeks=SEASON_START_WEEKS):
            server_comm_ch = guild.get_channel_or_thread(SERVER_COMM_CH)
            if not server_comm_ch:
                print(f"In auto_update_season(): SERVER_COMM_CH not found for guild: {guild.name}")
                return
            with open(deleted_ranks_path, 'r+') as d_r:
                d_r.truncate(0)
                deleted_ranks = csv.writer(d_r)
                deleted_ranks.writerow(HEADER_LINE)

                cur.execute("SELECT time_added, user_id, rank, season_num, note FROM ranks_added")
                row_list = sorted(cur.fetchall(), key=lambda tup: (expiry(tup[2], tup[3]), tup[0]))
                for index, row in enumerate(row_list):
                    time_added, user_id, rank, num, note = row
                    if num < expiry_back(RANK_ID_DICT[rank], new_num):
                        deleted_ranks.writerow([index, guild.get_member(user_id).name, rank, num, note])
                        await delete_rank(guild, time_added, user_id, rank, False)
                conn.commit()
            try:
                cur.execute(
                    "REPLACE INTO current_season_end (guild_id, season_num, end_timestamp) VALUES (?, ?, ?)",
                    (g_id, new_num, new_ts)
                )
                conn.commit()
                await server_comm_ch.send(f"Auto-updated current season to S{new_num}, end set to {datetime.strftime(datetime.fromtimestamp(new_ts, timezone.utc), TIME_FORMAT)} UTC\nDeleted ranks:", file=discord.File(deleted_ranks_path))
            except ValueError as e:
                await server_comm_ch.send(f"{guild.get_role(MOD_ROLE_ID).mention} Error updating season end: ValueError: {e}\n\nUse slash command `/set_season_end` to manually update it.")
                auto_update_season.stop()


@auto_update_season.before_loop
async def before_auto_update_season():
    await bot.wait_until_ready()


@tree.command(description="Lists users in the ranks database, oldest first. Also provides button to Delete ranks")
@app_commands.checks.has_role(STAFF_ROLE_ID)
@app_commands.checks.bot_has_permissions(send_messages=True)
async def show_user_ranks(interaction: discord.Interaction):
    with open(show_ranks_path, 'r+') as s_r:
        s_r.truncate(0)
        show_ranks = csv.writer(s_r)
        show_ranks.writerow(HEADER_LINE)
        cur.execute("SELECT time_added, user_id, rank, season_num, note FROM ranks_added")
        row_list = []
        for row in cur.fetchall():
            time_added, user_id, rank, num, note = row
            user = bot.get_user(user_id)
            username = user.name if user else "(deleted_user)"
            row_list.append([time_added, username, rank, num, note])

        row_list.sort(key=lambda ls: (expiry(ls[2], ls[3]), ls[0]))
        for index, row in enumerate(row_list):
            _, name, rank, num, note = row
            show_ranks.writerow([index, name, rank, num, note])

    await interaction.response.send_message(f"Ranks stored in database, sorted by earliest expiration first. Expiry = Season # + {MEDAL_TIME} if normal, + {TOP_TIME} if Top 10 type. Note: mid-season ranks counted as previous season.",
                                            file=discord.File(show_ranks_path), view=ShowRanksView(row_list))


@tree.command(description="Bulk grant ranks via csv-formatted txt file")
@app_commands.checks.has_role(STAFF_ROLE_ID)
@app_commands.describe(
    file="/show_user_ranks format OR username, rank, season num, note (optional)"
)
async def upload_user_ranks(interaction: discord.Interaction, file: discord.Attachment):
    await interaction.response.defer()
    server_comm_ch = interaction.guild.get_channel_or_thread(SERVER_COMM_CH)
    cur.execute(
        "SELECT season_num, end_timestamp FROM current_season_end WHERE guild_id = ?",
        (interaction.guild_id,)
    )
    current_end = cur.fetchone()
    if not current_end:
        await interaction.followup.send("No current season end stored yet. Use slash command `/set_season_end`.", ephemeral=True)
        return
    c_num, end_ts = current_end
    time_added = datetime.now(timezone.utc).timestamp()
    await file.save(upload_ranks_path)
    with open(upload_ranks_path, 'r') as u_r:
        ranks_upload = csv.reader(u_r)
        ranks = []
        official_format = 0
        illformed_ranks = []
        bad_name_count = 0
        for i, row in enumerate(ranks_upload):
            if i == 0 and row == HEADER_LINE:
                official_format = 1
                continue
            if official_format and len(row) != 5:
                illformed_ranks.append(row)
                continue
            if len(row) < 3 or not official_format and len(row) > 4:
                illformed_ranks.append(row)
                continue
            name = row[0+official_format].strip()
            rank = row[1+official_format].strip()
            season_num = row[2+official_format].strip()
            note = row[3+official_format].strip() if len(row) == 4+official_format else ""

            if rank not in RANK_ID_DICT.keys() or not season_num.isdigit():
                illformed_ranks.append(row)
                continue
            match_members = await interaction.guild.query_members(name, limit=100)
            if len(match_members) == 100:
                lim_msg = f"WARNING: hit query limit of 100 for name: {name} (treated as a prefix)\nDesired user could have been left out"
                if server_comm_ch:
                    await server_comm_ch.send(lim_msg)
                else:
                    await interaction.followup.send(lim_msg, ephemeral=True)
            match_members = [mem for mem in match_members if (mem.nick == name or mem.global_name == name or mem.name == name) and not mem.bot]  # query must match whole name, not only prefix; member cannot be a bot
            if len(match_members) > 1:
                dup_msg = f"Note: possible nickname duplicates found for usernames: {' '.join([m.name+' ('+m.display_name+'),' for m in match_members])}"
                if server_comm_ch:
                    await server_comm_ch.send(dup_msg)
                else:
                    await interaction.followup.send(dup_msg, ephemeral=True)
            user = None
            dup_nick = False
            for mem in match_members:
                if mem.name == name:
                    user = mem
                    break  # assumes mem.name is unique, since it should be username. This is why bots not allowed, because they can have discriminators still
                if mem.display_name == name:
                    if user:
                        user = None  # if nickname is unique, can be used, but if duplicated, cannot
                        dup_nick = True
                    elif not dup_nick:
                        user = mem
            if not user:
                bad_name_count += 1
                illformed_ranks.append(row)
                continue

            ranks.append((time_added, user.id, RANK_ID_DICT[rank], int(season_num), note))

    await add_records(interaction, ranks, c_num, end_ts)

    if illformed_ranks:
        with open(illformed_ranks_path, 'r+') as i_r:
            i_r.truncate(0)
            i_r_writer = csv.writer(i_r)
            for row in illformed_ranks:
                i_r_writer.writerow(row)
        bad_names_msg = f"\nPrefer using usernames over nicknames. Names are case-sensitive.\n{bad_name_count} names provided were found not to be (non-bot) usernames or unique nicknames."
        illform_msg = (f"\n\nSome rows in the file were of unexpected format. Were rank titles and season numbers correct?\nRank titles accepted: {', '.join(RANK_ID_DICT.keys())}"
                       f"\nTip: use double quotes \" if comma is in an entry, and double double quotes \"\" if \" symbol is needed."
                       f"\n{bad_names_msg}\nBelow are the ranks that were passed over altogether due to being ill-formed:")
        if server_comm_ch:
            await server_comm_ch.send(illform_msg, file=discord.File(illformed_ranks_path))
        else:
            await interaction.followup.send(illform_msg, file=discord.File(illformed_ranks_path))


async def rank_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.channel_id != REQUEST_RANK_CH:
        return
    if payload.member.get_role(STAFF_ROLE_ID):
        guild = bot.get_guild(payload.guild_id)
        author = guild.get_member(payload.message_author_id)
        msg = await guild.get_channel(payload.channel_id).fetch_message(payload.message_id)
        if not author:
            await guild.get_channel(SERVER_COMM_CH).send(f"A Staff member reacted to {msg.jump_url}\nError: user not in server.")
            return
        rank_react_ls = [react for react in msg.reactions if isinstance(react.emoji, discord.Emoji) and react.emoji.id == payload.emoji.id]
        if rank_react_ls:
            rank_react = rank_react_ls[0]
            rank_name = REACTION_DICT[payload.emoji.id]
            rank_button = GrantRankView(author, RANK_ID_DICT[rank_name], msg.id)
            staff_msg = f"{payload.member.mention} Select a season end for granting **{rank_name}** rank to user: {author.display_name}"
            if pressed_ranks.get(msg.id) == rank_name:
                staff_msg = f"{msg.jump_url} A Staff member has already pressed the button to grant **{rank_name}** rank to user: {author.display_name}\nIf something's not right, use slash command `/show_user_ranks` to delete the record, and `/grant_rank` to replace it."
                rank_button = None
            elif [user async for user in rank_react.users() if guild.get_member(user.id) and user.get_role(STAFF_ROLE_ID) and user.id != payload.member.id]:
                staff_msg = f"{payload.member.mention} A Staff member has already reacted with **{rank_name}** for user: {author.display_name}\nHowever, they might not have pressed the button to grant the rank yet. (Or maybe they did, but the bot was later reset.)"
            await guild.get_channel(SERVER_COMM_CH).send(content=staff_msg, view=rank_button)


async def clean_member_roles(member: discord.Member):
    if not member.guild.get_member(member.id):  # confirm member has not already left server
        return
    cur.execute(
        "SELECT time_added, rank FROM ranks_added WHERE user_id = ?",
        (member.id,)
    )
    entries = cur.fetchall()
    roles_to_rm = []
    for role in member.roles:
        if role.id in RANK_DICT.keys():
            rank_entries = [t for t, r in entries if r == RANK_DICT[role.id]]
            if not rank_entries:  # confirm no basis for role in db
                roles_to_rm.append(role)
    await member.remove_roles(*roles_to_rm)
