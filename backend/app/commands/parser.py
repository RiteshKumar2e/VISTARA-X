"""Deterministic command parser for English, romanised Hindi (Hinglish) and Hindi.

Safety-critical decisions never depend on a learned model: the intent comes from fixed
keyword rules and the destination only from the scenario's configured places (or
explicit coordinates). Unknown or ambiguous destinations produce a clarification
request, never a guessed location. A stop word anywhere in the text wins over every
other reading of it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

DEVANAGARI = re.compile(r"[ऀ-ॿ]")

# Keyword sets. Latin entries match whole words; Devanagari entries match substrings.
STOP = ["stop", "halt", "emergency", "freeze", "abort", "ruko", "rukko", "rukiye", "roko", "band karo",
        "bandh karo", "thamo", "ruk jao", "रुको", "रुकिए", "रुकें", "रुक जाओ", "रोको", "बंद करो", "थमो"]
PAUSE = ["pause", "hold on", "wait", "thoda ruko", "thodi der ruko", "थोड़ा रुको", "थोड़ी देर रुको", "ठहरो", "पॉज़", "पॉज"]
RESUME = ["resume", "continue", "carry on", "keep going", "go on", "phir se chalo", "fir se chalo", "aage badho",
          "chalu karo", "jari rakho", "jaari rakho", "फिर से चलो", "आगे बढ़ो", "आगे बढ़ो", "जारी रखो", "चालू करो"]
RETURN = ["return", "go back", "come back", "head back", "wapas", "vapas", "waapas", "वापस", "लौटो", "लौट जाओ"]
NAV_VERBS = ["go", "take", "move", "navigate", "drive", "head", "bring", "find", "route", "reach", "le jao", "le chalo",
             "jao", "chalo", "pahuncho", "pahunchao", "ले जाओ", "ले चलो", "जाओ", "चलो", "पहुँचो", "पहुंचो", "पहुँचाओ",
             "पहुंचाओ", "तक", "tak"]
CAREFUL = ["safe", "safely", "safest", "carefully", "careful", "surakshit", "dhyan se", "dhyaan se", "savdhani",
           "सुरक्षित", "ध्यान से", "सावधानी"]
SLOW = ["slow", "slowly", "dheere", "dhire", "dheeme", "धीरे", "धीमे"]
HINGLISH_MARKERS = {"ko", "tak", "jao", "chalo", "ruko", "roko", "karo", "wapas", "vapas", "phir", "fir", "aage",
                    "badho", "kahan", "kidhar", "thoda", "pahuncho", "dheere", "jaldi", "rakho", "chalu"}

COORDS = re.compile(r"(?:x\s*=?\s*)?(-?\d+(?:\.\d+)?)\s*(?:,|and|aur|और|\s)\s*(?:y\s*=?\s*)?(-?\d+(?:\.\d+)?)")


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[.,!?;:\"'()\[\]{}।॥|]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _has(text: str, words) -> list[str]:
    found = []
    for w in words:
        if DEVANAGARI.search(w):
            if w in text:
                found.append(w)
        elif re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", text):
            found.append(w)
    return found


def detect_language(text: str) -> str:
    """'hi' (Devanagari), 'hi-Latn' (romanised Hindi) or 'en'. Script and keyword based."""
    if DEVANAGARI.search(text):
        return "hi"
    if set(normalise(text).split()) & HINGLISH_MARKERS:
        return "hi-Latn"
    return "en"


@dataclass
class ParsedCommand:
    intent: str  # navigate | return_home | stop | pause | resume | unknown
    language: str
    destination: dict | None = None  # {"key", "name", "name_hi", "x", "y"} or {"x", "y"} for coordinates
    constraints: dict = field(default_factory=dict)
    issue: str | None = None  # ambiguous | unknown_destination | no_destination | not_understood | empty
    candidates: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)  # keywords that decided the intent (for transparency)


def parse(text: str, places) -> ParsedCommand:
    """``places`` are the scenario's Place objects."""
    lang = detect_language(text)
    t = normalise(text)
    if not t:
        return ParsedCommand("unknown", lang, issue="empty")

    stop = _has(t, STOP)
    pause = _has(t, PAUSE)
    # "thoda ruko" contains "ruko": an explicit pause phrase is a pause; any other stop
    # word is a stop. When unsure, stop (the safe reading).
    if pause and not [w for w in stop if not any(w in p for p in pause)]:
        return ParsedCommand("pause", lang, matched=pause)
    if stop:
        return ParsedCommand("stop", lang, matched=stop)

    constraints = {}
    careful = _has(t, CAREFUL)
    slow = _has(t, SLOW)
    if careful:
        constraints["careful"] = True
    if slow:
        constraints["slow"] = True

    # Destination: configured place names, longest alias first so "storage room" beats "storage".
    hits = {}
    for p in places:
        for alias in sorted(p.aliases, key=len, reverse=True):
            a = alias.lower()
            if (a in t) if DEVANAGARI.search(a) else re.search(rf"(?<![a-z]){re.escape(a)}(?![a-z])", t):
                hits.setdefault(p.key, (p, alias))
                break
    returning = _has(t, RETURN)
    resume = _has(t, RESUME)
    nav = _has(t, NAV_VERBS)

    if returning and (not hits or set(hits) == {"start"}):
        start = next((p for p in places if p.key == "start"), None)
        if start:
            return ParsedCommand("return_home", lang, _place(start), constraints, matched=returning)
    if len(hits) > 1:
        names = [h[0].name for h in hits.values()]
        return ParsedCommand("navigate", lang, None, constraints, issue="ambiguous", candidates=names,
                             matched=[h[1] for h in hits.values()])
    if len(hits) == 1:
        p, alias = next(iter(hits.values()))
        return ParsedCommand("navigate", lang, _place(p), constraints, matched=[alias, *nav])

    coords = COORDS.search(t) if nav else None
    if coords:
        x, y = float(coords.group(1)), float(coords.group(2))
        return ParsedCommand("navigate", lang, {"x": x, "y": y}, constraints, matched=[coords.group(0), *nav])
    if resume:
        return ParsedCommand("resume", lang, matched=resume)
    if nav:
        # A movement request without a known place: ask, never guess.
        unknown = bool(set(t.split()) - _function_words())
        return ParsedCommand("navigate", lang, None, constraints,
                             issue="unknown_destination" if unknown else "no_destination", matched=nav)
    return ParsedCommand("unknown", lang, issue="not_understood")


def _place(p) -> dict:
    return {"key": p.key, "name": p.name, "name_hi": p.name_hi, "x": p.x, "y": p.y}


def _function_words() -> set[str]:
    return {
        "go", "take", "move", "navigate", "drive", "head", "bring", "find", "route", "reach", "to", "the", "a", "an",
        "robot", "please", "me", "us", "now", "safe", "safely", "safest", "carefully", "slowly", "slow", "le", "jao",
        "chalo", "ko", "tak", "par", "pe", "se", "please", "kripya", "abhi", "रोबोट", "को", "तक", "ले", "जाओ", "चलो",
        "कृपया", "पर", "से", "मुझे", "hamein", "mujhe",
    }
