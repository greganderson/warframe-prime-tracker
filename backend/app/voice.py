"""Offline relic dictation: Vosk speech recognition limited to relic vocabulary, then parsing to relic ids."""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

MODEL_PATH = Path(os.getenv("VOSK_MODEL", Path(__file__).parents[2] / "models" / "vosk-model-small-en-us-0.15"))

# The small English model has no "lith", "meso" or "axi", so each era is heard as sound-alike words.
ERA_WORDS = {
    "Lith": ["lit", "list", "lift", "leith", "liss", "lyth", "with"],
    "Meso": ["mezzo", "mesa", "maso", "mess", "massa"],
    "Neo": ["neo", "neon"],
    "Axi": ["axe", "axes", "axis", "access", "axle", "acts", "ax"],
}
LETTER_WORDS = {
    "A": ["a", "alpha"], "B": ["b", "bee", "bravo"], "C": ["c", "see", "sea", "charlie"],
    "D": ["d", "dee", "delta"], "E": ["e", "echo"], "F": ["f", "foxtrot"], "G": ["g", "gee", "golf"],
    "H": ["h", "hotel"], "I": ["i", "india"], "J": ["j", "jay"], "K": ["k", "kay", "kilo"],
    "L": ["l", "el", "lima"], "M": ["m", "em", "mike"], "N": ["n", "en", "november"],
    "O": ["o", "oh", "oscar"], "P": ["p", "pee", "papa"], "Q": ["q", "cue", "queue", "quebec"],
    "R": ["r", "are", "romeo"], "S": ["s", "ess", "sierra"], "T": ["t", "tee", "tango"],
    "U": ["u", "you", "uniform"], "V": ["v", "vee", "victor"], "W": ["w", "whiskey"],
    "X": ["x", "ex"], "Y": ["y", "why", "yankee"], "Z": ["z", "zee", "zed", "zulu"],
}
ONES = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
TEENS = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
NUMBER_WORDS = {word: index + 1 for index, word in enumerate(ONES)} | {word: index + 10 for index, word in enumerate(TEENS)}
TENS = {"twenty": 20, "thirty": 30}
# Letters that the recognizer confuses with each other; used when the heard letter matches no relic.
CONFUSABLE = [set("BCDEGPTVZ"), set("MN"), set("FSX"), set("AHJK"), set("IY"), set("QU")]
# Letters that tend to merge into the end of an era word ("axi a twelve" is often heard as "axes twelve").
SWALLOWED = "AEILNOS"

ERA_BY_WORD = {word: era for era, words in ERA_WORDS.items() for word in words}
LETTER_BY_WORD = {word: letter for letter, words in LETTER_WORDS.items() for word in words}
GRAMMAR = sorted(set(ERA_BY_WORD) | set(LETTER_BY_WORD) | set(NUMBER_WORDS) | set(TENS)) + ["[unk]"]


def _numbers(tokens: list[str], start: int) -> tuple[int | None, int]:
    """Read a spoken number (or digits) at tokens[start]; return (value, tokens consumed)."""
    word = tokens[start]
    if word.isdigit(): return int(word), 1
    if word in NUMBER_WORDS: return NUMBER_WORDS[word], 1
    if word in TENS:
        following = tokens[start + 1] if start + 1 < len(tokens) else None
        if following in ONES: return TENS[word] + NUMBER_WORDS[following], 2
        return TENS[word], 1
    return None, 0


def parse(text: str, relics: list[dict], mission_era: str | None = None) -> list[dict]:
    """Turn a transcript such as "lit b four mezzo c two" into one entry per spoken relic.

    Each entry has "heard" (e.g. "Lith B4"), "relic_id" when a single catalog relic matches,
    and "options" (candidate relic ids) when the letter was ambiguous.
    """
    ids = {(relic["era"], relic["code"]): relic["id"] for relic in relics}
    default_era = mission_era if mission_era in ERA_WORDS else None
    tokens = [token for token in re.findall(r"[a-z0-9]+", text.lower()) if token != "unk"]
    results, era, letter, index, after_era = [], default_era, None, 0, False
    while index < len(tokens):
        token = tokens[index]
        # A glued code like "b4" can come through if the recognizer ever emits one.
        glued = re.fullmatch(r"([a-z])(\d{1,2})", token)
        if glued:
            letter = glued.group(1).upper(); tokens[index:index + 1] = [glued.group(2)]; continue
        number, used = _numbers(tokens, index)
        if number is not None and (letter or after_era):
            results.append(_resolve(era, letter, number, ids) if letter else _swallowed(era, number, ids))
            era, letter, after_era = default_era, None, False
            index += used; continue
        after_era = token in ERA_BY_WORD
        if after_era: era, letter = ERA_BY_WORD[token], None
        elif token in LETTER_BY_WORD: letter = LETTER_BY_WORD[token]
        index += max(used, 1)
    return results


def _resolve(era: str | None, letter: str, number: int, ids: dict[tuple[str, str], str]) -> dict:
    eras = [era] if era else list(ERA_WORDS)
    heard = f"{era + ' ' if era else ''}{letter}{number}"
    exact = [ids[(candidate, f"{letter}{number}")] for candidate in eras if (candidate, f"{letter}{number}") in ids]
    if len(exact) == 1: return {"heard": heard, "relic_id": exact[0], "options": []}
    if exact: return {"heard": heard, "relic_id": None, "options": exact}
    similar = next((group for group in CONFUSABLE if letter in group), set())
    options = [ids[(candidate, f"{other}{number}")] for candidate in eras for other in sorted(similar - {letter})
               if (candidate, f"{other}{number}") in ids]
    if len(options) == 1: return {"heard": heard, "relic_id": options[0], "options": []}
    return {"heard": heard, "relic_id": None, "options": options}


def _swallowed(era: str, number: int, ids: dict[tuple[str, str], str]) -> dict:
    """An era followed directly by a number: the letter was lost, so offer the likely candidates."""
    matches = {code: relic_id for (candidate, code), relic_id in ids.items()
               if candidate == era and re.fullmatch(rf"[A-Z]{number}", code)}
    likely = [relic_id for code, relic_id in sorted(matches.items()) if code[0] in SWALLOWED]
    options = likely or [relic_id for _, relic_id in sorted(matches.items())]
    heard = f"{era} ?{number}"
    if len(options) == 1: return {"heard": heard, "relic_id": options[0], "options": []}
    return {"heard": heard, "relic_id": None, "options": options}


def available() -> bool:
    try: import vosk  # noqa: F401
    except ImportError: return False
    return (MODEL_PATH / "am" / "final.mdl").exists()


@lru_cache(maxsize=1)
def _model():
    import vosk
    vosk.SetLogLevel(-1)
    return vosk.Model(str(MODEL_PATH))


def recognizer(sample_rate: float):
    import vosk
    return vosk.KaldiRecognizer(_model(), sample_rate, json.dumps(GRAMMAR))
