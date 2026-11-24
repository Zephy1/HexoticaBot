import MainBot

import discord

from Utils.Translation import Say, Text
from Commands.Admin import adminGroup, RequireTarget
from Utils import Logger
from Utils import Utils
from Game import Items
from Game import Lists

@MainBot.AppCommandWithAliases(
    adminGroup,
    name="give_item",
    description=Say(Text.ADMIN_GIVE_ITEM_DESCRIPTION),
    variableDescriptions={
        "user": Say(Text.GLOBAL_USER),
        "armor_type": Say(Text.ADMIN_GIVE_ITEM_ARMOR),
        "armor_slot": Say(Text.GLOBAL_PIECE_TYPE_DESCRIPTION),
        "hex_code": Say(Text.GLOBAL_COLOR_DESCRIPTION),
    },
    autoComplete={
        "armor_type": Items.AutocompleteArmorTypes,
        "armor_slot": Items.AutocompleteArmorSlots,
    },
    permission=Utils.Permission.OWNER,
)
async def Command_AdminGiveItem(
    interaction: discord.Interaction,
    user: discord.Member,
    armor_type: str,
    armor_slot: str,
    hex_code: str,
):
    await interaction.response.defer(thinking=True, ephemeral=True)
    guildID = await RequireTarget(interaction, user)

    armorType = Items.GetArmorType(armor_type)
    if armorType is None or armorType not in Lists.index.armorTypes:
        await Logger.Reply(interaction, Say(Text.ADMIN_GIVE_ITEM_BAD_ARMOR, armor=armor_type))
        return

    hexColor = Utils.TryGetHexColor(hex_code)
    if hexColor is None or hexColor.isBlank:
        await Logger.Reply(interaction, Say(Text.ADMIN_GIVE_ITEM_BAD_HEX, hexCode=hex_code))
        return

    slots = Items.ArmorSlots(armorType)
    try:
        armorSlot = Utils.ArmorSlot(armor_slot)
    except ValueError:
        armorSlot = None
    if armorSlot is None or armorSlot not in slots:
        await Logger.Reply(interaction, Say(Text.ADMIN_GIVE_ITEM_BAD_SLOT, armor=armorType, slot=armor_slot, slots=", ".join(s.lower() for s in slots)))
        return

    piece = Lists.BundlePiece(hexColor.hexCode, armorType, armorSlot, -1, f"{armorType} {armorSlot}", {})
    bundle = Lists.DropBundle("admin", "Admin", piece.rarity, [piece], void=False, info={})
    itemID = await Items.GiveItem(guildID, user.id, piece, bundle)
    embed = MainBot.CreateDefaultEmbed(
        createdAt=interaction.created_at,
        title=Say(Text.ADMIN_GIVE_ITEM_TITLE),
        description=Say(Text.ADMIN_GIVE_ITEM_BODY, userID=user.id, name=piece.name, hex=piece.hex, rarity=Items.FormatRarity(piece.rarity), itemID=itemID),
        color=discord.Color(hexColor.rgbInt),
    )
    await Logger.SendInteractionMessage(interaction=interaction, embed=embed)
