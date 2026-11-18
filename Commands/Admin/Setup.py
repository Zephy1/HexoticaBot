import MainBot

import discord

from Utils.Translation import Say, Text
from Database import PersistentAppData
from Commands.Admin import adminGroup
from Utils import Variables
from Utils import Logger
from Utils import Utils
from Utils import Views

class SetupView(Views.Panel):
    def __init__(self, guildID: Utils.GuildID):
        super().__init__()
        self.guildID = guildID
        config = Utils.GuildConfig(guildID)
        self.chosen: dict[str, int | None] = {}

        self.add_item(discord.ui.TextDisplay(Say(Text.ADMIN_SETUP_INTRO)))
        container = discord.ui.Container(accent_color=Variables.defaultDiscordColor)
        container.add_item(discord.ui.TextDisplay(Say(Text.ADMIN_SETUP_LEGEND)))

        def channelSelect(key: str, placeholder: str, required: bool) -> discord.ui.ChannelSelect:
            select = discord.ui.ChannelSelect(
                channel_types=[discord.ChannelType.text, discord.ChannelType.news],
                placeholder=placeholder,
                min_values=1 if required else 0,
                max_values=1,
                default_values=[discord.Object(id=config[key])] if config.get(key) else [],
            )

            @Views.ButtonCallback
            async def chosen(interaction: discord.Interaction):
                self.chosen[key] = select.values[0].id if select.values else None

            select.callback = chosen
            return select

        for key, placeholder, required in (
            ("dropChannelID", Say(Text.ADMIN_SETUP_DROP_PLACEHOLDER), True),
            ("specialChannelID", Say(Text.ADMIN_SETUP_SPECIAL_PLACEHOLDER), False),
        ):
            container.add_item(discord.ui.ActionRow(channelSelect(key, placeholder, required)))

        container.add_item(discord.ui.ActionRow(Views.Button(Say(Text.ADMIN_SETUP_SAVE), self.save, discord.ButtonStyle.success)))
        self.add_item(container)

    async def save(self, interaction: discord.Interaction):
        config = dict(Utils.GuildConfig(self.guildID))
        for key, value in self.chosen.items():
            if value is None:
                config.pop(key, None)
            else:
                config[key] = value
        if not config.get("dropChannelID"):
            await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.ADMIN_SETUP_NEED_DROP), ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        await PersistentAppData.UpdateData(f"guildConfig.{self.guildID}", config, showMessage=False)

        special = Say(Text.ADMIN_SETUP_CHANNEL, channelID=config['specialChannelID']) if config.get("specialChannelID") else Say(Text.ADMIN_SETUP_NOT_SET)
        view = discord.ui.LayoutView(timeout=None)
        view.add_item(discord.ui.TextDisplay(Say(
            Text.ADMIN_SETUP_SAVED,
            dropChannel=Say(Text.ADMIN_SETUP_CHANNEL, channelID=config['dropChannelID']),
            specialChannel=special,
        )))
        await interaction.edit_original_response(view=view)

@MainBot.AppCommandWithAliases(
    adminGroup,
    name="setup",
    description=Say(Text.ADMIN_SETUP_DESCRIPTION),
    permission="manage",
)
async def Command_AdminSetup(interaction: discord.Interaction):
    guildID = await Utils.RequireGuild(interaction.guild_id, interaction)
    await interaction.response.send_message(view=SetupView(guildID), ephemeral=True)
