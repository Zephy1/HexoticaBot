import os

from functools import lru_cache
from PIL import Image

from Utils import Variables
from Utils import Utils

version = "New"
imageSize = 128
slotOrder = list(Utils.ArmorSlot)
overlaySlots = {
    Utils.ArmorSlot.HELMET,
    Utils.ArmorSlot.LEGGINGS,
    Utils.ArmorSlot.BOOTS,
}
blockHelmets = (
    "lapis",
    "leaflet",
    "sponge",
    "haybale",
    "space",
)
versionedItems = {
    "LapisHelmet",
    "SpongeHelmet",
    "LeafletHelmet",
    "HaybaleHelmet",
    "DiamondHelmet",
    "GoldHelmet",
    "IronLeggings",
    "IronBoots",
    "ChainmailChestplate",
    "SpaceHelmet",
}

def HelmetFiles(armors: tuple, suffix: str) -> dict[Utils.ArmorType, dict[Utils.ArmorSlot, str]]:
    return {armor: {Utils.ArmorSlot.HELMET: f"{armor.name.title().replace('_', '')}{suffix}"} for armor in armors}

fixedPieces: dict[Utils.ArmorType, dict[Utils.ArmorSlot, str]] = {
    Utils.ArmorType.ANGLER: {Utils.ArmorSlot.HELMET: "DiamondHelmet.webp"},
    Utils.ArmorType.CHEAP_TUXEDO: {Utils.ArmorSlot.HELMET: "GoldHelmet.webp"},
    Utils.ArmorType.FANCY_TUXEDO: {Utils.ArmorSlot.HELMET: "GoldHelmet.webp"},
    Utils.ArmorType.ELEGANT_TUXEDO: {Utils.ArmorSlot.HELMET: "GoldHelmet.webp"},
    Utils.ArmorType.PACK: {Utils.ArmorSlot.LEGGINGS: "IronLeggings.webp", Utils.ArmorSlot.BOOTS: "IronBoots.webp"},
    Utils.ArmorType.FARM_ARMOR: {Utils.ArmorSlot.HELMET: "HaybaleHelmet.png"},
    Utils.ArmorType.PUMPKIN: {Utils.ArmorSlot.HELMET: "SproutHelmet.png"},
    Utils.ArmorType.TARANTULA: {Utils.ArmorSlot.CHESTPLATE: "ChainmailChestplate.webp", Utils.ArmorSlot.BOOTS: "IronBoots.webp"},
    **HelmetFiles((
        Utils.ArmorType.BAT_PERSON,
        Utils.ArmorType.BACKWATER,
        Utils.ArmorType.SPOOKY,
        Utils.ArmorType.BLAZE,
        Utils.ArmorType.FROZEN_BLAZE,
        Utils.ArmorType.MASTIFF,
        Utils.ArmorType.LAPIS,
        Utils.ArmorType.LEAFLET,
        Utils.ArmorType.BIOHAZARD,
        Utils.ArmorType.SPONGE,
        Utils.ArmorType.SHARK,
    ), "Helmet.webp"),
    **HelmetFiles((
        Utils.ArmorType.SUPERIOR,
        Utils.ArmorType.YOUNG,
        Utils.ArmorType.WISE,
        Utils.ArmorType.PROTECTOR,
        Utils.ArmorType.UNSTABLE,
        Utils.ArmorType.OLD,
        Utils.ArmorType.STRONG,
    ), "HelmetBaby.webp"),
}

@lru_cache(maxsize=128)
def LoadCached(path: str) -> Image.Image:
    with Image.open(path) as image:
        return image.resize((imageSize, imageSize)).convert("RGBA")

def Load(name: str) -> Image.Image:
    stem, extension = os.path.splitext(name)
    if stem.startswith("Leather"):
        stem += f"_Version={version}_Size={imageSize}x"
    elif stem in versionedItems:
        stem += f"_Version={version}"
    return LoadCached(os.path.join(Variables.ARMOR_IMAGES_PATH, stem + extension)).copy()

def Tint(image: Image.Image, hexCode: str) -> Image.Image:
    *rgb, alpha = image.split()
    channels = bytes.fromhex(hexCode)
    tinted = [band.point([value * channel // 255 for value in range(256)]) for band, channel in zip(rgb, channels)]
    return Image.merge("RGBA", [*tinted, alpha])

def LeatherPiece(slot: Utils.ArmorSlot, hexCode: str) -> Image.Image:
    name = slot.title()
    image = Tint(Load(f"Leather{name}.png"), hexCode)
    if slot in overlaySlots:
        image = Image.alpha_composite(image, Load(f"Leather{name}Overlay.png"))
    return image

def Crop(image: Image.Image) -> Image.Image:
    box = image.getbbox()
    return image.crop(box) if box else image

def SlotImage(slot: Utils.ArmorSlot, owned: dict, fixed: dict[Utils.ArmorSlot, str]) -> Image.Image | None:
    if slot in owned:
        return Crop(LeatherPiece(slot, owned[slot].hex))
    if slot in fixed:
        return Crop(Load(fixed[slot]))
    return None

def SetSlots(pieces: list) -> list[tuple[Utils.ArmorSlot, object, Image.Image | None]]:
    armors = {piece.armor for piece in pieces}
    if len(armors) != 1 or len({piece.slot for piece in pieces}) != len(pieces):
        return [
            (piece.slot, piece, Crop(LeatherPiece(piece.slot, piece.hex)))
            for piece in sorted(pieces, key=lambda piece: slotOrder.index(piece.slot))
        ]

    armor = armors.pop()
    owned = {piece.slot: piece for piece in pieces}
    fixed = fixedPieces.get(armor, {})
    whole = set(Utils.ARMOR_SETS[armor].pieces) if armor in Utils.ARMOR_SETS else set()
    if not whole <= set(owned):
        fixed = {slot: name for slot, name in fixed.items() if slot != Utils.ArmorSlot.HELMET}
    slots = whole | set(fixed) | set(owned)
    return [(slot, owned.get(slot), SlotImage(slot, owned, fixed)) for slot in slotOrder if slot in slots]
