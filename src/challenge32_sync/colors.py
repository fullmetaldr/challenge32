from __future__ import annotations

from collections.abc import Iterable


COLOR_CODE_BY_NAME = {
    "W": "W",
    "WHITE": "W",
    "U": "U",
    "BLUE": "U",
    "B": "B",
    "BLACK": "B",
    "R": "R",
    "RED": "R",
    "G": "G",
    "GREEN": "G",
}

IDENTITY_NAMES = {
    "": "colorless",
    "W": "white",
    "U": "blue",
    "B": "black",
    "R": "red",
    "G": "green",
    "WU": "azorius",
    "UB": "dimir",
    "BR": "rakdos",
    "RG": "gruul",
    "GW": "selesnya",
    "WB": "orzhov",
    "UR": "izzet",
    "BG": "golgari",
    "RW": "boros",
    "GU": "simic",
    "WUB": "esper",
    "UBR": "grixis",
    "BRG": "jund",
    "WRG": "naya",
    "WUG": "bant",
    "WBG": "abzan",
    "URG": "temur",
    "WUR": "jeskai",
    "UBG": "sultai",
    "WBR": "mardu",
    "WUBR": "yore-tiller",
    "WUBG": "witch-maw",
    "WURG": "ink-treader",
    "WBRG": "dune-brood",
    "UBRG": "glint-eye",
    "WUBRG": "five-color",
}

COLOR_ORDER = {color: index for index, color in enumerate("WUBRG")}


def color_codes(values: Iterable[str]) -> str:
    codes = {
        COLOR_CODE_BY_NAME[str(value).strip().upper()]
        for value in values
        if str(value).strip().upper() in COLOR_CODE_BY_NAME
    }
    return "".join(sorted(codes, key=COLOR_ORDER.__getitem__))


def identity_name(values: Iterable[str]) -> str | None:
    codes = color_codes(values)
    return IDENTITY_NAMES.get(codes)
