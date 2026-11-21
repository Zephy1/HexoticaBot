import re
import math

from functools import lru_cache
from typing import NamedTuple

colorThreshold = 10.0

palette: list[tuple[list[str], str]] = [
    ([
         "Red",
         "Pure Red",
         "Exotic Red",
    ], "993333"),
    ([
         "Orange",
         "Pure Orange",
         "Exotic Orange",
    ], "D87F33"),
    ([
         "Yellow",
         "Pure Yellow",
         "Exotic Yellow",
         "Yell",
    ], "E5E533"),
    ([
         "Lime",
         "Pure Lime",
         "Exotic Lime",
    ], "7FCC19"),
    ([
         "Dark Green",
         "Pure Dark Green",
         "Exotic Dark Green",
         "Pure Green",
         "Exotic Green",
         "Green",
         "DG",
         "Exotic DG",
         "Pure DG",
    ], "667F33"),
    ([
         "Cyan",
         "Pure Cyan",
         "Exotic Cyan",
    ], "4C7F99"),
    ([
         "Light Blue",
         "Pure Light Blue",
         "Exotic Light Blue",
         "Pure LB",
         "LB",
         "Exotic LB",
    ], "6699D8"),
    ([
         "Dark Blue",
         "Pure Dark Blue",
         "Pure Blue",
         "Exotic Dark Blue",
         "Blue",
         "DB",
         "Pure DB",
         "Exotic DB",
    ], "334CB2"),
    ([
         "Purple",
         "Pure Purple",
         "Exotic Purple",
         "Purp",
    ], "7F3FB2"),
    ([
         "Magenta",
         "Pure Magenta",
         "Exotic Magenta",
         "Mag",
    ], "B24CD8"),
    ([
         "Pink",
         "Pure Pink",
         "Exotic Pink",
    ], "F27FA5"),
    ([
         "Brown",
         "Pure Brown",
         "Exotic Brown",
    ], "664C33"),
    ([
         "White",
         "Pure White",
         "Exotic White",
         "True White",
         "True White Dye",
         "Pure White Dye",
    ], "FFFFFF"),
    ([
         "Light Gray",
         "Pure Light Grey",
         "Pure Light Gray",
         "Exotic Light Grey",
         "Exotic Light Gray",
         "Light Grey",
         "Pure Gray",
         "Pure Grey",
         "Exotic Gray",
         "Exotic Grey",
         "LG",
         "L Gray",
         "L Grey",
         "Exotic LG",
         "Exotic L Gray",
         "Exotic L Grey",
         "Grey",
         "Gray",
    ], "999999"),
    ([
         "Dark Gray",
         "Pure Dark Grey",
         "Pure Dark Gray",
         "Exotic Dark Grey",
         "Exotic Dark Gray",
         "Dark Grey",
         "D Gray",
         "D Grey",
         "Exotic D Grey",
         "Exotic D Gray",
    ], "4C4C4C"),
    ([
         "Black",
         "Pure Black",
         "Exotic Black",
    ], "191919"),
    ([
         "True Mint",
         "Mint",
    ], "86D28D"),
    ([
         "True Maroon",
         "Maroon",
    ], "592626"),
    ([
         "True Navy",
         "Navy",
    ], "263265"),
    ([
         "True Ice",
         "Ice",
    ], "B2CCEB"),
    ([
         "True Gold",
         "Gold",
    ], "DEB233"),
    ([
         "True Nint",
         "Nint",
    ], "B2D826"),
    ([
         "True Pistachio",
         "Pistachio",
    ], "B2BF99"),
    ([
         "True Brick",
         "Brick",
    ], "B85933"),
    ([
         "True Dark Cyan",
         "Dark Cyan",
         "D Cyan",
    ], "324C59"),
    ([
         "True Grape",
         "Grape",
    ], "4C2C65"),
    ([
         "True Jade",
         "Jade",
    ], "6DB260"),
    ([
         "True Stone",
         "Stone",
    ], "727272"),
    ([
         "True Teal",
         "Teal",
    ], "7CABA2"),
]

hexToken = re.compile(r"#?([0-9a-f]{6})")

Lab = tuple[float, float, float]
maxAliasWords = max(len(alias.split()) for aliases, _ in palette for alias in aliases)

@lru_cache(maxsize=8192)
def ToLab(hexCode: str) -> Lab:
    red, green, blue = (Linear(int(hexCode[number:number + 2], 16) / 255) for number in (0, 2, 4))
    x = Cube((0.4124564 * red + 0.3575761 * green + 0.1804375 * blue) / 0.95047)
    y = Cube(0.2126729 * red + 0.7151522 * green + 0.0721750 * blue)
    z = Cube((0.0193339 * red + 0.1191920 * green + 0.9503041 * blue) / 1.08883)
    return 116 * y - 16, 500 * (x - y), 200 * (y - z)

class Query(NamedTuple):
    colors: tuple[Lab, ...]
    words: tuple[str, ...]

def Linear(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

def Cube(value: float) -> float:
    return value ** (1 / 3) if value > 216 / 24389 else (24389 / 27 * value + 16) / 116

aliasLab: dict[str, Lab] = {alias.lower().replace(" ", ""): ToLab(hexCode) for aliases, hexCode in palette for alias in aliases}

def Parse(text: str) -> Query | None:
    tokens = [token for token in re.split(r"[\s_]+", text.lower()) if token]
    colors: list[Lab] = []
    words: list[str] = []
    index = 0
    while index < len(tokens):
        for length in range(min(maxAliasWords, len(tokens) - index), 0, -1):
            run = "".join(tokens[index:index + length])
            if run in aliasLab:
                colors.append(aliasLab[run])
                index += length
                break
        else:
            hexMatch = hexToken.fullmatch(tokens[index])
            if hexMatch:
                colors.append(ToLab(hexMatch.group(1)))
            else:
                words.append(tokens[index])
            index += 1
    return Query(tuple(colors), tuple(words)) if colors or words else None

def Nearest(query: Query, hexCode: str) -> float:
    lab = ToLab(hexCode)
    return min(math.dist(lab, target) for target in query.colors)
