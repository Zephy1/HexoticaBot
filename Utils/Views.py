import MainBot

import functools

from Utils import Logger
from . import Utils

def ButtonCallback(func):
    @functools.wraps(func)
    async def guarded(*args, **kwargs):
        interaction = MainBot.FindInteraction(args, kwargs)
        try:
            if interaction is None or await MainBot.IsUserBlacklisted(interaction, logUsage=False):
                return None
            await interaction.response.defer()
            return await func(*args, **kwargs)
        except Utils.CommandAbort:
            return None
        except Exception as e:
            await Logger.LogInteractionError(interaction=interaction, client=MainBot.GetClient(), message=f"Unhandled exception in button: {e}")
    return guarded
