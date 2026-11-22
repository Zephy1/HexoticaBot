import math
import io

from PIL import Image, ImageDraw
from functools import lru_cache
from typing import NamedTuple
from types import SimpleNamespace

from Game import ArmorImages
from Game import RollCard
from Game import Inventory
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
goldColor = (255, 215, 64, 255)
maxSideColumns = 5
showcaseIcon = 40
showcaseGap = showcaseIcon * RollCard.iconGap / RollCard.columnSide
showcaseSetGap = 20
showcaseColumnGap = 10
showcaseTop = 26
showcaseColumns = 8
showcaseStar = 18
previewIcon = 40
previewGap = 6

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
    return ArmorImages.Fit(image, S(iconSide))

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

def DrawCheck(draw: ImageDraw.ImageDraw, x: float, y: float, size: float = badgeSize) -> None:
    grow = size / badgeSize
    draw.ellipse((S(x), S(y), S(x + size), S(y + size)), fill=RollCard.positiveColor)
    cx, cy = x + size / 2, y + size / 2
    draw.line([(S(cx - 4.5 * grow), S(cy)), (S(cx - 1 * grow), S(cy + 3.5 * grow)), (S(cx + 4.5 * grow), S(cy - 3.5 * grow))], fill=(20, 40, 28, 255), width=S(2 * grow), joint="curve")

def DrawBadge(draw: ImageDraw.ImageDraw, x: float, y: float, text: str, fill: tuple) -> None:
    draw.ellipse((S(x), S(y), S(x + badgeSize), S(y + badgeSize)), fill=fill)
    Centered(draw, x + badgeSize / 2, y, text, "Bold", 11 if len(text) < 2 else 9, white, badgeSize)

def DrawPill(draw: ImageDraw.ImageDraw, right: float, y: float, text: str, fill: tuple) -> float:
    width = RollCard.Measure(text, "Bold", pillSize) + pillPad * 2
    left = right - width
    draw.rounded_rectangle((S(left), S(y), S(right), S(y + pillHeight)), radius=S(pillHeight / 2), fill=fill)
    RollCard.DrawText(draw, left + pillPad, y, text, "Bold", pillSize, white, pillHeight)
    return left

def DrawTile(canvas: Image.Image, draw: ImageDraw.ImageDraw, x: float, y: float, item: Inventory.InventoryItem, selected: bool, currentSlot: int | None = None) -> None:
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
        DrawPill(draw, right, pillY, "IN TRADE", lockedPillFill)
    if item.showcased:
        DrawBadge(draw, x + badgeInset, y + badgeInset, "S" if currentSlot is None or currentSlot == item.showcaseSlot else str(item.showcaseSlot), showcaseFill)

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
    RollCard.DrawText(draw, x + tileWidth - 8 - RollCard.Measure(value, "Bold", detailSize + 1), bottomY, value, "Bold", detailSize + 1, goldColor, 16)

