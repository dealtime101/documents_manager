from decimal import Decimal

import pytest
from docflow.fields import (
    find_amount,
    find_date,
    find_invoice_number,
    norm,
    parse_number,
)
from docflow.naming import build_filename, sanitize, token


def test_sanitize_windows():
    assert sanitize('a<b>c:d"e/f\\g|h?i*j') == "abcdefghij"
    assert sanitize("nom. ") == "nom"
    assert sanitize("CON") == "_CON"


def test_token():
    assert token("friskies chefs blend 7.5kg") == "FriskiesChefsBlend7.5kg"
    assert token("Employé Seulement") == "EmployeSeulement"


def test_build_filename_examples():
    assert build_filename("2025-10-07", "Hydro-Quebec", "FactureElectricite", "", Decimal("158.98")) == \
        "2025-10-07 - Hydro-Quebec - FactureElectricite - 158.98$.pdf"
    assert build_filename("2025-11-30", "Amazon", "FactureNourritureChat", "FriskiesChefsBlend7.5kg", Decimal("25.55")) == \
        "2025-11-30 - Amazon - FactureNourritureChat - FriskiesChefsBlend7.5kg - 25.55$.pdf"
    assert build_filename("XXXX", "CroixBleueMedavie", "CarteAssuranceSante", "Identification") == \
        "XXXX - CroixBleueMedavie - CarteAssuranceSante - Identification.pdf"


@pytest.mark.parametrize("company,doc_type,detail", [
    ("C" * 300, "Facture", "detail"), ("Hydro", "T" * 300, ""), ("C" * 250, "T" * 250, "D" * 250), ("C" * 179, "T", "D"),
])
def test_build_filename_never_exceeds_max_name_whatever_part_is_too_long(company, doc_type, detail):
    from docflow.naming import MAX_NAME
    n = build_filename("2025-10-07", company, doc_type, detail, Decimal("12.5"))
    assert len(n) <= MAX_NAME
    assert n.startswith("2025-10-07 - ") and n.endswith(" - 12.50$.pdf")      # date and amount are never cut
    assert not any(part != part.strip(" .") for part in n[:-4].split(" - "))   # no part ends with a dot/space


@pytest.mark.parametrize("company,doc_type,detail", [
    ("É" * 90, "é" * 90, "è" * 90),                      # 2 bytes per character: 180 characters would be ~330 bytes
    ("😀" * 60, "Facture", "x"),                          # 4 bytes per character
    ("日本語" * 40, "Facture", "詳細" * 40),
])
def test_build_filename_fits_the_byte_limit_of_file_systems_without_cutting_a_character(company, doc_type, detail):
    from docflow.naming import MAX_BYTES, MAX_NAME
    n = build_filename("2025-10-07", company, doc_type, detail, Decimal("12.5"))
    assert len(n) <= MAX_NAME and len(n.encode("utf-8")) <= MAX_BYTES <= 255 - len(" (999)")   # room for a ' (2)' suffix
    assert n.startswith("2025-10-07 - ") and n.endswith(" - 12.50$.pdf")      # date, amount and extension are kept
    assert n.encode("utf-8").decode("utf-8") == n                              # no half character


@pytest.mark.parametrize("date", ["2024-01-01\n", "2024-01-01\r\n", "2024\n", "XXXX\n", " 2024-01-01", "2024-01-01 ", "2024-01-01\t",
                                  "2024-1-1", "2024-01-011", "20240101", "XXXXX", "xxxx", ""])
def test_a_date_with_anything_around_it_is_not_a_date(date):
    from docflow.analyze import Analysis, parse_llm_json
    from docflow.naming import DATE_RE
    assert DATE_RE.match(date) is None                                       # `$` used to accept a trailing newline
    with pytest.raises(ValueError, match="invalid date"):
        build_filename(date, "Hydro", "Facture")                             # so a control character reached the file name
    with pytest.raises(ValueError):
        Analysis(date=date)
    answer = parse_llm_json('{"date": %s, "company": "A", "document_type": "B", "confidence": 0.9}'.replace("%s", __import__("json").dumps(date)))
    assert answer.date == "XXXX" and answer.conf["date"] == 0.0              # a model's odd date is dropped, not kept


@pytest.mark.parametrize("amount,expected", [
    ("12.345", "12.35$"), ("0.125", "0.13$"), ("2.675", "2.68$"), ("1.005", "1.01$"), ("0.005", "0.01$"),   # half goes UP
    ("12.344", "12.34$"), ("12.346", "12.35$"), ("0.004", "0.00$"),                                            # not at the half
    ("-12.345", "-12.35$"), ("-0.005", "-0.01$"),                                                              # away from zero
    ("12.34", "12.34$"), ("12.3", "12.30$"), ("12", "12.00$"), ("0", "0.00$"), ("158.98", "158.98$"),
    ("1234567.895", "1234567.90$"),
])
def test_amounts_are_rounded_the_commercial_way_half_up_not_to_even(amount, expected):
    from docflow.naming import format_amount
    assert format_amount(Decimal(amount)) == expected


