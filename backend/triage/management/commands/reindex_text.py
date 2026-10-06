from django.core.management.base import BaseCommand

from triage import services


class Command(BaseCommand):
    help = ("Read again the text of the documents that have none stored, so the filed archive can be searched. Local OCR: "
            "it can take a while. Safe to run again: it only touches documents without a stored text.")

    def handle(self, *args, **options):
        def report(n, item):
            self.stdout.write(f"{n}: {item.source_path}")

        result = services.reindex_text(report)
        self.stdout.write(self.style.SUCCESS(
            f"{result['indexed']} indexed, {result['unreadable']} unreadable (see the log), {result['without_text']} without any text"))