def Draw(items: list[Inventory.InventoryItem], selected: set[Utils.ItemID], columns: int, minRows: int = 1, currentSlot: int | None = None) -> Image.Image:
    rows = max(minRows, math.ceil(len(items) / columns))
    width = margin * 2 + columns * tileWidth + (columns - 1) * tileGap
    height = margin * 2 + rows * tileHeight + (rows - 1) * tileGap
    canvas = Image.new("RGBA", (S(width), S(height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    for index, item in enumerate(items):
        row, column = divmod(index, columns)
        x = margin + column * (tileWidth + tileGap)
        y = margin + row * (tileHeight + tileGap)
        DrawTile(canvas, draw, x, y, item, item.itemID in selected, currentSlot)
    if not items:
        grow = max(1, width / 256)
        draw.rounded_rectangle((S(margin), S(margin), S(width - margin), S(height - margin)), radius=S(tileRadius), outline=RollCard.dividerColor, width=S(1))
        Centered(draw, width / 2, height / 2 - 9 * grow, "Empty", "Bold", 14 * grow, RollCard.mutedColor, 18 * grow)
    return canvas

def Render(items: list[Inventory.InventoryItem], selected: set[Utils.ItemID], currentSlot: int | None = None, columns: int = Inventory.pageColumns) -> bytes:
    return RollCard.ToPNG(Draw(items, selected, columns, currentSlot=currentSlot))

class SideLabel(NamedTuple):
    title: str
    locked: bool
    detail: list[tuple[str, bool]]
    total: str
    avatar: bytes | None

@lru_cache(maxsize=64)
def Avatar(data: bytes | None, side: int) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data)).convert("RGBA").resize((side, side), Image.LANCZOS)
    except Exception:
        image = Image.new("RGBA", (side, side), RollCard.dividerColor)
    mask = Image.new("L", (side * 4, side * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, side * 4 - 1, side * 4 - 1), fill=255)
    image.putalpha(mask.resize((side, side), Image.LANCZOS))
    return image

def RenderSides(left: list[Inventory.InventoryItem], right: list[Inventory.InventoryItem], labels: list[SideLabel]) -> list[bytes]:
    count = max(len(left), len(right))
    columns = min(maxSideColumns, max(2, math.ceil(math.sqrt(count))))
    rows = max(1, math.ceil(count / columns))
    pngs = []
    for items, label in zip((left, right), labels):
        grid = Draw(items, set(), columns, rows)
        grow = grid.width / S(256)
        header = S(40 * grow)
        side = max(grid.width, grid.height + header)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.alpha_composite(grid, ((side - grid.width) // 2, header + (side - header - grid.height) // 2))
        draw = ImageDraw.Draw(canvas)
        x = (side - grid.width) / S(1) / 2 + margin
        canvas.alpha_composite(Avatar(label.avatar, S(32 * grow)), (S(x), S(4 * grow)))
        textX = x + 38 * grow
        room = grid.width / S(1) - margin * 2 - 38 * grow
        indent = 0
        if label.locked:
            DrawCheck(draw, textX, 6 * grow, 16 * grow)
            indent = 21 * grow
        totalWidth = RollCard.Measure(label.total, "Bold", 13 * grow) if label.total else 0
        nameRoom = room - indent - (totalWidth + 8 * grow if totalWidth else 0)
        RollCard.DrawText(draw, textX + indent, 4 * grow, RollCard.Fit(label.title, "Bold", 15 * grow, nameRoom), "Bold", 15 * grow, RollCard.nameColor, 20 * grow)
        if label.total:
            RollCard.DrawText(draw, textX + room - totalWidth, 4 * grow, label.total, "Bold", 13 * grow, goldColor, 20 * grow)
        size = 12 * grow
        detailWidth = sum(RollCard.Measure(part, "Regular", size) for part, _ in label.detail)
        size *= min(1, room / detailWidth) if detailWidth else 1
        for part, gold in label.detail:
            RollCard.DrawText(draw, textX, 24 * grow, part, "Regular", size, goldColor if gold else RollCard.mutedColor, 16 * grow)
            textX += RollCard.Measure(part, "Regular", size)
        pngs.append(RollCard.ToPNG(canvas))
    return pngs

def SetImages(pieces: list[Inventory.InventoryItem], seated: bool = True) -> list[Image.Image | None]:
    try:
        rows = ArmorImages.SetSlots([SimpleNamespace(armor=Utils.ArmorType(piece.armor), slot=Utils.ArmorSlot(piece.slot), hex=piece.hexCode) for piece in pieces], showFixed=True, seated=seated)
        images = {slot: image for slot, _, image in rows}
        return [images.get(slot) for slot in ArmorImages.slotOrder]
    except Exception:
        owned = {Utils.ArmorSlot(piece.slot): piece for piece in pieces}
        side = ArmorImages.ReferenceSize()
        return [PlaceholderIcon(owned[slot].hexCode).resize((side, side), Image.LANCZOS) if slot in owned else None for slot in ArmorImages.slotOrder]

def DrawShowcaseTile(canvas: Image.Image, draw: ImageDraw.ImageDraw, x: float, y: float, cells: list[tuple[Image.Image | None, int]], width: float, earning: bool) -> None:
    if earning:
        RollCard.DrawStar(draw, x + (width - showcaseStar) / 2, y + showcaseStar / 2, showcaseStar, RollCard.starColor)
    top = y + showcaseTop
    for icon, height in cells:
        if icon is not None:
            canvas.alpha_composite(icon, (S(x + width / 2) - icon.width // 2, S(top) + max(0, height - icon.height) // 2))
        top += height / RollCard.scale + showcaseGap

def RenderPreview(pieces: list[Inventory.InventoryItem]) -> bytes:
    images = SetImages(pieces, seated=False)
    width = margin * 2 + len(images) * previewIcon + (len(images) - 1) * previewGap
    canvas = Image.new("RGBA", (S(width), S(margin * 2 + previewIcon)), (0, 0, 0, 0))
    for number, image in enumerate(images):
        if image is None:
            continue
        icon = ArmorImages.Fit(image, S(previewIcon))
        cellX, cellY = S(margin + number * (previewIcon + previewGap)), S(margin)
        canvas.alpha_composite(icon, (cellX + (S(previewIcon) - icon.width) // 2, cellY + (S(previewIcon) - icon.height) // 2))
    return RollCard.ToPNG(canvas)

def RenderShowcase(sets: list[tuple[list[Inventory.InventoryItem], bool]]) -> bytes:
    columns = []
    for pieces, earning in sets:
        cells = []
        for slot, image in zip(ArmorImages.slotOrder, SetImages(pieces)):
            icon = None if image is None else ArmorImages.Fit(image, S(showcaseIcon))
            cells.append((icon, ArmorImages.CellHeight(slot, S(showcaseIcon))))
        width = max(icon.width for icon, _ in cells if icon is not None) / RollCard.scale
        height = sum(cell[1] for cell in cells) / RollCard.scale + showcaseGap * (len(cells) - 1)
        columns.append((cells, width, height, earning))
    rows = [columns[start:start + showcaseColumns] for start in range(0, len(columns), showcaseColumns)]
    rowWidths = [sum(column[1] for column in row) + showcaseColumnGap * (len(row) - 1) for row in rows]
    rowHeights = [showcaseTop + max(column[2] for column in row) for row in rows]
    canvas = Image.new("RGBA", (S(margin * 2 + max(rowWidths)), S(margin * 2 + sum(rowHeights) + showcaseSetGap * (len(rows) - 1))), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    y = margin
    for row, height in zip(rows, rowHeights):
        x = margin
        for cells, width, _, earning in row:
            DrawShowcaseTile(canvas, draw, x, y, cells, width, earning)
            x += width + showcaseColumnGap
        y += height + showcaseSetGap
    return RollCard.ToPNG(canvas)
