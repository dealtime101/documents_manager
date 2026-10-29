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
    # DOC534.238: the other verbs an interface speaks with (singular and plural imperatives). Left out on purpose: forms that are also a
    # noun, a participle, a preposition or a third person in the real texts ("note", "faites", "entre", "va", "utilise", "modifie")
    r"|\b(ouvre|ouvrez|s[ée]lectionne|s[ée]lectionnez|glisse|glissez|ferme|fermez|lancez|copie|copiez|colle|collez|ajoute|ajoutez"
    r"|supprime|supprimez|retire|retirez|enregistre|enregistrez|valide|validez|modifiez|changez|consulte|consultez|r[ée]essayez"
    r"|patiente|patientez|revenez|reviens|appuie|appuyez|tape|tapez|entrez|indique|indiquez|pr[ée]cise|pr[ée]cisez|utilisez"
    r"|regarde|regardez|laissez|gardez|mets|mettez|contacte|contactez|d[ée]place|d[ée]placez|renomme|renommez"
    r"|t[ée]l[ée]charge|t[ée]l[ée]chargez|connecte|connectez|relis|relisez|prenez|allez|sauvegarde|sauvegardez|confirme|confirmez"
    r"|annule|annulez|recommence|recommencez)\b"
    r"|\w+-en\b", re.IGNORECASE)


def french_values() -> list[tuple[str, str]]:
    """(key, text) of every French string: the `fr` dictionary and the translated server messages."""
    source = I18N.read_text(encoding="utf-8")
    block = source[source.index("const fr"):source.index("const fill")]
    pairs = re.findall(r"^\s*(?:'([^']+)'|\"([^\"]+)\"):\s*(?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\")\s*,?\s*$",
                       block, re.MULTILINE)
    return [(a or b, c or d) for a, b, c, d in pairs]


KEY_AT_TABLE_LEVEL = re.compile(r"^  (?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"):", re.MULTILINE)


def keys_the_extraction_missed(block: str, extracted: list[tuple[str, str]]) -> list[str]:
    """DOC534.237: the keys written in the table whose text was not read as a one-line quoted string (a value in backticks, over
    several lines, or a trailing comment...). Each is a translation the register checks would never see."""
    wanted = [a or b for a, b in KEY_AT_TABLE_LEVEL.findall(block)]
    got = {k for k, _ in extracted}
    return [k.replace("\\'", "'") for k in wanted if k.replace("\\'", "'") not in got]


def table_block(source: str, start: str, end: str) -> str:
    return source[source.index(start):source.index(end)]


def test_every_key_of_the_translation_tables_has_its_text_read():
    source = I18N.read_text(encoding="utf-8")
    assert keys_the_extraction_missed(table_block(source, "const fr", "const fill"), french_values()) == []
    assert keys_the_extraction_missed(table_block(source, "const en = {", "export type Key"), english_values()) == []
    # and the check itself sees a value that the extraction cannot read
    sample = "  'a.b': 'one line',\n  'c.d': `in backticks`,\n  'e.f':\n    'next line',\n  'g.h': 'x' + 'y',\n"
    pairs = [("a.b", "one line")]
    assert keys_the_extraction_missed(sample, pairs) == ["c.d", "e.f", "g.h"]


def test_the_extraction_really_reads_the_french_strings():
    values = dict(french_values())
    assert len(values) > 80 and values["queue.scan"] == "Analyser la boîte de réception"         # a silent miss would make the next test vacuous


def test_the_second_person_pattern_catches_the_common_interface_imperatives_and_spares_ordinary_words():
    # DOC534.238: "ouvre", "sélectionne", "glisse", "ouvrez", "sélectionnez"... went through
    for caught in ("Ouvre le dossier", "Sélectionne un fichier", "Glisse le PDF ici", "Ouvrez le dossier", "Sélectionnez un fichier",
                   "Appuyez sur Entrée", "Enregistrez puis fermez", "Réessayez plus tard", "Cliquez ici", "Vérifie le nom"):
        assert SECOND_PERSON.search(caught), caught
    for spared in ("Aucune note de version trouvée.", "Corrections faites à la main, par champ", "Entre deux scans", "Ouvrir le dossier",
                   "Sélectionner un fichier", "Fichier ouvert", "Dossier supprimé", "Enregistrement réussi"):
        assert not SECOND_PERSON.search(spared), spared


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
    src = I18N.read_text(encoding="utf-8")
    fr = src[src.index("const fr"):]
    assert "'queue.remove': 'Retirer de la file'" in fr and "Supprimer de la file" not in fr


def test_the_french_interface_calls_a_company_a_societe_everywhere():
    # DOC474.26: "Compagnie" in the form and the messages, "Société" on the Rules, accuracy and selection screens
    src = I18N.read_text(encoding="utf-8")
    fr = src[src.index("const fr"):]
    assert "ompagnie" not in fr
    assert "'field.company': 'Société'" in fr and "'learned.company': 'société « {v} »'" in fr


