import MainBot

import discord
import asyncio
import io

from Utils.Translation import Say, Text
from Commands.Admin import adminGroup
from Game import InventoryCard
from Game import ArmorImages
from Game import Inventory
from Utils import Logger
from Utils import Utils

testColors = [
    "D87F33",
    "6699D8",
    "7FCC19",
    "F27FA5",
    "E5E533",
    "7F3FB2",
]

def Piece(armor: Utils.ArmorType, slot: Utils.ArmorSlot, number: int) -> Inventory.InventoryItem:
    return Inventory.InventoryItem(
        itemID=f"test{number}{slot}",
        armor=str(armor),
        slot=slot.value,
        hexCode=testColors[number % len(testColors)],
        name=slot.title(),
        rarity=0,
        claimedAt=0,
        value=0,
        showcaseSlot=None,
        locked=False,
        special=False,
    )

def Formats() -> list[tuple[str, list[Inventory.InventoryItem]]]:
    formats: list[tuple[str, list[Inventory.InventoryItem]]] = []
    seen = set()
    for armor, armorSet in Utils.ARMOR_SETS.items():
        key = (tuple(armorSet.pieces), tuple(ArmorImages.fixedPieces.get(armor, {}).items()))
        if key not in seen:
            seen.add(key)
            formats.append((Inventory.ArmorLabel(armor), [Piece(armor, slot, len(formats)) for slot in armorSet.pieces]))
    formats.append(("Lone helmet", [Piece(Utils.ArmorType.MAGMA, Utils.ArmorSlot.HELMET, len(formats))]))
    formats.append(("3 piece", [
        Piece(Utils.ArmorType.OBSIDIAN_CHESTPLATE, Utils.ArmorSlot.CHESTPLATE, len(formats)),
        Piece(Utils.ArmorType.STEREO_PANTS, Utils.ArmorSlot.LEGGINGS, len(formats)),
        Piece(Utils.ArmorType.SQUID_BOOTS, Utils.ArmorSlot.BOOTS, len(formats)),
    ]))
    return formats

@MainBot.AppCommandWithAliases(
    adminGroup,
    name="armor_test",
    description=Say(Text.ADMIN_ARMOR_TEST_DESCRIPTION),
    permission=Utils.Permission.OWNER,
)
async def Command_AdminArmorTest(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True, ephemeral=True)
    formats = Formats()
    png = await asyncio.to_thread(InventoryCard.RenderShowcase, [(pieces, False) for _, pieces in formats])
    names = ", ".join(f"{number}. {name}" for number, (name, _) in enumerate(formats, 1))
    await Logger.SendInteractionMessage(
        interaction=interaction,
        message=Say(Text.ADMIN_ARMOR_TEST_DONE, count=len(formats), s=Utils.PluralS(len(formats)), names=names)[:2000],
        discordFile=discord.File(io.BytesIO(png), filename="armor_test.png"),
        ephemeral=True,
    )
