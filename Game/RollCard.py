import io
import math
import os
import re

from PIL import Image, ImageDraw, ImageFont
from dataclasses import dataclass
from functools import lru_cache
from string import capwords
from typing import NamedTuple

from Game import ArmorImages
from Utils import Variables
from Utils import Utils
from Game import Items

scale = 2
minWidth = 480
pad = 16
columnSide = 64
columnGap = 28
columnMax = 96
iconGap = 8
lineHeight = 23
modHeight = 20
pieceSpacing = 26
quoteIndent = 12
footerGap = 16
dividerGap = 16

# Panels and pills
panelPadX = 10
panelPadY = 6
panelRadius = 10
panelFill = (255, 255, 255, 18)
panelBorder = (255, 255, 255, 41)
pillPad = 5
pillHeight = 18
pillAlpha = 41
pillLift = 1

# Text and icons
bodySize = 16
modSize = 14
swatchSize = 12
swatchGap = 6
starSize = 16
emojiSize = 20
emojiDrop = 2

# Colors
nameColor = (242, 243, 245, 255)
textColor = (219, 222, 225, 255)
mutedColor = (148, 155, 164, 255)
positiveColor = (87, 242, 135, 255)
negativeColor = (250, 100, 100, 255)
starColor = (250, 168, 26, 255)
quoteBarColor = (78, 80, 88, 255)
dividerColor = (63, 65, 71, 255)
slotColor = (43, 45, 49, 255)
shadowColor = (0, 0, 0, 255)

# Loot
lootCell = (88, 86)
lootGap = 6
lootColumns = 6
lootIcon = 32
lootRadius = 6

lootPath = Variables.ARMOR_IMAGES_PATH
emojiPattern = re.compile(r"^<a?:(\w+):(\d+)>$")
emojis: dict[str, Image.Image] = {}

class Token(NamedTuple):
    word: str
    kind: str
    width: float
    emoji: Image.Image | None
    color: tuple | None
    pill: bool

class Row(NamedTuple):
    line: list[Token]
    size: float
    height: float

@dataclass(slots=True)
class Title:
    name: str
    chip: str
    rarity: str
    color: tuple
    barOutline: tuple | None
    nameWidth: float
    chipWidth: float
    rarityWidth: float
    dashWidth: float

    @property
    def width(self) -> float:
        return self.rarityWidth + self.dashWidth + self.nameWidth + self.chipWidth + 18

class Layout(NamedTuple):
    icons: list[Image.Image]
    columnWidth: float
    columnHeight: float
    textX: float
    width: float
    blocks: list[list[Row]]
    textHeight: float

def S(value: float) -> int:
    return round(value * scale)

@lru_cache(maxsize=None)
def Font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size)

def Measure(text: str, kind: str, size: float) -> float:
    return Font(kind, S(size)).getlength(text) / scale

def DrawText(draw: ImageDraw.ImageDraw, x: float, y: float, text: str, kind: str, size: float, fill: tuple, height: float = lineHeight) -> None:
    draw.text((S(x), S(y + height / 2)), text, font=Font(kind, S(size)), fill=fill, anchor="lm", stroke_width=int(kind == "Bold"), stroke_fill=fill)

def Glass(canvas: Image.Image, box: tuple, radius: float, fill: tuple, outline: tuple | None = None) -> None:
    x0, y0, x1, y1 = (S(value) for value in box)
    layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((0, 0, x1 - x0 - 1, y1 - y0 - 1), radius=S(radius), fill=fill, outline=outline, width=S(1))
    canvas.alpha_composite(layer, (x0, y0))

def Tokens(text: str, size: float = bodySize, color: tuple | None = None, pill: bool = False) -> list[Token]:
    tokens = []
    for number, part in enumerate(text.split("**")):
        kind = "Bold" if number % 2 else "Regular"
        for word in part.split():
            match = emojiPattern.match(word)
            if match and match[2] in emojis:
                tokens.append(Token(word, kind, emojiSize, emojis[match[2]], None, False))
                continue
            if match:
                word = f":{match[1]}:"
            tokens.append(Token(word, kind, Measure(word, kind, size) + (pillPad * 2 if pill else 0), None, color, pill))
    return tokens

