"""File name generation: YYYY-MM-DD - Company - Type - Detail - 12.34$.pdf"""
import datetime
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# What Windows forbids, the control characters (C0 and DEL), and every Unicode "format" character (category Cf): bidirectional
# controls such as U+202E (which can make "x.pdf" LOOK like another extension), zero-width characters and the soft hyphen, which make
# two visually identical names two different files. The Cf ranges are those of Unicode 15.1; a test compares them with the
# Python in use, so a newer Unicode that adds one is reported.
FORBIDDEN = re.compile(
    '[<>:"/\\\\|?*\x00-\x1f\x7f'
    "\xad؀-؅؜۝܏࢐-࢑࣢᠎​-‏‪-‮⁠-⁤⁦-⁯﻿"
    "￹-￻\U000110bd\U000110cd\U00013430-\U0001343f\U0001bca0-\U0001bca3\U0001d173-\U0001d17a\U000e0001\U000e0020-\U000e007f]")
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
# A name must satisfy BOTH limits; the one reached first wins. The file systems count BYTES (255 on ext4), not characters:
# 180 accented or non-Latin characters can exceed that, which is why MAX_BYTES exists.
MAX_NAME = 180  # characters: also far from the 260 of a classic Windows path
MAX_BYTES = 240  # UTF-8 bytes: ext4 allows 255 per name, minus room for a ' (999)' collision suffix
DATE_RE = re.compile(r"^([0-9]{4}(-[0-9]{2}(-[0-9]{2})?)?|XXXX)\Z")  # [0-9], not \d (Arabic-Indic, full-width... digits); \Z, not $: `$` also matches before a trailing newline
CURRENCY_RE = re.compile(r"[A-Z]{3}")
EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,10}")


def valid_date(s: str) -> bool:
    """One of the four forms (YYYY-MM-DD, YYYY-MM, YYYY, XXXX) AND a date that exists: month 1-12, a day that exists in that
    month (leap years included), year 1900-2100. Used for anything typed or answered by a model; automatic detection in a
    document is stricter still (fields.py: 1990-2100)."""
    if not DATE_RE.match(s):
        return False
    if s == "XXXX":
        return True
    year, *rest = (int(part) for part in s.split("-"))
    if not 1900 <= year <= 2100:
        return False
    try:
        datetime.date(year, rest[0] if rest else 1, rest[1] if len(rest) > 1 else 1)
    except ValueError:
        return False
    return True


# Letters that Unicode normalisation does NOT decompose into base + accent: without this they would be silently deleted by
# the character filter ("Œufs bœuf" -> "ufsBuf"). Each gets its usual plain spelling.
TRANSLITERATION = str.maketrans({
    "œ": "oe", "Œ": "Oe", "æ": "ae", "Æ": "Ae", "ß": "ss", "ẞ": "SS", "ø": "o", "Ø": "O", "ł": "l", "Ł": "L",
    "đ": "d", "Đ": "D", "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th", "ı": "i",
})


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s).translate(TRANSLITERATION) if not unicodedata.combining(c))


def sanitize(s: str) -> str:
    """Remove everything Windows forbids; never a trailing dot/space."""
    s = FORBIDDEN.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    if s.split(".")[0].rstrip().upper() in RESERVED:  # "CON .txt" too: Windows ignores the spaces before the dot
        s = "_" + s
    return s


def token(s: str) -> str:
    """'friskies chefs blend 7.5kg' -> 'FriskiesChefsBlend7.5kg' (no accents, no spaces). The letters of any alphabet are kept
    ('Газпром Нефть' -> 'ГазпромНефть'); accent marks are removed in every script (é -> e, ё -> е). What is left empty (only
    punctuation) is "unknown" for the callers: confidence 0, a person decides."""
    words = strip_accents(s).replace("’", "'").split()
    joined = "".join(w[:1].upper() + w[1:] for w in words)
    return re.sub(r"[^\w.+-]", "", joined).strip(".-_")  # \w: the letters and digits of ANY alphabet, and "_"


def format_date(year: int | None, month: int | None = None, day: int | None = None) -> str:
    if year is None:
        return "XXXX"
    if month is None:
        return f"{year:04d}"
    if day is None:
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


def format_amount(amount: Decimal, currency: str = "CAD") -> str:
    # commercial rounding (a half cent goes up, away from zero), not Decimal's default of rounding to the even cent
    try:
        if not amount.is_finite():
            raise InvalidOperation
        txt = f"{amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"
    except InvalidOperation:  # an arithmetic error is not a ValueError: callers refuse a name on ValueError only
        raise ValueError(f"invalid amount: {str(amount)[:30]!r}") from None
    return txt + ("$" if currency == "CAD" else currency)


def build_filename(date: str, company: str, doc_type: str, detail: str = "",
                   amount: Decimal | None = None, currency: str = "CAD", ext: str = ".pdf") -> str:
    """If the name exceeds MAX_NAME, the LONGEST of company / type / detail is shortened first (so a long detail goes
    first, but a very long company or type cannot break the limit either). Date and amount are never cut."""
    if not valid_date(date):
        raise ValueError(f"invalid date: {date!r}")
    if not EXT_RE.fullmatch(ext):  # the extension is joined as-is: it must not carry a separator or a trailing dot
        raise ValueError(f"invalid extension: {ext!r}")
    if amount is not None and not CURRENCY_RE.fullmatch(currency):
        raise ValueError(f"invalid currency: {currency!r}")
    tail = format_amount(amount, currency) if amount is not None else ""
    parts = {"company": sanitize(company), "type": sanitize(doc_type), "detail": sanitize(detail)}
    if not parts["company"] or not parts["type"]:  # only forbidden characters or spaces: '2024-01-01 -  - Facture.pdf' is no name
        raise ValueError("company and type are required (nothing is left of one of them after cleaning)")

    def join() -> str:
        return " - ".join([date, parts["company"], parts["type"], *(p for p in (parts["detail"], tail) if p)]) + ext

    name = join()
    for _ in range(MAX_NAME * 4):  # every pass removes at least one character, so this always ends well before the cap
        excess_chars = len(name) - MAX_NAME
        excess_bytes = len(name.encode("utf-8")) - MAX_BYTES  # file systems limit BYTES (255 on ext4), not characters
        if excess_chars <= 0 and excess_bytes <= 0:
            break
        longest = max(parts, key=lambda k: len(parts[k].encode("utf-8")))
        cut = max(1, excess_chars, -(-excess_bytes // 4))  # a character is 1 to 4 bytes: cut a safe minimum, repeat
        keep = max(1, len(parts[longest]) - cut)
        parts[longest] = parts[longest][:keep].rstrip(" .-") or parts[longest][:1]  # slicing str never splits a character
        name = join()
    if len(name) > MAX_NAME or len(name.encode("utf-8")) > MAX_BYTES:
        # only the parts that are never cut are left (date, amount, extension). A valid date, extension, currency and amount
        # cannot reach this; if one ever does, a refused name is better than a file that cannot be written (ENAMETOOLONG)
        raise ValueError(f"the file name is too long even without its optional parts: {len(name)} characters")
    return name