def test_the_empty_queue_message_quotes_the_exact_label_of_the_scan_button_in_both_languages():
    # DOC474.27: the message said "Scan" / "Scanner" while the button reads "Scan inbox" / "Analyser la boîte de réception"
    src = I18N.read_text(encoding="utf-8")
    en, fr = src[src.index("const en"):src.index("const fr")], src[src.index("const fr"):]
    for block in (en, fr):
        label = re.search(r"'queue\.scan': [\"'](.+?)[\"'],", block).group(1)
        empty = re.search(r"'queue\.empty': (.+),\n", block).group(1)
        assert label in empty, (label, empty)


def test_the_french_table_reader_takes_that_table_only_and_says_clearly_when_it_cannot_find_it():
    # DOC534.215: not "everything to the end of the file", and not a bare ValueError when the constant is renamed
    import pytest
    from conftest import fr_messages_table
    source = "const en = {\n  'a': 'in en',\n}\nconst frMessages = {\n  'b': 'fr',\n}\nconst other = {\n  'c': 'elsewhere',\n}\n"
    table = fr_messages_table(source)
    assert "'b'" in table and "'a'" not in table and "'c'" not in table
    with pytest.raises(AssertionError, match="no longer declares"):
        fr_messages_table("const fr = {\n}\n")
    real = I18N.read_text(encoding="utf-8")                                              # (DOC534.236: the one constant for this file)
    assert "const frSpaced" not in fr_messages_table(real) and fr_messages_table(real).count("\n") > 50   # the real table, cut at its end
    old_way = "index(" + '"const frMessages")'                                          # (built, so that this line is not its own match)
    assert not [p.name for p in Path(__file__).parent.glob("test_*.py") if old_way in p.read_text(encoding="utf-8")]


def test_every_reason_the_settings_screen_can_be_refused_with_has_a_french_text_and_goes_through_msg():
    # DOC534.123: the field errors of the server were shown as they came, in English, whatever the language of the screen
    root = Path(__file__).resolve().parents[1]
    server = (root / "backend" / "docflow" / "usersettings.py").read_text(encoding="utf-8")
    i18n = (root / "frontend" / "src" / "i18n.tsx").read_text(encoding="utf-8")
    from conftest import fr_messages_table
    table = fr_messages_table(i18n)
    keys = {a or b for a, b in re.findall(r"^  (?:'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\"):", table, re.MULTILINE)}
    texts = re.findall(r'errors(?:\[[^\]]+\])? = (?:f)?"([^"]+)"', server) + re.findall(r'\n\s+return f"([^"]*\{p\}[^"]*)"', server)
    texts += re.findall(r'errors\.setdefault\("[a-z_]+", "([^"]+)"\)', server)
    assert len(texts) >= 8, texts                                                       # the extraction really sees the messages
    for text in texts:
        assert text in keys, f"no French text for the server message: {text!r}"
    settings = (root / "frontend" / "src" / "pages" / "Settings.tsx").read_text(encoding="utf-8")
    assert "{msg(errors[key])}" in settings and "{msg(m)}" in settings                  # and both places show them through msg()
    assert "const frTemplates = " in i18n and "if (m) return french.replace('{p}', m[1])" in i18n   # the texts with a path inside


def test_the_texts_name_the_inbox_the_way_the_settings_do_and_never_a_fixed_folder_called_inbox():
    # DOC534.63: the French button said "Scanner l'Inbox" and the messages sent the reader to a folder "_Inbox", while the settings
    # speak of the boîte de réception and the folder is whatever the user chose
    src = I18N.read_text(encoding="utf-8")
    en, fr = src[src.index("const en"):src.index("const fr")], src[src.index("const fr"):]
    assert "_Inbox" not in src and "l'Inbox" not in src
    assert "'queue.scan': 'Analyser la boîte de réception'" in fr and "'dash.srcInbox': 'Boîte de réception'" in fr
    assert "boîte de réception" in re.search(r"'queue\.empty': (.+),\n", fr).group(1)
    assert "'dash.srcInbox': 'Inbox'" in en


def test_file_sizes_use_the_units_and_the_number_format_of_the_language():
    # DOC534.68: the library showed "B", "KB", "MB" and a point decimal in French
    root = Path(__file__).resolve().parents[1] / "frontend" / "src"
    src, page = (root / "i18n.tsx").read_text(encoding="utf-8"), (root / "pages" / "Library.tsx").read_text(encoding="utf-8")
    en, fr = src[src.index("const en"):src.index("const fr")], src[src.index("const fr"):]
    assert [f"'size.{k}': '{v}'" in en for k, v in (("b", "B"), ("kb", "KB"), ("mb", "MB"))] == [True] * 3
    assert [f"'size.{k}': '{v}'" in fr for k, v in (("b", "o"), ("kb", "Ko"), ("mb", "Mo"))] == [True] * 3
    assert "` B`" not in page and "toFixed(" not in page and "new Intl.NumberFormat(lang" in page   # no unit or separator written in the code
    assert "{size(f.size, t, lang)}" in page