def test_a_file_name_carries_the_commercially_rounded_amount():
    assert build_filename("2025-10-07", "Hydro", "Facture", "", Decimal("12.345")).endswith(" - 12.35$.pdf")


@pytest.mark.parametrize("company,doc_type", [
    ("", "Facture"), (" ", "Facture"), ("///", "Facture"), ("<>:\"|?*", "Facture"), ("...", "Facture"), (" . ", "Facture"),
    ("Hydro", ""), ("Hydro", "  "), ("Hydro", "\\\\"), ("Hydro", ".."), ("", ""), ("\x00\x1f", "Facture"),
])
def test_a_company_or_type_that_is_empty_after_cleaning_is_refused_not_left_as_an_empty_segment(company, doc_type):
    with pytest.raises(ValueError, match="company and type"):
        build_filename("2024-01-01", company, doc_type)                      # it used to return '2024-01-01 -  - Facture.pdf'


def test_an_empty_detail_is_still_fine_and_leaves_no_empty_segment():
    assert build_filename("2024-01-01", "Hydro", "Facture", detail="///") == "2024-01-01 - Hydro - Facture.pdf"
    assert " -  - " not in build_filename("2024-01-01", "Hydro", "Facture", "", Decimal(5))


@pytest.mark.parametrize("text,expected", [
    ("Œufs bœuf", "OeufsBoeuf"), ("Æon Flux", "AeonFlux"), ("Straße", "Strasse"), ("STRAẞE", "STRASSE"),
    ("Søren Ørsted", "SorenOrsted"), ("Łódź", "Lodz"), ("Đà Nẵng", "DaNang"), ("Þór Ðuric", "ThorDuric"),
    ("ĳsselmeer", "Ijsselmeer"), ("ﬁnance", "Finance"), ("ıstanbul", "Istanbul"),                  # ligatures and dotless i
    ("café Noël Hélène Zoë", "CafeNoelHeleneZoe"), ("garage tremblay & fils", "GarageTremblayFils"),  # unchanged behaviour
])
def test_special_letters_are_transliterated_not_deleted(text, expected):
    from docflow.naming import token
    assert token(text) == expected


def test_special_letters_also_match_their_plain_spelling_when_reading_text():
    from docflow.naming import strip_accents
    assert strip_accents("Bœuf haché, Œuvre, Æsir, Straße, Ørsted") == "Boeuf hache, Oeuvre, Aesir, Strasse, Orsted"
    assert strip_accents("") == "" and strip_accents("plain ascii 123") == "plain ascii 123"


@pytest.mark.parametrize("date", [
    "2024-13-45", "2024-13-01", "2024-00-10", "2024-01-00", "2024-01-32", "2024-02-30", "2023-02-29", "2100-02-29",   # impossible
    "2024-04-31", "2024-06-31", "2024-13", "2024-00",                                                                # month, day
    "1899-12-31", "1899", "0000", "0000-01-01", "2101", "2101-01-01",                                                # absurd years
])
def test_a_date_that_does_not_exist_is_refused_everywhere(date):
    import json

    from docflow.analyze import Analysis, parse_llm_json
    from docflow.naming import valid_date
    assert valid_date(date) is False
    with pytest.raises(ValueError, match="invalid date"):
        build_filename(date, "Hydro", "Facture")
    with pytest.raises(ValueError):
        Analysis(date=date)
    answer = parse_llm_json('{"date": %s, "company": "A", "document_type": "B", "confidence": 0.9}'.replace("%s", json.dumps(date)))
    assert answer.date == "XXXX" and answer.conf["date"] == 0.0                # a model's impossible date is dropped


@pytest.mark.parametrize("date", ["2024-02-29", "2000-02-29", "1900-12-31", "1900", "1900-01", "2100-12-31", "2100", "2024-12",
                                  "2025-10-07", "1975-06-15", "XXXX"])
def test_real_dates_including_leap_days_and_old_documents_are_accepted(date):
    from docflow.analyze import Analysis
    from docflow.naming import valid_date
    assert valid_date(date) is True
    assert Analysis(date=date).date == date
    assert build_filename(date, "Hydro", "Facture").startswith(date + " - Hydro")


