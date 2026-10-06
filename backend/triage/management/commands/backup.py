from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from docflow.backup import make_backup, restore


class Command(BaseCommand):
    help = ("Back up the database (a consistent snapshot, the service may keep running) and the learned rules into a dated "
            "folder under settings.yaml backup.dir, keeping the newest backup.keep. --restore FOLDER puts one back: stop the service first.")

    def add_arguments(self, parser):
        parser.add_argument("--to", type=Path, help="write under this folder instead of backup.dir")
        parser.add_argument("--restore", type=Path, metavar="FOLDER", help="restore this docflow-YYYYmmdd-HHMMSS folder (service stopped)")

    def handle(self, *args, **options):
        cfg = settings.DOCFLOW
        db, learn = cfg.path("db"), cfg.learn_dir
        if options["restore"]:
            try:
                restore(options["restore"], db, learn)
            except OSError as e:
                raise CommandError(str(e)) from e
            self.stdout.write(self.style.SUCCESS(f"restored from {options['restore']}; what was replaced is kept as *.before-restore"))
            return
        conf = cfg.settings.get("backup") or {}
        dest = options["to"] or (Path(conf["dir"]) if conf.get("dir") else None)
        if dest is None:
            raise CommandError("no destination: give --to FOLDER or set backup.dir in config/settings.yaml")
        try:
            out = make_backup(db, learn, dest, keep=int(conf.get("keep", 14)))
        except (OSError, ValueError) as e:  # a missing share, a bad `keep`: said plainly; a sqlite error is a real fault and shows
            raise CommandError(str(e)) from e
        self.stdout.write(self.style.SUCCESS(f"backup written: {out}"))