def test_the_count_of_accepted_documents_has_a_singular_and_a_plural_in_both_languages():
    # DOC534.64: one key '{n} acceptés sur {total}' gave "1 acceptés sur 1"
    src = I18N.read_text(encoding="utf-8")
    en, fr = src[src.index("const en"):src.index("const fr")], src[src.index("const fr"):]
    assert "'acc.untouchedCount':" not in src                                       # no form without a number agreement
    assert "'acc.untouchedCount.one': '{n} accepté sur {total}'" in fr and "'acc.untouchedCount.other': '{n} acceptés sur {total}'" in fr
    assert "'acc.untouchedCount.one'" in en and "'acc.untouchedCount.other'" in en


def test_without_a_saved_choice_the_language_follows_the_browser_and_a_saved_choice_wins():
    # DOC474.28: a fr-CA browser got the English interface until the switch was used by hand (and again in a private window)
    src = I18N.read_text(encoding="utf-8")
    body = src[src.index("function readLang"):src.index("function readLang") + 600]
    assert "stored === 'fr' || stored === 'en'" in body                          # a saved choice, either one, is kept
    assert "navigator.language" in body and "startsWith('fr')" in body            # otherwise the browser's language decides
    assert body.index("stored === 'fr'") < body.index("navigator.language")      # in that order


def test_the_accuracy_summary_has_a_singular_form_chosen_by_the_total():
    # DOC474.29: "1 of 1 filed documents were accepted" with a single filed document
    root = Path(__file__).resolve().parents[1] / "frontend" / "src"
    src = (root / "i18n.tsx").read_text(encoding="utf-8")
    en, fr = src[src.index("const en"):src.index("const fr")], src[src.index("const fr"):]
    for block in (en, fr):
        assert "'acc.summary.one'" in block and "'acc.summary.other'" in block and "'acc.summary':" not in block
    assert "filed document ({rate})" in en and "document classé ({rate})" in fr          # the singular reads as a singular
    assert "n: s.total" in (root / "components" / "Accuracy.tsx").read_text(encoding="utf-8")           # the count that picks the form


def test_every_error_message_written_in_api_ts_has_a_french_translation():
    # DOC474.59 claimed the client's error messages stay in English: they go through msg(), which needs an entry for each
    root = Path(__file__).resolve().parents[1] / "frontend" / "src"
    api, i18n = (root / "api.ts").read_text(encoding="utf-8"), (root / "i18n.tsx").read_text(encoding="utf-8")
    from conftest import fr_messages_table
    table = fr_messages_table(i18n)
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
    i18n, accuracy = (root / "i18n.tsx").read_text(encoding="utf-8"), (root / "components" / "Accuracy.tsx").read_text(encoding="utf-8")
    assert "month: (key: string) => string" in i18n                                        # part of the language context
    assert "new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric', timeZone: 'UTC' })" in i18n
    assert "/^(\\d{4})-(0[1-9]|1[0-2])$/.exec(key)" in i18n and ": key" in i18n                  # a real month, else the key as it is
    assert "row(m.month, month(m.month)," in accuracy                                      # key kept as the React key, label shown


def test_the_counters_of_the_months_and_the_bands_come_from_translated_messages():
    # DOC474.105: '3 / 5' and '80-90 %' were written in the code: no word for what is counted, French spacing hard-coded
    root = Path(__file__).resolve().parents[1] / "frontend" / "src"
    i18n, accuracy = (root / "i18n.tsx").read_text(encoding="utf-8"), (root / "components" / "Accuracy.tsx").read_text(encoding="utf-8")
    en, fr = i18n[i18n.index("const en"):i18n.index("const fr")], i18n[i18n.index("const fr"):]
    assert "'acc.untouchedCount.other': '{n} accepted of {total}'" in en and "'acc.untouchedCount.other': '{n} acceptés sur {total}'" in fr
    assert "'acc.band': '{band}%'" in en and "'acc.band': '{band} %'" in fr            # French: a (narrow, no-break) space before %
    assert "`${m.untouched} / ${m.total}`" not in accuracy and "`${b.untouched} / ${b.total}`" not in accuracy
    assert "`${b.band} %`" not in accuracy
    assert accuracy.count("t('acc.untouchedCount', { n:") == 2 and "t('acc.band', { band: b.band })" in accuracy


def test_a_document_date_from_the_server_is_shown_in_the_language_of_the_page_in_the_search_results():
    # DOC474.123: '2025-10-07' / '2025-10' / '2025' / 'XXXX' were printed as the server sends them
    root = Path(__file__).resolve().parents[1] / "frontend" / "src"
    i18n, search = (root / "i18n.tsx").read_text(encoding="utf-8"), (root / "pages" / "Search.tsx").read_text(encoding="utf-8")
    assert "date: (key: string) => string" in i18n                                         # part of the language context
    body = i18n[i18n.index("      date: (key) => {"):]
    body = body[:body.index("      },")]
    assert "new Intl.DateTimeFormat(locale, { dateStyle: 'long', timeZone: 'UTC' })" in i18n
    assert "getUTCDate() === Number(day)" in body and "month(key)" in body and "return key" in body    # real day, month, else raw
    assert "date(h.date)" in search and "[h.company, h.date, h.folder]" not in search