@pytest.mark.parametrize("date", ["2024-01-01", "2024-01", "2024", "XXXX"])
def test_the_four_accepted_date_forms_still_work(date):
    from docflow.naming import DATE_RE
    assert DATE_RE.match(date)
    assert build_filename(date, "Hydro", "Facture").startswith(date + " - Hydro")


@pytest.mark.parametrize("currency", ["A/B", "..", "", "cad", "CA", "CAD$", "C:D", "X\\Y"])
def test_build_filename_refuses_a_currency_that_could_add_forbidden_characters(currency):
    with pytest.raises(ValueError, match="currency"):
        build_filename("2025-10-07", "Hydro", "Facture", "", Decimal(1), currency)


@pytest.mark.parametrize("ext", ["/x", ".pdf.", "pdf", "..", ".p/df", ".pdf ", "", ".", ".a\\b", "." + "x" * 11])
def test_build_filename_refuses_an_extension_that_is_not_a_plain_dot_extension(ext):
    with pytest.raises(ValueError, match="extension"):
        build_filename("2025-10-07", "Hydro", "Facture", "", None, "CAD", ext)


def test_build_filename_accepts_normal_currencies_and_extensions():
    assert build_filename("2025-10-07", "Hydro", "Facture", "", Decimal(1), "USD", ".PDF") == \
        "2025-10-07 - Hydro - Facture - 1.00USD.PDF"
    assert build_filename("2025-10-07", "Hydro", "Facture", "", None, "CAD", ".pdf").endswith("Facture.pdf")


def test_build_filename_rejects_bad_date_and_truncates_detail():
    with pytest.raises(ValueError):
        build_filename("07/10/2025", "A", "B")
    n = build_filename("2025-01-01", "A", "B", "x" * 400, Decimal(1))
    assert len(n) <= 180 and n.endswith(" - 1.00$.pdf")


@pytest.mark.parametrize("text,expected", [
    ("Facture d'électricité du 7 octobre 2025", "2025-10-07"),
    ("Facture d’électricité du 9 mars 2026", "2026-03-09"),
    ("Date de facturation: 2025-11-30", "2025-11-30"),
    ("Order placed: November 30, 2025", "2025-11-30"),
    ("1er février 2024", "2024-02-01"),
])
def test_find_date(text, expected):
    assert find_date(norm(text)).text == expected


def test_due_date_never_beats_invoice_date():
    t = norm("Date d'échéance : 15 novembre 2025\nDate de facturation : 7 octobre 2025")
    assert find_date(t).text == "2025-10-07"
    assert find_date(norm("Date d'échéance : 15 novembre 2025")).kind == "due"


def test_invoice_date_beats_order_date():
    t = norm("Date de commande: 1 mars 2025\nDate de facture: 5 mars 2025")
    assert find_date(t).text == "2025-03-05"


def test_english_labels_ending_with_the_word_date_keep_their_real_kind():
    d = find_date(norm("Invoice Date: 2025-01-05"))
    assert (d.text, d.kind, d.confidence) == ("2025-01-05", "invoice", 1.0)
    assert find_date(norm("Due Date: 2025-02-01")).kind == "due"
    assert find_date(norm("Order Date: 2025-01-02"), prefer="order").confidence == 1.0
    d = find_date(norm("Invoice Date: 2025-01-05\nDue Date: 2025-02-01"))
    assert d.text == "2025-01-05"                                   # the due date never wins over the invoice date
    assert find_date(norm("Date: 2025-01-05")).kind == "label"      # a bare "Date" is still just a label


def test_a_due_date_never_beats_an_unlabelled_date():
    d = find_date(norm("Due date: 2025-11-01\nDocument emis a Montreal le 12 mars 2025"))
    assert d.text == "2025-03-12" and d.kind != "due"                # the unlabelled date wins over the deadline
    only = find_date(norm("Due date: 2025-11-01"))
    assert (only.kind, only.confidence) == ("due", 0.4)              # alone it is still a due date, at low confidence


def test_numeric_dates_and_ambiguity():
    d = find_date(norm("Date: 16/10/2025"))          # 16 > 12: unambiguous
    assert (d.text, d.confidence) == ("2025-10-16", 0.8)
    d = find_date(norm("Date: 3/17/2026"))           # MM/DD/YYYY
    assert d.text == "2026-03-17"
    d = find_date(norm("Date: 11/08/2025"))          # ambiguous: DD/MM kept, never auto
    assert d.text == "2025-08-11" and d.confidence <= 0.7


def test_birth_and_effective_dates_never_win():
    t = norm("Date de naissance : 24/02/1987\nAttestation du 16/10/2025")
    assert find_date(t).text == "2025-10-16"
    t = norm("Date d'effet : 2023/01/01\n25 mars 2025")
    assert find_date(t).text == "2025-03-25"


