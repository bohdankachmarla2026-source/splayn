"""Build site/js/layout-model.js: letter-pair statistics that tell wrong-layout typing from English.

When a customer forgets to switch the keyboard, "ще варіанти" arrives as "ot dfhsfynb".
The Start page converts such words back, but must leave real English words ("gear", "Bosch") alone.
It compares how typical the letter pairs of a word are in English with how typical the pairs of its
Cyrillic conversion are in Ukrainian and Russian.

Text sources (all on this Mac):
  - Bambu Studio's interface translations: Ukrainian and Russian phrases (3D-printing vocabulary),
    with the English originals;
  - /usr/share/dict/words for general English.

Run:  python3 tools/build_layout_model.py      (prints the accuracy on held-out words)
"""
from __future__ import annotations

import gettext
import json
import math
import os
import random
import re
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "site", "js", "layout-model.js")
I18N = "/Applications/BambuStudio.app/Contents/Resources/i18n"
DICT = "/usr/share/dict/words"

ALPHABETS = {
    "en": "abcdefghijklmnopqrstuvwxyz",
    "uk": "абвгґдеєжзиіїйклмнопрстуфхцчшщьюя'",
    "ru": "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
}
EDGE = "^"           # word start / end
STEP = 0.5           # quantization step of -log(p), nats
TOP_SHORT = 45       # most frequent 1–2 letter words kept per language

# The same keys on the English (QWERTY) and Ukrainian / Russian (ЙЦУКЕН) layouts.
LATIN = "qwertyuiop[]asdfghjkl;'zxcvbnm,.`\\"
UK = "йцукенгшщзхїфівапролджєячсмитьбю'ґ"
RU = "йцукенгшщзхъфывапролджэячсмитьбюёё"


def catalog(lang: str) -> dict:
    with open(os.path.join(I18N, lang, "BambuStudio.mo"), "rb") as f:
        return gettext.GNUTranslations(f)._catalog


def words(text: str, alphabet: str) -> list[str]:
    text = text.lower().replace("’", "'").replace("ʼ", "'")
    text = re.sub(r"%[-+ #0]*\d*(?:\.\d+)?[a-z]|\{[^}]*\}|<[^>]*>|&[a-z]+;", " ", text)
    found = re.findall(f"[{re.escape(alphabet)}]+", text)
    return [w.strip("'") for w in found if len(w.strip("'")) >= 1]


def corpora() -> dict[str, list[str]]:
    out = {"en": [], "uk": [], "ru": []}
    for lang in ("uk", "ru"):
        for key, value in catalog(lang).items():
            src = key[0] if isinstance(key, tuple) else key
            if not src or not value:
                continue
            out[lang] += words(value, ALPHABETS[lang])
            out["en"] += words(src, ALPHABETS["en"])
    with open(DICT, encoding="utf-8") as f:
        dict_words = [w.strip().lower() for w in f if w.strip().isalpha() and w.strip().isascii()]
    random.Random(1).shuffle(dict_words)
    out["en"] += dict_words[:60000]
    # Words customers of a print shop type in English anyway.
    out["en"] += ("pla petg abs tpu asa stl obj step gear holder stand mount bracket case box hook clip "
                  "bosch ikea xiaomi samsung iphone gopro prusa bambu ender creality lego dyson "
                  "phone car bike vase lamp toy figurine keychain cable adapter knob handle lid cap").split() * 20
    return out


def model(ws: list[str], alphabet: str) -> list[list[float]]:
    syms = EDGE + alphabet
    idx = {c: i for i, c in enumerate(syms)}
    counts = [[0.5] * len(syms) for _ in syms]   # add-0.5 smoothing
    for w in ws:
        seq = EDGE + w + EDGE
        for a, b in zip(seq, seq[1:]):
            if a in idx and b in idx:
                counts[idx[a]][idx[b]] += 1
    table = []
    for row in counts:
        total = sum(row)
        table.append([-math.log(c / total) for c in row])
    return table


def quantize(table: list[list[float]]) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    return "".join(digits[min(35, round(v / STEP))] for row in table for v in row)


def score(word: str, table: list[list[float]], alphabet: str) -> float:
    """Mean -log(p) per letter pair, word edges included. Lower = more typical."""
    syms = EDGE + alphabet
    idx = {c: i for i, c in enumerate(syms)}
    seq = EDGE + word + EDGE
    vals = [round(table[idx[a]][idx[b]] / STEP) * STEP if a in idx and b in idx else 18.0
            for a, b in zip(seq, seq[1:])]
    return sum(vals) / len(vals)


def to_cyr(latin: str, target: str) -> str:
    return latin.translate(str.maketrans(LATIN, target))


def to_latin(cyr: str, source: str) -> str:
    return "".join(LATIN[source.index(c)] if c in source else c for c in cyr)


def main() -> None:
    data = corpora()
    rnd = random.Random(7)
    held = {}
    tables = {}
    for lang, ws in data.items():
        uniq = sorted(set(ws))
        rnd.shuffle(uniq)
        test = set(uniq[:1500])
        held[lang] = [w for w in uniq[:1500] if len(w) >= 3]
        tables[lang] = model([w for w in ws if w not in test], ALPHABETS[lang])

    def margin(latin: str) -> float:
        en = score(latin, tables["en"], ALPHABETS["en"])
        uk = score(to_cyr(latin, UK), tables["uk"], ALPHABETS["uk"])
        ru = score(to_cyr(latin, RU), tables["ru"], ALPHABETS["ru"])
        return en - min(uk, ru)   # > 0: looks more like Ukrainian/Russian typed on the wrong layout

    eng = [margin(w) for w in held["en"] if w.isalpha()]
    cyr = [margin(to_latin(w, UK)) for w in held["uk"]] + [margin(to_latin(w, RU)) for w in held["ru"]]
    print(f"held-out words: english {len(eng)}, ukrainian+russian {len(cyr)}")
    best = None
    for t10 in range(0, 40):
        t = t10 / 10
        false_conv = sum(m > t for m in eng) / len(eng)
        missed = sum(m <= t for m in cyr) / len(cyr)
        cost = 4 * false_conv + missed   # breaking an English word is worse than missing one
        if best is None or cost < best[0]:
            best = (cost, t, false_conv, missed)
    _, threshold, false_conv, missed = best
    print(f"threshold {threshold}: english converted by mistake {false_conv:.1%}, wrong-layout words missed {missed:.1%}")

    # Short words decide by lists: a pair or two of letters says too little.
    short = {lang: [w for w, _ in Counter(w for w in data[lang] if 1 <= len(w) <= 2).most_common(TOP_SHORT)]
             for lang in ("uk", "ru")}
    short["en"] = ("a i to is of in be it on or by as if no at do an so we he me my up us go am "
                   "oh ok hi id tv pc mm cm").split()
    print("short uk:", " ".join(short["uk"][:25]))
    print("short ru:", " ".join(short["ru"][:25]))
    print("short en:", " ".join(short["en"][:25]))

    payload = {
        "step": STEP,
        "threshold": threshold,
        "alphabets": ALPHABETS,
        "tables": {lang: quantize(t) for lang, t in tables.items()},
        "short": short,
        "keys": {"latin": LATIN, "uk": UK, "ru": RU},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// Generated by tools/build_layout_model.py — letter-pair statistics for js/layout-fix.js.\n")
        f.write("window.LAYOUT_MODEL = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print("written", os.path.relpath(OUT), os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
