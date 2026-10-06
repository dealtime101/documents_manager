"""Rewrite the French engine notes stored on existing items into their English equivalents."""
from django.db import migrations

EXACT = {
    "Document identique déjà classé (SHA-256).": "Identical document already filed (SHA-256).",
    "Page image et Tesseract introuvable : OCR impossible.": "Image page and Tesseract not found: OCR unavailable.",
    "Analyse par modèle local (confirmation requise).": "Analysed by local model (confirmation required).",
    "Destination par année, mais la date du document est inconnue.":
        "Year-based destination, but the document date is unknown.",
    "Aucune règle de destination.": "No destination rule.",
    "Document potentiellement déjà présent.": "Document potentially already present.",
    "Identique à un fichier du même lot (SHA-256).": "Identical to another file in the same batch (SHA-256).",
    "Identique à un document déjà classé (SHA-256).": "Identical to a document already filed (SHA-256).",
    "Identique à un autre fichier de la file (SHA-256).": "Identical to another file in the queue (SHA-256).",
}
PREFIXES = {
    "Lecture impossible: ": "Cannot read file: ",
    "Ollama indisponible: ": "Ollama unavailable: ",
}


BATCH = 500


def translate(note):
    if not isinstance(note, str):
        return note
    if note in EXACT:
        return EXACT[note]
    for fr, en in PREFIXES.items():
        if note.startswith(fr):
            return en + note[len(fr):]
    return note


def to_english(apps, schema_editor):
    Item = apps.get_model("triage", "Item")
    alias = schema_editor.connection.alias  # the database being migrated, not necessarily "default"
    manager = Item.objects.using(alias)
    changed = []

    def flush():  # one UPDATE per batch of rows, not one per row
        if changed:
            manager.bulk_update(changed, ["notes"], batch_size=BATCH)
            changed.clear()

    # streamed in chunks and only the two columns needed: the whole table is never held in memory
    for it in manager.only("id", "notes").iterator(chunk_size=BATCH):
        if not isinstance(it.notes, list):
            continue
        new = [translate(n) for n in it.notes]
        if new != it.notes:
            it.notes = new
            changed.append(it)
            if len(changed) >= BATCH:
                flush()
    flush()


class Migration(migrations.Migration):

    dependencies = [
        ("triage", "0002_scanjob"),
    ]

    operations = [
        # Reversing is deliberately a no-op, not "to_french": the CODE (not the schema) decides the language of the notes it
        # writes, and it writes English; the interface translates English notes at display time. Turning stored notes back
        # into French would leave data that disagrees with the code and that the interface would not translate.
        migrations.RunPython(to_english, migrations.RunPython.noop),
    ]
