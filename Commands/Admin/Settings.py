import MainBot

import discord

from discord import app_commands

from Utils.Translation import Say, Text
from Commands.Admin import adminGroup
from Utils import Variables
from Utils import Logger
from Utils import Utils
from Utils import Views

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

class SettingModal(discord.ui.Modal):
    def __init__(self, panel: "SettingsPanel", name: str):
        definition = Variables.SETTINGS[name]
        current = Utils.GetSettingValueFromGuild(panel.guildID, name)
        super().__init__(title=definition.label[:45])
        self.panel, self.name, self.definition = panel, name, definition
        self.field = discord.ui.TextInput(default=str(current) if definition.isInt else f"{current:g}", required=False, max_length=20)
        self.add_item(discord.ui.Label(
            text=definition.label[:45],
            description=Say(
                Text.ADMIN_SETTINGS_MODAL_HINT,
                minimum=Utils.FormatSetting(name, definition.minimum),
                maximum=Utils.FormatSetting(name, definition.maximum),
                default=Utils.FormatSetting(name, definition.default),
            )[:100],
            component=self.field,
        ))

    @Views.ButtonCallback
    async def on_submit(self, interaction: discord.Interaction):
        raw = self.field.value.replace(",", "").replace("_", "").strip()
        try:
            value = (int(raw) if self.definition.isInt else float(raw)) if raw else None
        except ValueError:
            await self.panel.Show(interaction, Say(Text.ADMIN_SETTINGS_NOT_INTEGER if self.definition.isInt else Text.ADMIN_SETTINGS_NOT_NUMBER, value=raw))
            return
        if value == self.definition.default:
            value = None
        try:
            await Utils.SetSetting(self.panel.guildID, self.name, value)
        except ValueError as e:
            await self.panel.Show(interaction, str(e))
            return
        current = Utils.FormatSetting(self.name, Utils.GetSettingValueFromGuild(self.panel.guildID, self.name))
        await self.panel.Show(interaction, Say(Text.ADMIN_SETTINGS_RESET if value is None else Text.ADMIN_SETTINGS_SET, setting=self.definition.label, value=current))

class SettingsPanel(Views.Panel):
    def __init__(self, guildID: Utils.GuildID):
        super().__init__()
        self.guildID = guildID
        self.status = ""
        self.confirming = False
        self.Build()

    def Build(self) -> None:
        self.clear_items()
        lines, options = [], []
        for name, definition in list(Variables.SETTINGS.items())[:25]:
            current = Utils.FormatSetting(name, Utils.GetSettingValueFromGuild(self.guildID, name))
            default = Utils.FormatSetting(name, definition.default)
            lines.append(Say(Text.ADMIN_SETTINGS_PANEL_LINE, label=definition.label, current=current, note=Say(Text.ADMIN_SETTINGS_PANEL_DEFAULT, default=default) if current != default else ""))
            options.append(discord.SelectOption(label=definition.label, value=str(name), description=definition.description[:100]))
        self.select = Views.Dropdown(Say(Text.ADMIN_SETTINGS_PANEL_PLACEHOLDER), options, self.Pick)
        reset = Views.Button(
            Say(Text.ADMIN_SETTINGS_RESET_ALL_CONFIRM if self.confirming else Text.ADMIN_SETTINGS_RESET_ALL_BUTTON),
            self.ResetAll,
            discord.ButtonStyle.danger if self.confirming else discord.ButtonStyle.secondary,
        )
        items = [discord.ui.TextDisplay("\n".join([Say(Text.ADMIN_SETTINGS_PANEL_TITLE), *lines]))]
        if self.status:
            items.append(discord.ui.TextDisplay(self.status))
        self.add_item(discord.ui.Container(
            *items,
            discord.ui.Separator(),
            discord.ui.ActionRow(self.select),
            discord.ui.ActionRow(reset),
            accent_color=Variables.defaultDiscordColor,
        ))

    async def Show(self, interaction: discord.Interaction, status: str = "", confirming: bool = False) -> None:
        self.status, self.confirming = status, confirming
        self.Build()
        if interaction.response.is_done():
            await interaction.edit_original_response(view=self)
        else:
            await interaction.response.edit_message(view=self)

    async def Pick(self, interaction: discord.Interaction):
        await Views.OpenModal(interaction, SettingModal(self, self.select.values[0]))

    @Views.ButtonCallback
    async def ResetAll(self, interaction: discord.Interaction):
        if not self.confirming:
            await self.Show(interaction, self.status, confirming=True)
            return
        for name in list(Utils.GuildConfig(self.guildID).get("settings", {})):
            if name in Variables.SETTINGS:
                await Utils.SetSetting(self.guildID, name, None)
        await self.Show(interaction, Say(Text.ADMIN_SETTINGS_RESET_ALL_DONE))

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
    action: app_commands.Choice[str] | None = None,
    name: str | None = None,
    value: str | None = None,
):
    guildID = await Utils.RequireGuild(interaction.guild_id, interaction)
    if action is None:
        return await interaction.response.send_message(view=SettingsPanel(guildID), ephemeral=True)
    if action.value == "list":
        return await HandleSettingsList(interaction, guildID)

    setting = name if name in Variables.SETTINGS else None
    if setting is None:
        await Logger.SendInteractionMessage(interaction=interaction, message=Say(Text.ADMIN_SETTINGS_UNKNOWN), ephemeral=True)
        return

    if action.value == "reset":
        return await HandleSettingsReset(interaction, guildID, setting)
    return await HandleSettingsSet(interaction, guildID, setting, value)