def test_month_only_rejects_ocr_garbage_year():
    assert find_date(norm("Verrazzano avril 2661")) is None
    assert find_date(norm("Verrazzano avril 2001")).text == "2001-04"


def test_tax_year_end_is_the_most_frequent_year_and_never_auto():
    from docflow.fields import find_tax_year
    d = find_tax_year(norm("T4 Year 2024 Statement of Remuneration Paid 2024 box 14 ... form version 2020"))
    assert (d.text, d.confidence) == ("2024-12-31", 0.85)
    # boilerplate about 2020 is more frequent, but the year next to the "Year" box wins
    boiler = "T4 Year Statement of Remuneration Paid\nUBISOFT INC 2025 Z\n" + "57 - Employment Income - May 9, 2020\n" * 4
    assert find_tax_year(norm(boiler)).text == "2025-12-31"
    assert find_tax_year(norm("RELEVE 1\nAnnee Code du releve\n2024 R de")).text == "2024-12-31"
    assert find_tax_year("2019 and 2023 once each").text == "2023-12-31"   # tie: the latest
    assert find_tax_year("no year here") is None


def test_period_month_and_month_before():
    from docflow.fields import FoundDate, find_period_month, month_before
    assert find_period_month(norm("Pour la période du 1er janvier  au 31 janvier 2012")).text == "2012-01"
    assert find_period_month(norm("du 24 décembre 2011 au 23 janvier 2012")).text == "2012-01"
    assert find_period_month("pas de période ici") is None
    assert find_period_month("du 1 janvier au 31 janvier 2661") is None          # absurd year (OCR)
    m = month_before(FoundDate("2012-02-23", 1.0, "invoice"))
    assert (m.text, m.confidence) == ("2012-01", 0.85)                              # heuristic: never auto
    assert month_before(FoundDate("2013-01-25", 1.0, "x")).text == "2012-12"        # year rollover
    assert month_before(FoundDate("2012", 1.0, "x")).confidence <= 0.5              # date too partial


def test_no_date_and_invalid_date():
    assert find_date("aucune date ici") is None
    assert find_date("31 février 2025") is None


@pytest.mark.parametrize("s,v", [("158,98", "158.98"), ("1 234,56", "1234.56"), ("1,234.56", "1234.56"), ("25.55", "25.55")])
def test_parse_number(s, v):
    assert parse_number(s) == Decimal(v)


@pytest.mark.parametrize("text", [
    "Contrat individuel\n12 mars 2025", "Prime individuelle 12 mars 2025", "Montant residuel au 12 mars 2025",
])
def test_words_that_merely_contain_due_do_not_make_a_date_a_due_date(text):
    assert find_date(norm(text)).kind == "other"


@pytest.mark.parametrize("text,kind", [
    ("Date d'échéance : 12 mars 2025", "due"), ("Payment due 12 mars 2025", "due"), ("Facture overdue 12 mars 2025", "due"),
    ("Date: 12 mars 2025", "label"), ("Datee du 12 mars 2025", "label"), ("Dated 12 mars 2025", "label"),
    ("Update 12 mars 2025", "other"), ("Mise a jour 12 mars 2025", "other"),
    ("Facture du 12 mars 2025", "invoice"), ("Date de la facture : 12 mars 2025", "invoice"),
    ("Bon de commande 12 mars 2025", "order"),
])
def test_date_label_words_keep_their_meaning(text, kind):
    assert find_date(norm(text)).kind == kind


def test_order_items_are_found_with_the_dollar_sign_before_or_after_the_price():
    from docflow.fields import find_items
    english = "Wireless Mouse Logitech M185  1  $19.99  $0.00  $19.99"
    french = "Souris sans fil Logitech M185  1  19,99 $  0,00 $  19,99 $"
    mixed = "Cable HDMI deux metres  2  8,50 $  $17.00"
    assert find_items(english) == ["Wireless Mouse Logitech M185"]
    assert find_items(french) == ["Souris sans fil Logitech M185"]
    assert find_items(mixed) == ["Cable HDMI deux metres"]
    assert find_items(f"{english}\n{french}\nASIN: B0123456789  1  $5.00  $5.00") == [
        "Wireless Mouse Logitech M185", "Souris sans fil Logitech M185"]            # the ASIN line is still not an item


def test_text_that_only_looks_a_little_like_an_item_row_is_not_one():
    from docflow.fields import find_items
    assert find_items("Total de la commande  3  articles") == []                    # no prices
    assert find_items("Livraison gratuite pour 2 jours 19,99") == []                # no currency sign


