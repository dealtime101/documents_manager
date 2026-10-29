from django.core.management.base import BaseCommand, CommandError

from triage import services


class Command(BaseCommand):
    help = ("Read again the text of the documents that have none stored, so the filed archive can be searched. Local OCR: "
            "it can take a while. Safe to run again: it only touches documents without a stored text.")

    def handle(self, *args, **options):
        def report(position, item, total):
            self.stdout.write(f"{position}/{total}: {item.source_path}")

        result = services.reindex_text(report)
        summary = f"{result['indexed']} indexed, {result['unreadable']} unreadable (see the log), {result['without_text']} without any text"
        if result["unreadable"]:  # a partial success is not shown as a success, and a scheduled run sees the exit code
            self.stdout.write(self.style.WARNING(summary))
            raise CommandError(f"{result['unreadable']} document(s) could not be read: they stay out of the search. "
                               "The others are indexed; run the command again once the cause (see the log) is fixed.")
        self.stdout.write(self.style.SUCCESS(summary))
