"""The French interface speaks in ONE register: impersonal or infinitive ("Approuver", "laisser tel quel"), never
the familiar "tu"/"ton"/"dépose"/"clique". Read from the source file: the front end has no JavaScript test runner."""
import re
from pathlib import Path

I18N = Path(__file__).resolve().parents[1] / "frontend" / "src" / "i18n.tsx"

# second person, singular (familiar) or plural (formal): tutoiement and vouvoiement are both banned here
SECOND_PERSON = re.compile(
    r"\b(tu|toi|ton|ta|tes|te|vous|votre|vos)\b|-toi\b|-vous\b"
    r"|\b(d[ée]pose|clique|classe|approuve|choisis|saisis|v[ée]rifie|attends|essaie|r[ée]essaie|corrige|relance"
    r"|d[ée]posez|cliquez|classez|approuvez|choisissez|saisissez|v[ée]rifiez|attendez|essayez|corrigez|relancez)\b"
    r"|\w+-en\b", re.IGNORECASE)


def french_values() -> list[tuple[str, str]]:
    """(key, text) of every French string: the `fr` dictionary and the translated server messages."""
    source = I18N.read_text(encoding="utf-8")
    block = source[source.index("const fr"):source.index("const fill")]
    pairs = re.findall(r"^\s*(?:'([^']+)'|\"([^\"]+)\"):\s*(?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\")\s*,?\s*$",
                       block, re.MULTILINE)
    return [(a or b, c or d) for a, b, c, d in pairs]


def test_the_extraction_really_reads_the_french_strings():
    values = dict(french_values())
    assert len(values) > 80 and values["queue.scan"] == "Scanner l'Inbox"           # a silent miss would make the next test vacuous


def test_french_interface_text_never_addresses_the_user_in_the_second_person():
    offenders = [(k, m.group(0)) for k, text in french_values() for m in [SECOND_PERSON.search(text)] if m]
    assert offenders == []


def english_values() -> list[tuple[str, str]]:
    source = I18N.read_text(encoding="utf-8")
    block = source[source.index("const en = {"):source.index("export type Key")]
    pairs = re.findall(r"^\s*(?:'([^']+)'|\"([^\"]+)\"):\s*(?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\")\s*,?\s*$",
                       block, re.MULTILINE)
    return [(a or b, c or d) for a, b, c, d in pairs]


def test_a_counted_message_has_a_singular_and_a_plural_text_in_both_languages_and_no_plural_marks():
    english, french = dict(english_values()), dict(french_values())
    assert len(english) > 80 and "queue.scanDone.one" in english                        # the extraction really sees them
    bases = {k.rsplit(".", 1)[0] for k in english if k.endswith((".one", ".other"))}
    assert {"queue.scanDone", "queue.approvedMany", "queue.failedMany", "dash.pdfCount"} <= bases
    for table in (english, french):
        for base in bases:
            assert f"{base}.one" in table and f"{base}.other" in table, base            # both forms, in each language
            assert "{n}" in table[f"{base}.one"] and "{n}" in table[f"{base}.other"], base
        assert not any(re.search(r"\w\((s|x|e|es|nt)\)", text) for text in table.values())   # no "document(s)", "nouveau(x)"
    ui_keys = {k for k in french if re.fullmatch(r"[a-zA-Z]+(\.\w+)+", k)}               # (the server messages are keyed by sentences)
    assert ui_keys == set(english)                                                      # and the two dictionaries stay in step
    assert french["queue.scanDone.one"] != french["queue.scanDone.other"]


def test_the_french_remove_button_says_retirer_like_its_confirmation_and_its_message():
    # DOC474.25: "Supprimer" suggested the PDF is deleted; the confirmation and the success message say it stays in place
    src = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "i18n.tsx").read_text()
    fr = src[src.index("const fr"):]
    assert "'queue.remove': 'Retirer de la file'" in fr and "Supprimer de la file" not in fr


def test_the_french_interface_calls_a_company_a_societe_everywhere():
    # DOC474.26: "Compagnie" in the form and the messages, "Société" on the Rules, accuracy and selection screens
    src = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "i18n.tsx").read_text()
    fr = src[src.index("const fr"):]
    assert "ompagnie" not in fr
    assert "'field.company': 'Société'" in fr and "'learned.company': 'société « {v} »'" in fr


def test_the_empty_queue_message_quotes_the_exact_label_of_the_scan_button_in_both_languages():
    # DOC474.27: the message said "Scan" / "Scanner" while the button reads "Scan inbox" / "Scanner l'Inbox"
    src = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "i18n.tsx").read_text()
    en, fr = src[src.index("const en"):src.index("const fr")], src[src.index("const fr"):]
    for block in (en, fr):
        label = re.search(r"'queue\.scan': [\"'](.+?)[\"'],", block).group(1)
        empty = re.search(r"'queue\.empty': (.+),\n", block).group(1)
        assert label in empty, (label, empty)


