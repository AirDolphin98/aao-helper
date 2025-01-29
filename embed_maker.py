
from params import *
from discord import app_commands
import datetime as datetime_module  # stupid aspect of datetime being also an object
from datetime import datetime, timezone, timedelta


class CreateEmbedModal(discord.ui.Modal):
    def __init__(self, vals=(None,) * 5, message=None, *args, **kwargs) -> None:
        kwargs['title'] = "Enter values for embed fields"
        super().__init__(*args, **kwargs)
        self.vals = vals
        self.message = message  # only valid when editing
        self.add_item(discord.ui.TextInput(label='Title header of embed (max 256 char)', max_length=256, default=vals[0], row=0, required=False))
        self.add_item(discord.ui.TextInput(label='Body text of embed (max 4000 char)', max_length=4000, default=vals[1], row=1, style=discord.TextStyle.paragraph, required=True))
        self.add_item(discord.ui.TextInput(label='Footer text of embed (max 2048 char)', max_length=1500, default=vals[2], row=2, style=discord.TextStyle.paragraph, required=False))  # Low limit to not exceed 6000 combined limit
        self.add_item(discord.ui.TextInput(label='Color of embed siding (hex code)', max_length=7, default=vals[3], row=3, required=False))
        self.add_item(discord.ui.TextInput(label='Large image below body (url to image)', default=vals[4], row=4, required=False))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

        async def hex_str_to_int(hex_str: str):  # Helper function for color parameter
            if not hex_str:
                return 0
            hex_str = hex_str.strip().strip("#")
            for c in hex_str:
                if c not in "0123456789abcdefABCDEF":  # characters that are valid in hexadecimal
                    await interaction.followup.send("Color must be provided as valid hex code.", ephemeral=True)
                    return 0
            return int(hex_str, 16)

        title = self.children[0].value
        description = self.children[1].value
        footer = self.children[2].value
        color = await hex_str_to_int(self.children[3].value)
        image = self.children[4].value
        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_footer(text=footer)
        embed.set_image(url=image)
        try:
            if self.message:
                await self.message.edit(embed=embed)
                msg = self.message
            else:
                msg = await interaction.channel.send(embed=embed)
            server_comm_ch = interaction.guild.get_channel_or_thread(SERVER_COMM_CH)
            if server_comm_ch:
                await server_comm_ch.send(f"{interaction.user.name} {'edited' if self.message else 'created'} an embed: {msg.jump_url}")
            else:
                await interaction.followup.send("Server commands channel for logging purposes not found", ephemeral=True)
        except discord.errors.HTTPException as e:
            print("ERROR in embed_maker.py CreateEmbedModal on_submit\n", e)
            await interaction.followup.send("HTTP error: check image url", ephemeral=True)


@tree.command(description="Create and send embed")
@app_commands.checks.has_any_role(STAFF_ROLE_ID, BEAMDOG_ROLE_ID)
@app_commands.checks.bot_has_permissions(send_messages=True)
async def create_embed(interaction: discord.Interaction):
    await interaction.response.send_modal(CreateEmbedModal())


@app_commands.checks.has_any_role(STAFF_ROLE_ID, BEAMDOG_ROLE_ID)
@app_commands.checks.bot_has_permissions(send_messages=True)
@app_commands.context_menu(name="Edit embed")
async def edit_embed(interaction: discord.Interaction, message: discord.Message):
    if message.author != bot.user:
        await interaction.response.send_message("Cannot edit message not sent by the same bot.", ephemeral=True)
        return
    if len(message.embeds) > 1:
        await interaction.response.send_message("Not sure how the bot sent a message with multiple embeds, but this can't edit it.", ephemeral=True)
        return
    elif len(message.embeds) < 1:
        await interaction.response.send_message("Message does not contain an embed.", ephemeral=True)
        return
    else:
        embed = message.embeds[0]
        title = embed.title if embed.title else None
        description = embed.description if embed.description else None
        footer = embed.footer.text if embed.footer else None
        color = f'{embed.color.value:06x}' if embed.color else None
        image = embed.image.url if embed.image else None
        await interaction.response.send_modal(CreateEmbedModal(vals=(title, description, footer, color, image), message=message))
        

tree.add_command(edit_embed)