def WrapUnits(units: list[list[Token]], maxWidth: float, size: float) -> list[list[Token]]:
    space = Measure(" ", "Regular", size)
    lines, line, used = [], [], 0.0
    for unit in units:
        width = sum(token.width for token in unit) + space * (len(unit) - 1)
        if line and used + space + width > maxWidth:
            lines.append(line)
            line, used = [], 0.0
        used += (space if line else 0) + width
        line += unit
    return lines + [line] if line else lines

def Wrap(tokens: list[Token], maxWidth: float, size: float) -> list[list[Token]]:
    return WrapUnits([[token] for token in tokens], maxWidth, size)

def DrawLine(canvas: Image.Image, draw: ImageDraw.ImageDraw, x: float, y: float, line: list[Token], size: float, height: float) -> None:
    space = Measure(" ", "Regular", size)
    for word, kind, width, emoji, color, pill in line:
        if emoji is not None:
            emojiY = y + (height - emojiSize) / 2 + emojiDrop
            canvas.alpha_composite(emoji.resize((S(emojiSize), S(emojiSize)), Image.LANCZOS), (S(x), S(emojiY)))
        else:
            if pill:
                centre = y + height / 2
                Glass(canvas, (x, centre - pillHeight / 2, x + width, centre + pillHeight / 2), pillHeight / 2, (*color[:3], pillAlpha))
            fill = color or (nameColor if kind == "Bold" else textColor)
            DrawText(draw, x + (pillPad if pill else 0), y - (pillLift if pill else 0), word, kind, size, fill, height)
        x += width + space

def RowsHeight(rows: list[Row]) -> float:
    return sum(row.height for row in rows)

def ModLines(calc: dict, maxWidth: float) -> list[Row]:
    mods = calc.get("mods", {})
    if not mods:
        return []
    units = [Tokens("Rarity modifiers:", modSize, mutedColor)]
    for number, (key, value) in enumerate(mods.items()):
        percent = f"**{'+' if value >= 0 else '-'}{round(abs(value) * 100, 2):g}%**"
        label = key + ("," if number < len(mods) - 1 else "")
        units.append(Tokens(percent, modSize + 1, positiveColor if value >= 0 else negativeColor, True) + Tokens(label, modSize, textColor))
    return [Row(line, modSize, modHeight) for line in WrapUnits(units, maxWidth, modSize)]

def PieceRows(craft: dict, maxWidth: float) -> list[Row]:
    if not craft:
        return []
    dyes = Items.DyeText(craft["recipe"])
    rows = [Row(line, bodySize, lineHeight) for line in Wrap(Tokens(f"**Recipe:** {dyes}"), maxWidth, bodySize)] if dyes else []
    return rows + ModLines(craft["calc"], maxWidth)

def BlockHeight(rows: list[Row]) -> float:
    return lineHeight + (2 + RowsHeight(rows) if rows else 0)

