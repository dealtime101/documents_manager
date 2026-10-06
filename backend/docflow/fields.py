"""Extraction of dates, amounts and invoice numbers from text.

The text is first passed through `norm()` (accents stripped, straight apostrophes, case
preserved): every regex below, and those in the YAML files, is written without accents.
"""
import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .naming import format_date, strip_accents

MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "janv": 1, "feb": 2, "fev": 2, "fevr": 2, "mar": 3, "apr": 4, "avr": 4, "jun": 6, "jul": 7, "juil": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MON = "|".join(sorted(MONTHS, key=len, reverse=True))


def norm(text: str) -> str:
    text = strip_accents(text).replace("’", "'").replace("‘", "'")
    return text.replace(" ", " ").replace(" ", " ")


# ---------------------------------------------------------------- dates
_DATE_PATTERNS = [
    # (regex, order of the y/m/d groups); month-name groups are converted further down
    (re.compile(r"\b(\d{4})[-/](\d{2})[-/](\d{2})\b"), "ymd"),
    (re.compile(rf"\b(\d{{1,2}})(?:er|st|nd|rd|th)?\s+({_MON})\.?,?\s+(\d{{4}})\b", re.IGNORECASE), "dmy"),
    (re.compile(rf"\b({_MON})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.IGNORECASE), "mdy"),
    (re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b"), "num"),  # 16/10/2025, 3/17/2026
]
_MONTH_YEAR = re.compile(rf"\b({_MON})\.?\s+(\d{{4}})\b", re.IGNORECASE)

# The ONE definition of the words that say what a date is (find_date reads the LAST occurrence before the date).
# "\b(?:over)?due\b" and "\bdate" are anchored so that "indiviDUEl", "residUEl" or "UpDATE" do not count.
_KIND_WORDS = {
    "due": re.compile(r"echeance|\b(?:over)?due\b|a payer avant|payable avant|pay by|date limite"),
    "skip": re.compile(r"naissance|birth|effet|effective|debut|expir|valide jusqu|fin du"),
    "invoice": re.compile(r"factur|invoice|emission|emis le|issued"),  # "factur" also covers "date de la facture"
    "order": re.compile(r"command|order"),
    "label": re.compile(r"\bdate"),  # last resort: "Date", "Datee du", "Dated"
}


@dataclass
class FoundDate:
    text: str          # YYYY-MM-DD / YYYY-MM / YYYY
    confidence: float
    kind: str          # invoice | order | label | other | due | month_only


def _month(s: str) -> int:
    return MONTHS[s.lower()]


def _valid(y: int, m: int, d: int) -> bool:
    import datetime
    try:
        datetime.date(y, m, d)
        return 1990 <= y <= 2100
    except ValueError:
        return False


def find_date(text: str, prefer: str = "invoice") -> FoundDate | None:
    """Priority: billing > order > "Date" > other > due date (prefer="order" swaps the first two).
    Never the due date if anything else exists."""
    lines = text.split("\n")
    offsets, pos = [], 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln) + 1
    cands: list[tuple[int, int, str, str, bool]] = []  # (position, tier, kind, 'YYYY-MM-DD', ambiguous DD/MM vs MM/DD)
    for rx, order in _DATE_PATTERNS:
        for m in rx.finditer(text):
            g = m.groups()
            ambiguous = False
            if order == "num":
                a, b = int(g[0]), int(g[1])
                ambiguous = a <= 12 and b <= 12 and a != b  # 11/08: DD/MM or MM/DD?
                mo, d = (a, b) if b > 12 else (b, a)  # 3/17 -> MM/DD; otherwise DD/MM (Quebec convention)
                y = int(g[2])
            else:
                y, mo, d = ((int(g[0]), int(g[1]), int(g[2])) if order == "ymd" else
                            (int(g[2]), _month(g[1]), int(g[0])) if order == "dmy" else
                            (int(g[2]), _month(g[0]), int(g[1])))
            if not _valid(y, mo, d):
                continue
            li = bisect_right(offsets, m.start()) - 1  # the line holding this date, in O(log n)
            before = text[offsets[li]:m.start()]
            # label on the previous line only if the date starts its own line
            prev = lines[li - 1] if li else ""
            use_prev = bool(prev) and not before.strip() and not re.search(r"\d{4}", prev)  # label only
            ctx = (prev[-40:] + " " if use_prev else "") + before[-60:]
            ctx = ctx.lower()
            # a "due date" label closer than "invoice" wins
            last = {k: max((m.start() for m in rx.finditer(ctx)), default=-1) for k, rx in _KIND_WORDS.items()}
            # the bare word "date" is the label of LAST resort: "Invoice Date" is an invoice date, "Due Date" a due date
            specific = [k for k in last if k != "label" and last[k] >= 0]
            kind = max(specific, key=lambda k: last[k]) if specific else ("label" if last["label"] >= 0 else "other")
            tier = {"invoice": 1, "order": 2, "label": 3, "other": 4, "due": 9, "skip": 10}
            if prefer == "order":
                tier["invoice"], tier["order"] = 2, 1
            cands.append((m.start(), tier[kind], kind, format_date(y, mo, d), ambiguous))
    if cands:
        pos, _rank, kind, val, amb = min(cands, key=lambda c: (c[1], c[0]))
        conf = {"invoice": 1.0, "order": 0.9, "label": 0.8, "other": 0.65, "due": 0.4, "skip": 0.3}[kind]
        if prefer == "order" and kind in ("invoice", "order"):
            conf = 1.0 if kind == "order" else 0.9
        return FoundDate(val, min(conf, 0.7) if amb else conf, kind)  # DD/MM vs MM/DD: never auto
    month_year = _MONTH_YEAR.search(text)  # its own name: `m` above is a Match, this one may be None
    if month_year and 1990 <= int(month_year.group(2)) <= 2100:  # OCR sometimes reads 2661 for 2001
        return FoundDate(format_date(int(month_year.group(2)), _month(month_year.group(1))), 0.6, "month_only")
    return None


_PERIOD = re.compile(
    rf"\bdu\s+\d{{1,2}}(?:er)?\s+(?:{_MON})(?:\s+\d{{4}})?\s+au\s+\d{{1,2}}(?:er)?\s+({_MON})\.?\s+(\d{{4}})", re.IGNORECASE)


def find_period_month(text: str) -> FoundDate | None:
    """Statement "du 1er janvier au 31 janvier 2012" -> 2012-01 (month at the end of the period)."""
    m = _PERIOD.search(text)
    if not m or not 1990 <= int(m.group(2)) <= 2100:
        return None
    return FoundDate(format_date(int(m.group(2)), _month(m.group(1))), 0.95, "period")


def find_tax_year(text: str) -> FoundDate | None:
    """Annual tax slips (T4, Releve 1): the document date is the end of the tax year. The year printed next to
    the "Year"/"Annee" box wins (boilerplate text mentions other years, e.g. 2020 relief measures); otherwise the
    most frequent year (ties: the latest). Capped at 0.85: the user confirms it."""
    near = [int(m.group(1)) for k in re.finditer(r"\b(?:year|annee)\b", text, re.IGNORECASE)
            for m in [re.search(r"\b(20[0-3]\d)\b", text[k.end():k.end() + 120])] if m]
    years = Counter(near) or Counter(int(y) for y in re.findall(r"\b(20[0-3]\d)\b", text))
    if not years:
        return None
    best = max(years, key=lambda y: (years[y], y))
    return FoundDate(f"{best:04d}-12-31", 0.85, "tax_year")


def month_before(d: FoundDate) -> FoundDate:
    """Statement issued on 23 February for the month of January: 2012-02-23 -> 2012-01 (confidence capped: heuristic)."""
    y, mo = int(d.text[:4]), int(d.text[5:7]) if len(d.text) >= 7 else 0
    if not mo:
        return FoundDate(d.text, min(d.confidence, 0.5), d.kind)
    y, mo = (y, mo - 1) if mo > 1 else (y - 1, 12)
    return FoundDate(format_date(y, mo), min(d.confidence, 0.85), "month_before")


# ---------------------------------------------------------------- amounts
_NUM = r"\d{1,3}(?:[ ,.]\d{3})*[.,]\d{2}(?!\d)|\d+[.,]\d{2}(?!\d)"  # (?!\d): "$1,200" is not 1,20 followed by a stray 0
_AMT = re.compile(rf"(?:\$\s*[-−]?\s*({_NUM})|(?<![\d.,])({_NUM})\s*\$|\b(CAD|USD|EUR)\s*({_NUM})|(?<![\d.,])({_NUM})\s*(CAD|USD|EUR)\b)", re.IGNORECASE)  # re.I: find_amount lower-cases the lines it scans
# Whole amounts ("150 $", "$1,200"): ONLY when stuck to a currency symbol and not followed by decimals, so "1.200 $" or
# "150.5 $" (which cannot be read with certainty) stay unrecognised. Used only when a text holds no amount with cents.
_INT = r"\d{1,3}(?:[ ,]\d{3})+(?![.,]?\d)|\d+(?![.,]?\d)"
_INT_AMT = re.compile(rf"(?:\$\s*[-−]?\s*({_INT})|(?<![\d.,])({_INT})\s*\$|\b(CAD|USD|EUR)\s*({_INT})|(?<![\d.,])({_INT})\s*(CAD|USD|EUR)\b)", re.IGNORECASE)
WHOLE_AMOUNT_CONFIDENCE = 0.85  # below the 0.95 of "auto": no cents means a human confirms
_STRONG = [  # decreasing rank
    r"montant de la presente facture", r"montant total", r"total a payer", r"grand total", r"order total",
    r"amount due", r"montant a payer", r"total de la facture", r"\btotal\b",
]
# sub-totals and totals that are NOT what has to be paid (before a discount or before taxes)
_SUBTOTAL = re.compile(r"sous-total|sub-?total|avant (?:la )?remise|before discount|avant taxes?|before tax(?:es)?"
                       r"|hors taxes?|excl(?:uding|uant|\.)? tax(?:es)?")
_TAX_LINE = re.compile(r"\btps\b|\btvq\b|\bgst\b|\bqst\b|\btaxe|\btax\b")
_TAX_INCLUDED = re.compile(r"\bincl|\bttc\b|including")  # "Total taxes incluses" IS the grand total


def _not_a_total(line: str) -> bool:
    """Sub-totals and tax amounts are not the total; a total that merely says taxes are included is."""
    return bool(_SUBTOTAL.search(line) or (_TAX_LINE.search(line) and not _TAX_INCLUDED.search(line)))


@dataclass
class FoundAmount:
    value: Decimal
    currency: str
    confidence: float


def parse_number(s: str) -> Decimal | None:
    """'1 234,56' / '1,234.56' / '158,98' -> Decimal. The decimal separator is the last one, followed by 2 digits."""
    m = re.fullmatch(r"(.*?)[.,](\d{2})", s.strip())
    if not m:
        return None
    try:
        return Decimal(re.sub(r"[ ,.]", "", m.group(1)) + "." + m.group(2))
    except InvalidOperation:
        return None


def _is_negative(s: str, m: re.Match) -> bool:
    """-25,00 $ / -$25.00 / $-25.00 / (25,00 $). A dash used as a separator ("Total - 25,00 $") is NOT a minus sign:
    a sign is stuck to the amount and follows a space, a colon or an opening parenthesis."""
    before, after = s[:m.start()], s[m.end():]
    return bool(re.search(r"[-−]", m.group(0))
                or re.search(r"(^|[\s:(])[-−]$", before)
                or (before.rstrip().endswith("(") and after.lstrip().startswith(")")))


_CODE = r"(CAD|USD|EUR|US)(?![a-z0-9])"  # "US" is the usual short form of USD next to a dollar sign
_CODE_AFTER, _CODE_BEFORE = re.compile(rf"\s*{_CODE}", re.IGNORECASE), re.compile(rf"\b{_CODE}\s*$", re.IGNORECASE)  # \b: "bonus $25" is no US


def _currency(s: str, m: re.Match, code: str | None) -> str:
    """The code written in the amount ("CAD 25.00", "25.00 EUR") wins; for a bare "$" look right after it ("$25.00 USD",
    "25,00 $ US") and right before it ("USD $25.00", "US$25.00"). Nothing there: CAD, the default of the archive."""
    if not code:
        found = _CODE_AFTER.match(s, m.end()) or _CODE_BEFORE.search(s, 0, m.start())
        code = found.group(1) if found else "CAD"
    return "USD" if code.upper() == "US" else code.upper()


def _amounts_in(s: str) -> list[tuple[Decimal, str]]:
    out = []
    for m in _AMT.finditer(s):
        g = m.groups()
        num, cur = (g[0] or g[1] or g[3] or g[4]), (g[2] or g[5])
        v = parse_number(num)
        if v is not None:
            out.append((-v if _is_negative(s, m) else v, _currency(s, m, cur)))
    return out


def _whole_amounts_in(s: str) -> list[tuple[Decimal, str]]:
    out = []
    for m in _INT_AMT.finditer(s):
        g = m.groups()
        num, cur = (g[0] or g[1] or g[3] or g[4]), (g[2] or g[5])
        v = Decimal(re.sub(r"[ ,]", "", num))
        out.append((-v if _is_negative(s, m) else v, _currency(s, m, cur)))
    return out


def find_amount(text: str) -> FoundAmount | None:
    lines = text.lower().split("\n")
    best: tuple[int, int, Decimal, str, bool] | None = None  # (rank, line, value, currency, whole)
    for i, ln in enumerate(lines):
        if _not_a_total(ln):
            continue
        for rank, pat in enumerate(_STRONG):
            if re.search(pat, ln):
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                if _not_a_total(nxt):
                    nxt = ""  # the line below is a tax or a sub-total: its amount is not what the "Total" label above announces
                found, whole = _amounts_in(ln) or _amounts_in(nxt), False
                if not found:  # no amount with cents on the line or the next one: a whole amount, if any
                    found, whole = _whole_amounts_in(ln) or _whole_amounts_in(nxt), True
                if found:
                    cand = (-rank, i, *found[-1], whole)
                    # an amount with cents always beats a whole one, whatever the label rank or the line
                    if best is None or (not cand[4], cand[:2]) > (not best[4], best[:2]):
                        best = cand
                break
    if best:
        # a negative total is a credit note or a refund: a human always decides what it is, so never "sure"
        top = WHOLE_AMOUNT_CONFIDENCE if best[4] else 0.95
        return FoundAmount(best[2], best[3], top if best[2] >= 0 else 0.7)
    allv = _amounts_in(text)
    if allv:
        v, cur = max(allv)
        return FoundAmount(v, cur, 0.6)  # unlabelled amount: never auto-filed
    return None


# ---------------------------------------------------------------- items (order invoices)
_PRICE = r"(?:\$\s?[\d.,]+|[\d.,]+\s?\$)"  # "$19.99" (English layout) or "19,99 $" (French layout)
_ITEM = re.compile(rf"^(?P<title>[^\W_][^$\n]{{6,}}?)\s+\d{{1,3}}\s+{_PRICE}\s+{_PRICE}", re.MULTILINE)


def find_items(text: str) -> list[str]:
    """Item titles of an Amazon invoice: "Title  1  $19.99  $0.00 ..." (quantity then price)."""
    titles = (m.group("title").strip() for m in _ITEM.finditer(text))
    return [t for t in titles if not re.match(r"asin\b", t, re.IGNORECASE)]  # "ASIN: B0..." is not a title


def header_line(text: str) -> str:
    """First "textual" line of the document, normalised: the issuer usually opens the document.
    Only used to learn a company rule after a correction; never written into a file name."""
    for ln in norm(text).split("\n"):
        ln = re.sub(r"\s+", " ", ln).strip().lower()
        if len(ln) >= 4 and re.search(r"[a-z]{3}", ln):
            return ln[:60]
    return ""


# ---------------------------------------------------------------- invoice number
_NO = r"n(?:o|°)\.?"  # "No", "N°" (degree sign: the ordinal "º" is normalised to "o" by norm())
_INV = re.compile(
    rf"(?:\b{_NO}\s*(?:de\s*(?:la\s*)?)?facture|\bnumero\s*de\s*facture|\bfacture\s*(?:{_NO}|#)|"
    rf"\binvoice\s*(?:number|{_NO}|#)|\border\s*(?:number|{_NO}|#)|\b{_NO}\s*(?:de\s*)?commande|"
    rf"\bnumero\s*de\s*commande|\bcommande\s*(?:{_NO}|#))\s*[:#]?\s*"
    r"((?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{3,})", re.IGNORECASE)


def find_invoice_number(text: str) -> str | None:
    m = _INV.search(text)
    return m.group(1).upper() if m else None