def test_find_date_stays_fast_on_a_long_statement_with_a_date_on_every_line():
    import time
    text = "\n".join(f"2025-{(i % 12) + 1:02d}-{(i % 28) + 1:02d} operation {i} 12,34 $" for i in range(8000))
    start = time.perf_counter()
    d = find_date(text)
    elapsed = time.perf_counter() - start
    assert (d.text, d.kind) == ("2025-01-01", "other")
    assert elapsed < 1.5, f"{elapsed:.2f}s: the cost grows with lines x dates"   # was ~5.5 s; linear is a few tenths


def test_the_date_label_words_have_one_source_that_find_date_really_uses(monkeypatch):
    import re

    from docflow import fields
    assert find_date("zzz 12 mars 2025").kind == "other"
    monkeypatch.setitem(fields._KIND_WORDS, "invoice", re.compile("zzz"))   # change the one definition...
    assert find_date("zzz 12 mars 2025").kind == "invoice"                   # ...and the behaviour follows


@pytest.mark.parametrize("text,expected", [
    ("N° de facture : 12345", "12345"), ("N° de facture: 12345", "12345"), ("n° de commande : 98765", "98765"),
    ("N° facture : 12345", "12345"), ("N° de la facture : 12345", "12345"), ("N° de facture ABC-1234", "ABC-1234"),
    ("N° de commande 111-222", "111-222"), ("Invoice N° 4567", "4567"), ("Order n° 8888", "8888"),
    ("Nº de facture 12345", "12345"),                          # the ordinal sign is normalised to "No"
    ("No de facture : 12345", "12345"), ("Numéro de facture : 12345", "12345"), ("Facture n° 12345", "12345"),
    ("Commande no 5555", "5555"), ("Invoice number: INV-2025-7", "INV-2025-7"),
])
def test_french_and_english_invoice_and_order_number_labels_are_recognised(text, expected):
    assert find_invoice_number(norm(text)) == expected      # the analyzer always normalises first


@pytest.mark.parametrize("text", [
    "Casino de facture 12345",        # "no" inside a word is not the label
    "Annotation de facture 12345",
    "N° de facture : ",                # label without a number
    "N° de facture : abc",             # a number must contain a digit
    "Page n° 12 de 30",                # not an invoice label
])
def test_labels_inside_words_or_without_a_real_number_are_not_invoice_numbers(text):
    assert find_invoice_number(norm(text)) is None


@pytest.mark.parametrize("text,value,currency", [
    ("Total : 150 $", "150", "CAD"),
    ("Total: $1,200", "1200", "CAD"),
    ("TOTAL 1 200 $", "1200", "CAD"),
    ("Montant total : CAD 75", "75", "CAD"),
    ("Order total 99 USD", "99", "USD"),
    ("Devis\nTotal\n$ 2 500", "2500", "CAD"),                  # the amount on the line after the label
])
def test_a_whole_amount_next_to_a_currency_is_recognised_but_never_trusted_for_auto(text, value, currency):
    a = find_amount(text)
    assert a is not None and (a.value, a.currency) == (Decimal(value), currency)
    assert a.confidence < 0.95                                # no cents: a human confirms, the engine never files it alone


def test_a_whole_amount_never_overrides_an_amount_with_cents():
    a = find_amount("Sous-total 100 $\nTotal a payer 172,46 $\nAcompte 150 $")
    assert (a.value, a.confidence) == (Decimal("172.46"), 0.95)


@pytest.mark.parametrize("text", [
    "Total 1.200 $",            # 1.200: one thousand two hundred or 1.2 dollars? not guessed
    "Total 150.5 $",            # one decimal digit: not a clean amount
    "Total 150",                # no currency symbol: could be anything
    "Année 2025 et page 3",     # numbers without a currency
    "Tel. 514 555 1234 total",  # digits next to no symbol
])
def test_ambiguous_or_symbol_less_numbers_are_still_not_amounts(text):
    assert find_amount(text) is None


def test_a_negative_whole_amount_is_a_credit_for_a_human_to_judge():
    a = find_amount("Total: -150 $")
    assert (a.value, a.confidence) == (Decimal(-150), 0.7)


def test_find_amount_labeled_beats_larger_unlabeled():
    t = norm("Abonnement 900,00 $\nMontant de la présente facture : 158,98 $")
    a = find_amount(t)
    assert (a.value, a.confidence) == (Decimal("158.98"), 0.95)


def test_find_amount_ignores_subtotal_and_tax():
    t = norm("Sous-total 100,00 $\nTPS 5,00 $\nTVQ 9,98 $\nTotal 114,98 $")
    assert find_amount(t).value == Decimal("114.98")


