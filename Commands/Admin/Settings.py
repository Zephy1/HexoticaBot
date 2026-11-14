import MainBot

import discord

from discord import app_commands

from Utils.Translation import Say, Text
from Commands.Admin import adminGroup
from Utils import Variables
from Utils import Logger
from Utils import Utils

settingsActionChoices = [
    app_commands.Choice(name=Say(Text.ADMIN_SETTINGS_ACTION_LIST), value="list"),
    app_commands.Choice(name=Say(Text.ADMIN_SETTINGS_ACTION_SET), value="set"),
    app_commands.Choice(name=Say(Text.ADMIN_SETTINGS_ACTION_RESET), value="reset"),
]

async def HandleSettingsList(interaction: discord.Interaction, guildID: Utils.GuildID):
    lines = []
    for settingName, definition in Variables.SETTINGS.items():
        current = Utils.GetSettingValueFromGuild(guildID, settingName)
        lines.append(Say(
            Text.ADMIN_SETTINGS_LINE,
            label=definition.label,
            name=settingName,
            current=Utils.FormatSetting(settingName, current),
            default=Utils.FormatSetting(settingName, definition.default),
            minimum=Utils.FormatSetting(settingName, definition.minimum),
            maximum=Utils.FormatSetting(settingName, definition.maximum),
        ))
    embed = MainBot.CreateDefaultEmbed(
        createdAt=interaction.created_at,
        title=Say(Text.ADMIN_SETTINGS_TITLE),
        description="\n".join(lines)[:4000],
    )
    await Logger.SendInteractionMessage(interaction=interaction, embed=embed)

async def HandleSettingsReset(interaction: discord.Interaction, guildID: Utils.GuildID, settingName: Utils.SettingName):
    if settingName not in Utils.GuildConfig(guildID).get("settings", {}):
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.ADMIN_SETTINGS_NO_OVERRIDE, setting=settingName), ephemeral=True)
        return

    await Utils.SetSetting(guildID, settingName, None)
    value = Utils.GetSettingValueFromGuild(guildID, settingName)
    await Logger.SendInteractionMessage(
        interaction=interaction,
        message=Say(Text.ADMIN_SETTINGS_RESET, setting=settingName, value=Utils.FormatSetting(settingName, value)),
        ephemeral=True,
    )

async def HandleSettingsSet(interaction: discord.Interaction, guildID: Utils.GuildID, settingName: Utils.SettingName, value: str | None):
    if value is None:
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.ADMIN_SETTINGS_VALUE_REQUIRED), ephemeral=True)
        return

    definition = Variables.SETTINGS[settingName]
    try:
        parsed = int(value) if definition.isInt else float(value)
    except ValueError:
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.ADMIN_SETTINGS_NOT_INTEGER if definition.isInt else Text.ADMIN_SETTINGS_NOT_NUMBER, value=value), ephemeral=True)
        return

    try:
        await Utils.SetSetting(guildID, settingName, parsed)
    except ValueError as e:
        await Logger.SendInteractionMessage(interaction=interaction, message=str(e), ephemeral=True)
        return

    await Logger.SendInteractionMessage(
        interaction=interaction,
        message=Say(Text.ADMIN_SETTINGS_SET, setting=settingName, value=Utils.FormatSetting(settingName, parsed)),
        ephemeral=True,
    )

@MainBot.AppCommandWithAliases(
    adminGroup,
    name="settings",
    description=Say(Text.ADMIN_SETTINGS_DESCRIPTION),
    variableDescriptions={
        "action": Say(Text.ADMIN_SETTINGS_ACTION),
        "name": Say(Text.ADMIN_SETTINGS_NAME),
        "value": Say(Text.ADMIN_SETTINGS_VALUE),
    },
    commandChoices={
        "action": settingsActionChoices,
    },
    autoComplete={
        "name": Utils.AutocompleteSettings,
    },
    permission="manage",
)
async def Command_AdminSettings(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    name: str | None = None,
    value: str | None = None,
):
    guildID = await Utils.RequireGuild(interaction.guild_id, interaction)
    if action.value == "list":
        return await HandleSettingsList(interaction, guildID)

    setting = name if name in Variables.SETTINGS else None
    if setting is None:
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.ADMIN_SETTINGS_UNKNOWN), ephemeral=True)
        return

    if action.value == "reset":
        return await HandleSettingsReset(interaction, guildID, setting)
    return await HandleSettingsSet(interaction, guildID, setting, value)
