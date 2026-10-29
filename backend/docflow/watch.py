"""Notice the files that ARRIVE in the folders to watch (DOC534.5), by looking at them every few seconds: nothing to install, nothing
to package, and it works on a network share, where the notification systems of the operating system do not."""
import logging
import threading
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

POLL_SECONDS = 5.0

Stamp = tuple[int, int]  # (size, time of last change in ns)


class FolderWatcher:
    """Tells which files have arrived, or changed, and are now complete.

    A file is reported once it has the same size and modification time at two polls in a row (a copy still in progress, or a scanner
    still writing, keeps changing), and not again until it changes. What is already there when the watcher starts is not "arriving":
    the first poll only takes note of it."""

    def __init__(self, list_files: Callable[[], list[Path]]):
        self._list = list_files
        self._started = False
        self._previous: dict[Path, Stamp] = {}   # what the last poll saw
        self._reported: dict[Path, Stamp] = {}   # what has been handed over, in the state it was handed over

    @staticmethod
    def _stamp(path: Path) -> Stamp | None:
        try:
            stat = path.stat()
        except OSError:  # gone since the listing, or not readable now: it will be seen again, or not
            return None
        return stat.st_size, stat.st_mtime_ns

    def poll(self) -> list[Path]:
        now: dict[Path, Stamp] = {}
        for path in self._list():
            stamp = self._stamp(path)
            if stamp is not None:
                now[path] = stamp
        if not self._started:
            self._started = True
            self._previous, self._reported = dict(now), dict(now)
            return []
        ready = [path for path, stamp in now.items() if self._reported.get(path) != stamp and self._previous.get(path) == stamp]
        for path in ready:
            self._reported[path] = now[path]
        self._previous = now
        self._reported = {path: stamp for path, stamp in self._reported.items() if path in now}  # a file that left is forgotten
        return sorted(ready)


def watch(list_files: Callable[[], list[Path]], on_arrival: Callable[[list[Path]], None], interval: float = POLL_SECONDS,
          stop: threading.Event | None = None) -> None:
    """Poll until `stop` is set, calling `on_arrival(paths)` when files have arrived. One failing poll or callback is logged and the
    watch goes on: it must outlive a share that disappears for a minute."""
    stop = stop or threading.Event()
    watcher = FolderWatcher(list_files)
    while not stop.is_set():
        try:
            arrived = watcher.poll()
            if arrived:
                on_arrival(arrived)
        except Exception:  # noqa: BLE001 - whatever went wrong, the next poll tries again
            log.exception("folder watch: this poll failed")
        stop.wait(interval)
