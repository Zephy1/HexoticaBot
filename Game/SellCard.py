import math

from PIL import Image, ImageDraw
from functools import lru_cache

from Game import ArmorImages
from Game import RollCard
from Game import Selling
from Utils import Utils
from Game import Items

S = RollCard.S

tileWidth = 116
tileHeight = 136
tileGap = 8
tileRadius = 8
margin = 8
iconSide = 56
iconTop = 14
badgeSize = 18
badgeInset = 4
pillHeight = 14
pillPad = 5
pillGap = 4
nameSize = 12
nameLine = 14
detailSize = 11
pillSize = 9
swatchSide = 10

selectedFill = (30, 62, 45, 255)
lockedFill = (33, 34, 38, 255)
showcaseFill = (88, 101, 242, 255)
lockedPillFill = (110, 112, 120, 255)
white = (255, 255, 255, 255)
lockedIconAlpha = 0.35

def PlaceholderIcon(hexCode: str) -> Image.Image:
    side = S(iconSide)
    tile = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    ImageDraw.Draw(tile).rounded_rectangle((0, 0, side - 1, side - 1), radius=S(6), fill=(*bytes.fromhex(hexCode), 255))
    return tile

@lru_cache(maxsize=512)
def Icon(slot: str, hexCode: str) -> Image.Image:
    try:
        image = ArmorImages.Crop(ArmorImages.LeatherPiece(Utils.ArmorSlot(slot), hexCode))
    except Exception:
        return PlaceholderIcon(hexCode)
    fit = S(iconSide) / max(image.size)
    return image.resize((max(1, round(image.width * fit)), max(1, round(image.height * fit))), Image.LANCZOS)

def Fade(icon: Image.Image) -> Image.Image:
    faded = icon.copy()
    faded.putalpha(icon.getchannel("A").point(lambda alpha: int(alpha * lockedIconAlpha)))
    return faded

def Centered(draw: ImageDraw.ImageDraw, centerX: float, y: float, text: str, kind: str, size: float, fill: tuple, height: float) -> None:
    RollCard.DrawText(draw, centerX - RollCard.Measure(text, kind, size) / 2, y, text, kind, size, fill, height)

def WrapName(text: str, width: float) -> list[str]:
    words = text.split()
    for cut in range(len(words), 0, -1):
        first = " ".join(words[:cut])
        if RollCard.Measure(first, "Bold", nameSize) <= width:
            rest = " ".join(words[cut:])
            return [first, RollCard.Fit(rest, "Bold", nameSize, width)] if rest else [first]
    return [RollCard.Fit(text, "Bold", nameSize, width)]

def DrawCheck(draw: ImageDraw.ImageDraw, x: float, y: float) -> None:
    draw.ellipse((S(x), S(y), S(x + badgeSize), S(y + badgeSize)), fill=RollCard.positiveColor)
    cx, cy = x + badgeSize / 2, y + badgeSize / 2
    draw.line([(S(cx - 4.5), S(cy)), (S(cx - 1), S(cy + 3.5)), (S(cx + 4.5), S(cy - 3.5))], fill=(20, 40, 28, 255), width=S(2), joint="curve")

def DrawPill(draw: ImageDraw.ImageDraw, right: float, y: float, text: str, fill: tuple) -> float:
    width = RollCard.Measure(text, "Bold", pillSize) + pillPad * 2
    left = right - width
    draw.rounded_rectangle((S(left), S(y), S(right), S(y + pillHeight)), radius=S(pillHeight / 2), fill=fill)
    RollCard.DrawText(draw, left + pillPad, y, text, "Bold", pillSize, white, pillHeight)
    return left

def DrawTile(canvas: Image.Image, draw: ImageDraw.ImageDraw, x: float, y: float, item: Selling.SellItem, selected: bool) -> None:
    if selected:
        fill, outline, border = selectedFill, RollCard.positiveColor, 1.5
    elif item.locked:
        fill, outline, border = lockedFill, RollCard.dividerColor, 1
    elif item.special:
        fill, outline, border = RollCard.slotColor, RollCard.starColor, 1.5
    else:
        fill, outline, border = RollCard.slotColor, RollCard.dividerColor, 1
    draw.rounded_rectangle((S(x), S(y), S(x + tileWidth), S(y + tileHeight)), radius=S(tileRadius), fill=fill, outline=outline, width=S(border))

    right = x + tileWidth - badgeInset
    if selected:
        DrawCheck(draw, right - badgeSize, y + badgeInset)
        right -= badgeSize + pillGap
    pillY = y + badgeInset + (badgeSize - pillHeight) / 2
    if item.locked:
        right = DrawPill(draw, right, pillY, "IN TRADE", lockedPillFill) - pillGap
    if item.showcased:
        DrawPill(draw, right, pillY, "SHOWCASE", showcaseFill)

    icon = Fade(Icon(item.slot, item.hexCode)) if item.locked else Icon(item.slot, item.hexCode)
    iconX = S(x + (tileWidth - iconSide) / 2) + (S(iconSide) - icon.width) // 2
    iconY = S(y + iconTop) + (S(iconSide) - icon.height) // 2
    canvas.alpha_composite(icon, (iconX, iconY))

    centerX = x + tileWidth / 2
    textY = y + iconTop + iconSide + 3
    lines = WrapName(item.name, tileWidth - 12)
    for number, line in enumerate(lines):
        Centered(draw, centerX, textY + (number + (2 - len(lines)) / 2) * nameLine, line, "Bold", nameSize, RollCard.nameColor, nameLine)

    chip = f"#{item.hexCode}"
    chipWidth = swatchSide + 5 + RollCard.Measure(chip, "Regular", detailSize)
    chipX = centerX - chipWidth / 2
    chipY = textY + nameLine * 2
    swatchTop = chipY + (15 - swatchSide) / 2
    draw.rounded_rectangle((S(chipX), S(swatchTop), S(chipX + swatchSide), S(swatchTop + swatchSide)), radius=S(2), fill=(*bytes.fromhex(item.hexCode), 255), outline=RollCard.quoteBarColor if RollCard.Luminance(item.hexCode) < 0.04 else None, width=S(1))
    RollCard.DrawText(draw, chipX + swatchSide + 5, chipY, chip, "Regular", detailSize, RollCard.mutedColor, 15)

    bottomY = chipY + 16
    RollCard.DrawStar(draw, x + 8, bottomY + 8, 12, RollCard.starColor)
    RollCard.DrawText(draw, x + 8 + 12 + 3, bottomY, Items.FormatRarity(item.rarity), "Regular", detailSize + 1, RollCard.textColor, 16)
    value = str(Utils.CompactNumber(item.value))
    RollCard.DrawText(draw, x + tileWidth - 8 - RollCard.Measure(value, "Bold", detailSize + 1), bottomY, value, "Bold", detailSize + 1, RollCard.starColor, 16)

def Render(items: list[Selling.SellItem], selected: set[Utils.ItemID]) -> bytes:
    rows = max(1, math.ceil(len(items) / Selling.pageColumns))
    width = margin * 2 + Selling.pageColumns * tileWidth + (Selling.pageColumns - 1) * tileGap
    height = margin * 2 + rows * tileHeight + (rows - 1) * tileGap
    canvas = Image.new("RGBA", (S(width), S(height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    for index, item in enumerate(items):
        row, column = divmod(index, Selling.pageColumns)
        x = margin + column * (tileWidth + tileGap)
        y = margin + row * (tileHeight + tileGap)
        DrawTile(canvas, draw, x, y, item, item.itemID in selected)
    return RollCard.ToPNG(canvas)
