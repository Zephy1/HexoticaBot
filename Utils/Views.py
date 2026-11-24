import MainBot

import functools
import discord
import asyncio

from Utils.Translation import Say, Text
from Utils import Logger
from . import Utils

async def Retry(call):
    for attempt in range(3):
        try:
            return await call()
        except OSError:
            if attempt == 2:
                raise
            await asyncio.sleep(1 + attempt)

def ButtonCallback(func=None, *, thinking=False):
    if func is None:
        return functools.partial(ButtonCallback, thinking=thinking)

    @functools.wraps(func)
    async def guarded(*args, **kwargs):
        interaction = MainBot.FindInteraction(args, kwargs)
        try:
            if interaction is None or await MainBot.IsUserBlacklisted(interaction, logUsage=False):
                return None
            await interaction.response.defer(thinking=thinking, ephemeral=thinking)
            return await func(*args, **kwargs)
        except Utils.CommandAbort:
            return None
        except Exception as e:
            await Logger.LogInteractionError(interaction=interaction, message=f"Unhandled exception in button: {e}")
    return guarded

panelTimeoutSeconds = 840

def Button(label: str, callback=None, style: discord.ButtonStyle = discord.ButtonStyle.secondary, disabled: bool = False) -> discord.ui.Button:
    button = discord.ui.Button(label=label, style=style, disabled=disabled)
    if callback is not None:
        button.callback = callback
    return button

def Dropdown(placeholder: str, options: list[discord.SelectOption], callback, **kwargs) -> discord.ui.Select:
    select = discord.ui.Select(placeholder=placeholder, options=options, **kwargs)
    select.callback = callback
    return select

async def OpenModal(interaction: discord.Interaction, modal: discord.ui.Modal) -> None:
    if not await MainBot.IsUserBlacklisted(interaction, logUsage=False):
        await interaction.response.send_modal(modal)

class Panel(discord.ui.LayoutView):
    def __init__(self, ownerID: Utils.MemberID | None = None, expiredText: Text | None = None):
        super().__init__(timeout=panelTimeoutSeconds)
        self.ownerID = ownerID
        self.expiredText = expiredText
        self.lastInteraction: discord.Interaction | None = None

    def Touch(self, interaction: discord.Interaction) -> None:
        self.lastInteraction = interaction

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.ownerID is None or interaction.user.id == self.ownerID:
            return True
        await interaction.response.send_message(Say(Text.NOT_ALLOWED), ephemeral=True)
        return False

    async def on_timeout(self) -> None:
        if self.expiredText is None or self.lastInteraction is None:
            return
        expired = discord.ui.LayoutView(timeout=None)
        expired.add_item(discord.ui.TextDisplay(Say(self.expiredText)))
        try:
            await self.lastInteraction.edit_original_response(view=expired, attachments=[])
        except discord.HTTPException:
            pass
