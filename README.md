# AAO Helper

Bot of utility functions for the Axis & Allies 1942 Online community Discord server. Originally designed by Andrew, I (AirDolphin98) have rebuilt it with various new features. 

Donate to the authors:

https://ko-fi.com/aallgood

https://ko-fi.com/airdolphin98

## Overview

So far, these are the main functions of the bot:

* Roll for sides (assign players to either Axis or Allies)

* Create and edit embed messages

* Correct invisibility of newly created channels

* Conveniently give showcase roles

* Move showcase channels and galleries between archive and main categories

* After inactivity, automatically unhide threads or archive forum posts

* System that lets people give themselves exhibition match role

* System for granting leaderboard rank badges, storing them in a database, and updating with the ranked seasons. This is the most sophisticated functionality.

* Commands that streamline the posting of typical Hall of Fame embeds and auto-manage the awarded roles to some extent

The bot automates much of these processes and allows people who don't have perms such as manage channels/threads/roles to perform these actions.

## Setup

I have set this up on a Pebblehost server. It's cheap and decent for bot hosting (as of 2025). You can link it to a GitHub repo and have it update the code upon every server restart. Note: the actual repo linked to my host currently is combined with other bots and named /Discord-Bots. I copy-paste files between that and the standalone /aao-helper repo.

The main file which you run the program with is `aao_helper.py`

You also need to do the following:

* If not already, invite the bot to the Discord server through the Discord developer portal, making sure it has a lot of permissions (or admin perms, but that's risky).

* Hoist the bot's Discord role above most other roles so it is allowed to operate on them.

* Create a file simply called `.env` in the bot hosting server (e.g. Pebblehost) on the same level as `aao_helper.py`. Copy the Discord bot token into this file right after this text, which is all you need: `DISCORD_BOT_TOKEN=`

* Start the bot in the host server. In Pebblehost you'll have a loader script you can run `aao_helper.py` with whenever the server starts.

* When the bot first enters a Discord server or when its commands are updated in terms of the interface (command names, descriptions, and parameters, not function code), you must type `/sync` in any Discord channel as someone with Manage Server perms to register the commands.

Calling the main file with first command line argument `test` allows you to test the bot with different channels and roles etc. The current debug values are for the Discord server A&AO Test Server, as well as the bot A&AO testbot whose token you put after `DISCORD_TESTBOT_TOKEN=` in a (local) `.env` file.

## How to use

The commands for roll sides, roll dice, and create/edit embed or announcement should be fairly self-explanatory.

1. `/sides` Anyone can use.

2. `/dice` Anyone can use.

3. `/create_embed` Staff or Beamdog can use.

4. `Message right-click -> Apps -> Edit embed` (context menu command) Staff or Beamdog can use.

5. `/announcement` Only Admin can use. Only sends to #announcements channel.

6. `Message right-click -> Apps -> Edit Message` (context menu command) Only Admin can use. Can edit non-embed in any channel except #server-commands.

Note: to make user or channel mentions function properly when entered through a modal field, they must be in angle bracket format, e.g. <@1234567890> or <#1234567890>. @everyone and @here are exceptions and work as written.

7. `list_non_commanders_mem_pings` Must have Manage Server permission to use. Can only use in #server-commands. Lists the pings of members (not Staff or bot) who for one reason or another do not have the Commanders role, which is supposed to be universal to non-Staff non-bot.

8. `push_channels_as_default` Must have Manage Server permission to use. Basically always call this when creating new channels. Discord's Community Onboarding system has extremely unfortunate behavior for new channels in categories created after Onboarding was switched on, or without category. Anyone who doesn't have Show All Channels ticked (or who fiddles with Browse Channels which will untick Show All Channels) won't be able to see such new channels except via a random "suggested" tab, or by picking them in Browse Channels. This command automatically performs a clever technique to force everyone to see the channels: create a temp role, private the channels to be only that role, give everyone the role (which may take a while), unprivate the channels and delete the role. Carefully read the messages sent by this command for more info.

### Showcase

9. `/showcase_give_role` Invoke this in a showcase channel to be prompted to enter user pings, which assigns them the showcase role for that channel.

10. `/showcase_clear_role` Invoke this in a showcase channel to fully deassign its showcase role. Provides the option to ping the players from the gallery with a friendly message.

11. `/toggle_showcase` Invoke this in a showcase channel to automatically move it either from its usual category to the CACHE category, or vice versa. Its gallery channel will be moved along with it. The channel order may need to be adjusted for presentation, but Discord does a decent job of preserving the order sometimes.

Note: Finals channels are often intended to have gallery-1 channels as their gallery, but only showcase-1 channels are linked to them. Therefore, you're not supposed to archive a showcase-1 channel when a finals channel is on display. There's no issue with doing that manually, however.

### Auto manage threads

12. `/auto_unarchive` Invoke this in a thread to automatically unhide it when it would normally disappear from the channel list after the auto archive duration. Invoke in a channel to do this for all threads in that channel. Closed/locked threads will not be affected; auto archive does not register as archiving, it somehow only changes visibility. Note: takes `15` minutes to take effect so as not to clog up the Audit Log from frequent bot restarts.

13. `/auto_close_forum_posts` Invoke this with a forum ID to have it automatically archive forum posts that have not had recent messages. Default cutoff is `14` days ago. Can also auto-lock if desired.

14. `/list_auto_managed_channels` Invoke this to get a list of channels, threads, and forums currently being auto-managed with the above commands.

### Exhibition match

15. `/init_exhibitions` Invoke this anywhere to send embeds to all the exhibition-match channels with a permanent button that prompts the user to enter user pings, which assigns them Exhibition Match role and reserves the channel for them until the match is ended.

16. `/end_exhibitions` A player in an exhibition match invokes this in an ongoing match channel to end the match in that channel. 

## Ranked badge system

This section is to help implement the leaderboard ranking role granting system in the A&AO community server. The basic idea is that members may request a vanity role based on their highest recent leaderboard rank. Rather than let the ranks be valid indefinitely, it was decided that they should expire on a timetable as follows:

* Top 10 rank and #1 ranks are only granted for season end and expire 3 seasons + 5 weeks later. Once expired, Legacy Top 10 and/or Legacy #1 are granted.

* Medallion ranks (Platinum - Wood) are granted for any time except the 5 weeks right after season start. If the rank was attained at season end or up to 5 weeks before, it expires 2 seasons + 5 weeks later. If the rank was attained in the middle of a season, i.e. between 5 weeks after start and 5 weeks before end, it expires remainder of season + 1 season + 5 weeks later, equivalent to if it were for the previous season end.

This section implements a SQLite database that records roles granted and removes role when record is deleted. There is also a loop that auto-updates the season number, which is first manually set, 5 weeks after season end, and automatically removes roles and deletes records that have expired.

Ranks not granted through the system, e.g. by Discord built-in role management, will not be recorded in the database, so be sure to use the commands below to grant rank. Users who leave the server may still have records which will expire as normal; assuming there is an auto-role-restore upon server re-join, a clean-up check is implemented where such auto-role ranks are removed if no record is found.

Unless otherwise specified, Staff and only Staff role may use the following commands:

* `On rank react` In the request-rank channel, members post a screenshot of their profile with the rank for the season they want recorded. By reacting to this member's message with a medallion emoji, a select menu will pop up in the server-commands channel asking for which season the role should be granted.

17. `/grant_rank` Invoke this anywhere to give one or more users a given rank for a given season. @mention or raw User ID specifies the user. Tip: if the member is not visible in the channel, you can get the proper @mention by pressing *space* after typing out @ and the username in full. To find the User ID, you can check this Discord support article: https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID

18. `/get_season_end` Any member can invoke this to check the current season end. 

19. `/set_season_end` Mod or Beamdog role can invoke this to manually set the current season end. There are various checks which can be bypassed with the override option. 

20. `/show_user_ranks` Invoke this to generate a txt file of all the contents of the database in csv format, i.e. all ranks recorded. This view provides a delete button which allows you to manually delete a range of rows in the txt file. As a precaution, only Mod may delete rows older than 24 hours. Deleted rows will be printed back in a txt file in csv format. 

21. `/upload_user_ranks` Invoke this to upload a txt file in csv format of ranks to insert into the database. Useful for re-inserting deleted roles or inserting a lot of users. Names are case-sensitive. Tip: csv format allows you to use commas `,` inside an entry if you surround it with double-quotes `"`, and to use a double-quote if you add an extra double-quote like `""`.

## Hall of fame embeds

22. `hall_of_fame` This command group allows Staff to more easily post in hall-of-fame channel. These commands grant Hall of Fame role to all featured players. 

    a. `top_10` Posts Top 10 Platinum embed for season end. If not for a just-ended season, it does not auto-grant ranks aside from Hall of Fame. For a just-ended season, grants and records Top 10 and #1 ranks too.

    b. `tournament` Posts Tournament embed for Solos, Duos, or Blitz winners and finalists. The primary Champion roles are not managed by this, but the underlying Champions role is. Blitz tournament follows a dethrone policy as of 2024, so remember to manually remove the previous Blitz Champion's role, and the underlying Champion role if not champion in another tournament.

    c. `league` Posts League Generals embed. Provides the option to cycle the Generals and Supreme Commander roles to the featured players, removing from other players. Choose this if for the current started League season.