def test_without_a_saved_choice_the_language_follows_the_browser_and_a_saved_choice_wins():
    # DOC474.28: a fr-CA browser got the English interface until the switch was used by hand (and again in a private window)
    src = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "i18n.tsx").read_text()
    body = src[src.index("function readLang"):src.index("function readLang") + 600]
    assert "stored === 'fr' || stored === 'en'" in body                          # a saved choice, either one, is kept
    assert "navigator.language" in body and "startsWith('fr')" in body            # otherwise the browser's language decides
    assert body.index("stored === 'fr'") < body.index("navigator.language")      # in that order


def test_the_accuracy_summary_has_a_singular_form_chosen_by_the_total():
    # DOC474.29: "1 of 1 filed documents were accepted" with a single filed document
    root = Path(__file__).resolve().parents[1] / "frontend" / "src"
    src = (root / "i18n.tsx").read_text()
    en, fr = src[src.index("const en"):src.index("const fr")], src[src.index("const fr"):]
    for block in (en, fr):
        assert "'acc.summary.one'" in block and "'acc.summary.other'" in block and "'acc.summary':" not in block
    assert "filed document ({rate})" in en and "document classé ({rate})" in fr          # the singular reads as a singular
    assert "n: s.total" in (root / "components" / "Accuracy.tsx").read_text()           # the count that picks the form


def test_every_error_message_written_in_api_ts_has_a_french_translation():
    # DOC474.59 claimed the client's error messages stay in English: they go through msg(), which needs an entry for each
    root = Path(__file__).resolve().parents[1] / "frontend" / "src"
    api, i18n = (root / "api.ts").read_text(), (root / "i18n.tsx").read_text()
    table = i18n[i18n.index("const frMessages"):]
    keys = re.findall(r"^  (?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"):", table, re.MULTILINE)
    keys = [a or b for a, b in keys]
    literals = [text for _, text in re.findall(r"new ApiError\(\s*(['`])(.+?)\1", api)]
    literals.append("HTTP error: ${status}")                               # errorMessage()'s fallback, built just above
    assert len(literals) >= 3, "the extraction really sees the messages"
    for text in literals:
        static = re.split(r"\$\{", text)[0]
        # msg(): the whole text is a key, or a key ending in ": " is the start of the text (the rest is appended as it is)
        assert any(static == k or (k.endswith(": ") and static.startswith(k)) for k in keys), f"no French text for: {static!r}"


def test_a_month_key_from_the_api_is_shown_as_a_month_name_in_the_language_of_the_page():
    # DOC474.104: the accuracy screen printed '2026-03'; the rest of the interface speaks the reader's language
    root = Path(__file__).resolve().parents[1] / "frontend" / "src"
    i18n, accuracy = (root / "i18n.tsx").read_text(), (root / "components" / "Accuracy.tsx").read_text()
    assert "month: (key: string) => string" in i18n                                        # part of the language context
    assert "new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric', timeZone: 'UTC' })" in i18n
    assert "/^(\\d{4})-(0[1-9]|1[0-2])$/.exec(key)" in i18n and ": key" in i18n                  # a real month, else the key as it is
    assert "row(m.month, month(m.month)," in accuracy                                      # key kept as the React key, label shown


def test_the_counters_of_the_months_and_the_bands_come_from_translated_messages():
    # DOC474.105: '3 / 5' and '80-90 %' were written in the code: no word for what is counted, French spacing hard-coded
    root = Path(__file__).resolve().parents[1] / "frontend" / "src"
    i18n, accuracy = (root / "i18n.tsx").read_text(), (root / "components" / "Accuracy.tsx").read_text()
    en, fr = i18n[i18n.index("const en"):i18n.index("const fr")], i18n[i18n.index("const fr"):]
    assert "'acc.untouchedCount': '{n} accepted of {total}'" in en and "'acc.untouchedCount': '{n} acceptés sur {total}'" in fr
    assert "'acc.band': '{band}%'" in en and "'acc.band': '{band} %'" in fr            # French: a (narrow, no-break) space before %
    assert "`${m.untouched} / ${m.total}`" not in accuracy and "`${b.untouched} / ${b.total}`" not in accuracy
    assert "`${b.band} %`" not in accuracy
    assert accuracy.count("t('acc.untouchedCount', { n:") == 2 and "t('acc.band', { band: b.band })" in accuracy


def test_a_document_date_from_the_server_is_shown_in_the_language_of_the_page_in_the_search_results():
    # DOC474.123: '2025-10-07' / '2025-10' / '2025' / 'XXXX' were printed as the server sends them
    root = Path(__file__).resolve().parents[1] / "frontend" / "src"
    i18n, search = (root / "i18n.tsx").read_text(), (root / "pages" / "Search.tsx").read_text()
    assert "date: (key: string) => string" in i18n                                         # part of the language context
    body = i18n[i18n.index("      date: (key) => {"):]
    body = body[:body.index("      },")]
    assert "new Intl.DateTimeFormat(locale, { dateStyle: 'long', timeZone: 'UTC' })" in i18n
    assert "getUTCDate() === Number(day)" in body and "month(key)" in body and "return key" in body    # real day, month, else raw
    assert "date(h.date)" in search and "[h.company, h.date, h.folder]" not in search