@pytest.mark.parametrize("line", [
    "Total taxes incluses 114,98 $", "Montant total incluant les taxes : 114,98 $", "Total incl. tax $114.98",
    "Grand total (tax included) $114.98", "Total TTC 114,98 $",
])
def test_totals_that_mention_taxes_are_real_totals(line):
    a = find_amount(norm("Sous-total 100,00 $\nTPS 5,00 $\nTVQ 9,98 $\n" + line))
    assert (a.value, a.confidence) == (Decimal("114.98"), 0.95)


@pytest.mark.parametrize("text", [
    "Sous-total 120,00 $\nRemise -20,00 $\nTotal taxes incluses : 100,00 $\nTotal avant remise 120,00 $",  # finding DOC468.204
    "Total taxes incluses 114,98 $\nTotal hors taxes 100,00 $",
    "Total before tax $100.00\nGrand total (tax included) $114.98\nTotal before discount $130.00",
])
def test_the_payable_total_wins_over_pre_discount_and_pre_tax_totals(text):
    a = find_amount(norm(text))
    assert a.value in (Decimal("100.00"), Decimal("114.98")) and a.confidence == 0.95
    assert a.value == (Decimal("114.98") if "114" in text else Decimal("100.00"))


def test_the_tax_amount_line_itself_is_still_excluded():
    a = find_amount(norm("Sous-total 100,00 $\nTotal des taxes 14,98 $\nTotal 114,98 $"))
    assert a.value == Decimal("114.98")


def test_a_labelled_total_in_a_currency_code_keeps_its_priority_and_confidence():
    a = find_amount(norm("Total 100.00 USD\nShipping insurance 250.00 USD"))   # the fallback would pick 250
    assert (a.value, a.currency, a.confidence) == (Decimal("100.00"), "USD", 0.95)
    a = find_amount(norm("Montant total : 80,00 cad"))                          # lower/mixed case codes too
    assert (a.value, a.currency, a.confidence) == (Decimal("80.00"), "CAD", 0.95)


@pytest.mark.parametrize("line", ["Total -25,00 $", "Montant total : -25.00 $", "Total -$25.00", "Total $-25.00",
                                  "Montant total (25,00 $)", "Total −25,00 $"])           # incl. the Unicode minus sign
def test_negative_amounts_keep_their_sign_and_never_pass_for_sure(line):
    a = find_amount(norm(line))
    assert a.value == Decimal("-25.00")                          # a credit note is not a 25.00 invoice
    assert a.confidence <= 0.7                                   # so a human always decides


@pytest.mark.parametrize("line", ["Total - 25,00 $", "Total: 25,00 $ - TPS incluse", "Facture 2025-10 total 25,00 $"])
def test_a_dash_used_as_a_separator_is_not_a_minus_sign(line):
    a = find_amount(norm(line))
    assert a.value == Decimal("25.00") and a.confidence == 0.95


def test_find_amount_unlabeled_low_confidence_and_none():
    assert find_amount("prix 12,50 $").confidence < 0.8
    assert find_amount("rien") is None


def test_find_amount_next_line_and_usd():
    assert find_amount("grand total\n$25.55").value == Decimal("25.55")
    a = find_amount("amount due: USD 10.00")
    assert (a.value, a.currency) == (Decimal("10.00"), "USD")


def test_invoice_number():
    assert find_invoice_number(norm("Numéro de facture : INV-2025-0042")) == "INV-2025-0042"
    assert find_invoice_number("invoice number is here") is None


def test_a_currency_code_next_to_the_dollar_sign_sets_the_currency():
    # DOC474.36: "$25.00 USD" / "25,00 $ US" / "US$25.00" were all filed as CAD
    from decimal import Decimal

    from docflow.fields import find_amount
    for text, cur, value in [("Total: $25.00 USD", "USD", "25.00"), ("Total 25,00 $ US", "USD", "25.00"),
                             ("Total US$25.00", "USD", "25.00"), ("Total USD $25.00", "USD", "25.00"),
                             ("Total 150 $ EUR", "EUR", "150"), ("Total: 25.00 $ CAD", "CAD", "25.00"),
                             ("Total $25.00", "CAD", "25.00"), ("Total $25.00 plus the fee", "CAD", "25.00")]:
        got = find_amount(text)
        assert got is not None and (got.currency, got.value) == (cur, Decimal(value)), text
    for text in ("Total bonus $25.00", "Total plus $25.00"):  # a word that merely ends in "us" is not a currency
        got = find_amount(text)
        assert got is not None and got.currency == "CAD", text