def Luminance(hexCode: str) -> float:
    channels = [int(hexCode[number:number + 2], 16) / 255 for number in (0, 2, 4)]
    r, g, b = (value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4 for value in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def DrawStar(draw: ImageDraw.ImageDraw, x: float, y: float, size: float, fill: tuple) -> None:
    outer = size / 2
    points = []
    for number in range(10):
        radius = outer if number % 2 == 0 else outer * 0.4
        angle = -math.pi / 2 + number * math.pi / 5
        points.append((S(x + outer + math.cos(angle) * radius), S(y + math.sin(angle) * radius)))
    draw.polygon(points, fill=fill)

def MakeTitle(piece) -> Title:
    chip, rarity, name = f"#{piece.hex}", Items.FormatRarity(piece.rarity), Items.PieceName(piece)
    return Title(
        name=name,
        chip=chip,
        rarity=rarity,
        color=(*bytes.fromhex(piece.hex), 255),
        barOutline=quoteBarColor if Luminance(piece.hex) < 0.04 else None,
        nameWidth=Measure(name, "Bold", bodySize),
        chipWidth=swatchSize + swatchGap + Measure(chip, "Regular", bodySize),
        rarityWidth=starSize + 4 + Measure(rarity, "Regular", bodySize),
        dashWidth=Measure("-", "Regular", bodySize),
    )

def DrawChip(draw: ImageDraw.ImageDraw, x: float, y: float, title: Title) -> None:
    top = y + (lineHeight - swatchSize) / 2
    draw.rounded_rectangle((S(x), S(top), S(x + swatchSize), S(top + swatchSize)), radius=S(2), fill=title.color, outline=title.barOutline, width=S(1))
    DrawText(draw, x + swatchSize + swatchGap, y, title.chip, "Regular", bodySize, textColor)

def DrawTitle(draw: ImageDraw.ImageDraw, x: float, y: float, title: Title) -> None:
    DrawStar(draw, x, y + lineHeight / 2, starSize, starColor)
    DrawText(draw, x + starSize + 4, y, title.rarity, "Regular", bodySize, textColor)
    x += title.rarityWidth + 3
    DrawText(draw, x, y, "-", "Regular", bodySize, mutedColor)
    x += title.dashWidth + 3
    DrawText(draw, x, y, title.name, "Bold", bodySize, nameColor)
    DrawChip(draw, x + title.nameWidth + 10, y, title)

def PlanLayout(images: list[Image.Image], owned: list, titleWidth: float, side: float) -> Layout:
    fit = S(side) / max(max(image.size) for image in images)
    icons = [image.resize((max(1, round(image.width * fit)), max(1, round(image.height * fit))), Image.LANCZOS) for image in images]
    columnWidth = max(icon.width for icon in icons) / scale
    columnHeight = sum(icon.height for icon in icons) / scale + iconGap * (len(icons) - 1)
    textX = pad + columnWidth + columnGap
    width = max(minWidth, textX + titleWidth + pad)
    blocks = [PieceRows(piece.craft, width - textX - pad - quoteIndent) for piece in owned]
    textHeight = sum(BlockHeight(rows) for rows in blocks) + pieceSpacing * (len(blocks) - 1)
    return Layout(icons, columnWidth, columnHeight, textX, width, blocks, textHeight)

def Render(pieces: list, info: dict | None = None) -> tuple[list, bytes]:
    allSlots = ArmorImages.SetSlots(pieces)
    owned = [piece for _, piece, _ in allSlots if piece is not None]
    slots = [row for row in allSlots if row[1] is not None]
    images = [image for _, _, image in allSlots if image is not None]
    titles = [MakeTitle(piece) for piece in owned]
    titleWidth = max(title.width for title in titles)

    layout = PlanLayout(images, owned, titleWidth, columnSide)
    side = min(columnMax, max(columnSide, columnSide * layout.textHeight / layout.columnHeight))
    if side != columnSide:
        layout = PlanLayout(images, owned, titleWidth, side)
    icons, columnWidth, columnHeight, textX, width, blocks, textHeight = layout
    content = max(textHeight, columnHeight)

    footer: list[Row] = []
    if info:
        mode = capwords(str(info["mode"]).replace("_", " "))
        footer = [Row(line, bodySize, lineHeight) for line in Wrap(Tokens(f"**Dye mode:** {mode}"), width - pad * 2, bodySize)]
        footer += ModLines(info["calc"], width - pad * 2)
    footerHeight = dividerGap + footerGap + 1 + RowsHeight(footer) if footer else 0

    canvas = Image.new("RGBA", (S(width), S(pad + content + footerHeight + pad)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    y = pad + (content - columnHeight) / 2
    for icon in icons:
        canvas.alpha_composite(icon, (S(pad) + (S(columnWidth) - icon.width) // 2, S(y)))
        y += icon.height / scale + iconGap

    y = pad + (content - textHeight) / 2
    for title, rows in zip(titles, blocks):
        blockHeight = BlockHeight(rows)
        Glass(canvas, (textX - panelPadX, y - panelPadY, width - pad + panelPadX, y + blockHeight + panelPadY), panelRadius, panelFill, panelBorder)
        DrawTitle(draw, textX, y, title)
        y += lineHeight
        if rows:
            y += 2
            draw.rounded_rectangle((S(textX), S(y), S(textX + 4), S(y + RowsHeight(rows))), radius=S(2), fill=title.color)
            for line, size, height in rows:
                DrawLine(canvas, draw, textX + quoteIndent, y, line, size, height)
                y += height
        y += pieceSpacing

    if footer:
        y = pad + content + dividerGap
        draw.line((S(pad), S(y), S(width - pad), S(y)), fill=dividerColor, width=S(1))
        y += 1 + footerGap
        Glass(canvas, (pad - panelPadX, y - panelPadY, width - pad + panelPadX, y + RowsHeight(footer) + panelPadY), panelRadius, panelFill, panelBorder)
        for line, size, height in footer:
            DrawLine(canvas, draw, pad, y, line, size, height)
            y += height

    return slots, ToPNG(canvas)

def ToPNG(canvas: Image.Image) -> bytes:
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()

def LoadEmojis(bundles: list) -> None:
    wanted = {
        emojiID
        for bundle in bundles for piece in bundle.pieces
        for emojiID in re.findall(r"<a?:\w+:(\d+)>", Items.CraftLine(piece.craft))
        if emojiID not in emojis
    }
    for emojiID in wanted:
        try:
            emojis[emojiID] = Image.open(os.path.join(Variables.ARMOR_IMAGES_PATH, f"emoji_{emojiID}.png")).convert("RGBA")
        except Exception:
            pass

def Fit(text: str, kind: str, size: float, maxWidth: float) -> str:
    while len(text) > 1 and Measure(text, kind, size) > maxWidth:
        text = text[:-2] + "\u2026"
    return text

def LootIcon(name: str, path: str) -> Image.Image:
    side = S(lootIcon)
    try:
        image = Image.open(os.path.join(lootPath, path)).convert("RGBA")
    except FileNotFoundError:
        tile = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        tileDraw = ImageDraw.Draw(tile)
        tileDraw.rounded_rectangle((0, 0, side - 1, side - 1), radius=S(lootRadius), fill=quoteBarColor)
        tileDraw.text((side / 2, side / 2), name[0], font=Font("Bold", S(24)), fill=mutedColor, anchor="mm")
        return tile
    return image.resize((side, side), Image.NEAREST if max(image.size) <= side else Image.LANCZOS)

def RenderLoot(loot: list) -> bytes:
    rows = math.ceil(len(loot) / lootColumns)
    columns = math.ceil(len(loot) / rows)
    cellWidth, cellHeight = lootCell
    gridWidth = columns * cellWidth + (columns - 1) * lootGap
    width = max(minWidth, gridWidth + pad * 2)
    left = (width - gridWidth) / 2
    canvas = Image.new("RGBA", (S(width), S(pad * 2 + rows * cellHeight + (rows - 1) * lootGap)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    for number, (name, count, coins, image) in enumerate(loot):
        row, column = divmod(number, columns)
        inRow = min(columns, len(loot) - row * columns)
        x = left + (columns - inRow) * (cellWidth + lootGap) / 2 + column * (cellWidth + lootGap)
        y = pad + row * (cellHeight + lootGap)
        draw.rounded_rectangle((S(x), S(y), S(x + cellWidth), S(y + cellHeight)), radius=S(lootRadius), fill=slotColor, outline=dividerColor, width=S(1))
        canvas.alpha_composite(LootIcon(name, image), (S(x + (cellWidth - lootIcon) / 2), S(y + 8)))
        if count > 1:
            stack = f"x{count}"
            stackX = x + cellWidth - 6 - Measure(stack, "Bold", 13)
            DrawText(draw, stackX + 1, y + 5, stack, "Bold", 13, shadowColor, 16)
            DrawText(draw, stackX, y + 4, stack, "Bold", 13, nameColor, 16)
        label = Fit(name, "Regular", 12, cellWidth - 8)
        DrawText(draw, x + (cellWidth - Measure(label, "Regular", 12)) / 2, y + 8 + lootIcon + 4, label, "Regular", 12, mutedColor, 16)
        value = str(Utils.CompactNumber(coins))
        DrawText(draw, x + (cellWidth - Measure(value, "Bold", 14)) / 2, y + 8 + lootIcon + 20, value, "Bold", 14, starColor, 20)
    return ToPNG(canvas)
