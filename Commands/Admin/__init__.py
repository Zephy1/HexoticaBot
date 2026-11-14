import MainBot

from discord import app_commands

from Utils.Translation import Say, Text

class AdminGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="admin", description=Say(Text.ADMIN_GROUP_DESCRIPTION), guild_only=True)

adminGroup = AdminGroup()
MainBot.GetClient().tree.add_command(adminGroup)