def test_an_absurd_amount_is_a_refused_value_not_an_arithmetic_crash():
    # DOC474.177: date, amount and extension are never cut, so the amount is what could break the length limit. Measured: a
    # valid amount fits (<= 28 digits), but a huge one raised decimal.InvalidOperation, which propose() does not catch
    from decimal import Decimal

    from docflow.naming import MAX_BYTES, MAX_NAME, build_filename
    for bad in (Decimal("9" * 300 + ".00"), Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(ValueError, match="amount"):
            build_filename("2025-01-01", "Voisin", "Lettre", "x" * 400, bad)
    ok = build_filename("2025-01-01", "V" * 400, "Lettre", "d" * 400, Decimal("158.98"))        # long CUT-able parts still work
    assert len(ok) <= MAX_NAME and len(ok.encode("utf-8")) <= MAX_BYTES and "158.98$" in ok


def test_a_total_label_with_no_amount_does_not_borrow_a_tax_or_sub_total_line_below_it():
    # DOC474.215: "Total" alone on its line took the amount of the NEXT line, even a TPS/TVQ or a sub-total, at 0.95
    from decimal import Decimal

    from docflow.fields import find_amount
    for text in ("Total\nTPS 5,00 $\nTVQ 9,98 $", "Total a payer\nSous-total 100,00 $", "Total\nSub-total 10,00 $",
                 "Total\nTPS : 5,00 $\n158,98 $"):
        got = find_amount(text)
        assert got is None or got.confidence < 0.95, text                    # never "sure": a human confirms
    assert find_amount("Total\nTPS : 5,00 $\n158,98 $").value == Decimal("158.98")     # the unlabelled fallback still finds the total
    ok = find_amount("Total\n158,98 $")
    assert ok is not None and ok.value == Decimal("158.98") and ok.confidence == 0.95       # the normal layout is unchanged
    incl = find_amount("Total\nTaxes incluses 20,00 $")
    assert incl is not None and incl.value == Decimal("20.00")                       # "taxes included" IS the grand total


@pytest.mark.parametrize("text,date", [("Facture du 5 janv. 2025", "2025-01-05"), ("Date : 12 févr. 2025", "2025-02-12"),
                                       ("Le 3 juil. 2025", "2025-07-03"), ("5 janv 2025", "2025-01-05"),
                                       ("Le 3 juil 2025", "2025-07-03"), ("janv. 2025", "2025-01")])
def test_the_usual_french_abbreviations_of_january_february_and_july_are_read(text, date):
    # DOC474.37: "jan" was found but the "v" that follows broke the expected space; "juil" was not in the table at all
    from docflow.fields import find_date, norm
    found = find_date(norm(text))
    assert found is not None and found.text == date, text


@pytest.mark.parametrize("text,date", [("1st March 2025", "2025-03-01"), ("21st January 2026", "2026-01-21"),
                                       ("22nd of March 2025", None), ("3rd Feb 2025", "2025-02-03"), ("14th July 2025", "2025-07-14"),
                                       ("1er mars 2025", "2025-03-01"), ("12 March 2025", "2025-03-12")])
def test_english_ordinals_are_accepted_before_the_month_as_they_are_after_it(text, date):
    # DOC474.38: "March 1st, 2025" worked but "1st March 2025" did not
    from docflow.fields import find_date, norm
    found = find_date(norm(text))
    if date is None:                                                       # "22nd of March" is not a form we read: no wrong date
        assert found is None or found.text != "2025-03-22"
    else:
        assert found is not None and found.text == date, text


def test_a_name_whose_uncuttable_parts_alone_exceed_the_limit_is_refused_not_returned_too_long(monkeypatch):
    # DOC474.82: the date, the amount and the extension are never cut; if they alone passed the limit the loop ended silently
    from decimal import Decimal

    from docflow import naming
    assert naming.build_filename("2025-01-01", "Voisin", "Lettre", "", Decimal("158.98")).endswith("158.98$.pdf")    # normal: fine
    monkeypatch.setattr(naming, "MAX_NAME", 30)                  # a limit the fixed parts (date, amount, extension) cannot respect
    with pytest.raises(ValueError, match="too long"):
        naming.build_filename("2025-01-01", "Voisin", "Lettre", "detail", Decimal("158.98"))
    monkeypatch.setattr(naming, "MAX_NAME", 180)
    monkeypatch.setattr(naming, "MAX_BYTES", 30)
    with pytest.raises(ValueError, match="too long"):
        naming.build_filename("2025-01-01", "Voisin", "Lettre", "detail", Decimal("158.98"))


@pytest.mark.parametrize("bad", ["٢٠٢٤-٠١-٠١", "２０２４-０１-０１", "२०२४", "2024-०१", "٢٠٢٤"])
def test_a_date_written_with_non_ascii_digits_is_not_a_valid_date(bad):
    # DOC474.83: \d matches every Unicode digit and int() converts them, so these passed and went into the file name as typed
    from docflow.naming import build_filename, valid_date
    assert valid_date(bad) is False, bad
    with pytest.raises(ValueError):
        build_filename(bad, "Voisin", "Lettre")
    assert valid_date("2024-01-01") and valid_date("2024-01") and valid_date("2024") and valid_date("XXXX")


def test_invisible_and_bidirectional_control_characters_never_survive_in_a_file_name():
    # DOC474.84: U+202E (right-to-left override) can make "facture.pdf" display as another extension; zero-width characters make
    # two visually identical names different files; DEL passed too
    import sys
    import unicodedata

    from docflow.naming import FORBIDDEN, sanitize
    assert sanitize("fac‮ture​ \x7f2025.pdf") == "facture 2025.pdf"
    for char in "‮‭⁦⁩​‍﻿\xad؜\x7f":
        assert FORBIDDEN.search(f"a{char}b"), hex(ord(char))
    missed = [hex(c) for c in range(sys.maxunicode + 1) if unicodedata.category(chr(c)) == "Cf" and not FORBIDDEN.search(chr(c))]
    assert not missed, f"format characters let through: {missed}"                       # the table follows Unicode, nothing forgotten
    for fine in ("é", "ç", "à", "ñ", "日本", "Привет", "-", "_", "(", ")", "&", "'", "$"):
        assert not FORBIDDEN.search(fine), fine                                          # ordinary names are untouched


def test_an_item_title_may_start_with_an_accented_or_other_non_ascii_letter():
    # DOC474.148: the title had to start with [A-Za-z0-9]; "Écouteurs…" and "À la carte…" lines vanished from the item list
    from docflow.fields import find_items
    text = ("Écouteurs sans fil bluetooth 1 $19.99 $19.99\nÀ la carte menu complet 2 $5.00 $10.00\n"
            "Plain English Title 3 $2.00 $6.00\n9 Lives cat food 4 $1.00 $4.00\nПодушка для сидения 1 $7.00 $7.00\n"
            "ASIN: B0ABC12345 1 $1.00 $1.00\n- tiret initial n'est pas un titre 1 $1.00 $1.00\n")
    assert find_items(text) == ["Écouteurs sans fil bluetooth", "À la carte menu complet", "Plain English Title",
                                "9 Lives cat food", "Подушка для сидения"]               # no ASIN line, no line starting with a dash


@pytest.mark.parametrize("raw", ["CON", "CON.txt", "CON .txt", "con  .pdf", "NUL .backup", "com1 .x", " AUX .tar.gz", "LPT9 "])
def test_a_windows_reserved_name_is_recognised_whatever_spaces_or_dots_follow_it(raw):
    # DOC474.178: "CON .txt" kept its space before the extension and was not taken for CON, which Windows treats as a device
    from docflow.naming import sanitize
    out = sanitize(raw)
    assert out.startswith("_"), (raw, out)


@pytest.mark.parametrize("fine", ["Console", "Connexion .pdf", "COM10", "CONTRAT", "Facture CON", "NULL.txt", "AUXILIAIRE"])
def test_names_that_merely_start_like_a_reserved_one_are_left_alone(fine):
    from docflow.naming import sanitize
    assert not sanitize(fine).startswith("_"), fine


@pytest.mark.parametrize("text", ["Residue report 5 March 2025", "Undue delay 5 March 2025"])
def test_a_word_that_merely_ends_in_due_is_not_a_due_date_label(text):
    # DOC474.217: "due\b" matched the end of overdue / residue / undue, so the neighbouring date was ranked as a due date (overdue itself stays a due label)
    from docflow.fields import find_date, norm
    found = find_date(norm(text))
    assert found is not None and found.kind != "due", text


def test_the_word_due_itself_is_still_a_due_date_label():
    from docflow.fields import find_date, norm
    assert find_date(norm("Due date 5 March 2025")).kind == "due"


@pytest.mark.parametrize("text,expected", [
    ("Газпром Нефть ООО", "ГазпромНефтьООО"), ("Ελληνική Εταιρεία", "ΕλληνικηΕταιρεια"), ("株式会社東京商事", "株式会社東京商事"),
    ("شركة النفط", "شركةالنفط"), ("Hydro-Québec 2025", "Hydro-Quebec2025"),
    ("A/B:C*D", "ABCD"), ("  ..-x-..  ", "x"), ("%%%", ""),                    # what a file name forbids, or only punctuation: gone
])
def test_token_keeps_the_letters_of_any_alphabet_and_drops_only_what_a_name_cannot_hold(text, expected):
    # DOC474.241: only the Latin alphabet survived; Cyrillic, Greek, Arabic and CJK names came out empty
    assert token(text) == expected
