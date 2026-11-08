"""Debounced re-indexing of the data folder.

Editors save a file several times while you work, and a sync takes a while
(sanitize, chunk, embed, graph). Indexing every save would build a version
per keystroke burst. Instead:

1. The watcher polls DATA_DIR every WATCH_POLL_SECONDS and records added,
   modified (mtime or size) and deleted files.
2. Every change restarts a quiet timer. Only when no file has changed for
   DEBOUNCE_SECONDS (default 10 s) is the batch synced, so a burst of saves
   becomes one sync. DEBOUNCE_MAX_SECONDS caps the wait if changes never stop.
3. The sync runs ingest(only=batch): for each changed file the chunks are
   rebuilt and diffed by content hash against the live version (unchanged /
   added / removed chunks), and only then is a new version built and
   activated, embedding only the added chunks. Deleted files are retired;
   old chunks are garbage-collected in the background.

Chunks never overlap, so an edit changes only the chunks it touches and the
diff stays small.
"""
import threading
import time
from pathlib import Path

from . import config


class Debouncer:
    """Collects changed paths; releases them once nothing changed for `quiet`
    seconds (or `max_wait` after the first change)."""

    def __init__(self, quiet: float, max_wait: float | None = None, clock=time.monotonic):
        self.quiet, self.max_wait, self.clock = quiet, max_wait, clock
        self.pending: dict[str, str] = {}   # path -> last change kind
        self.first: float | None = None
        self.last: float | None = None

    def touch(self, path: str, kind: str = "modified") -> None:
        now = self.clock()
        self.pending[path] = kind
        self.first = self.first if self.first is not None else now
        self.last = now

    def remaining(self) -> float | None:
        """Seconds until the batch is released (None if nothing is pending)."""
        if not self.pending:
            return None
        now = self.clock()
        wait = self.quiet - (now - self.last)
        if self.max_wait is not None:
            wait = min(wait, self.max_wait - (now - self.first))
        return max(0.0, wait)

    def ready(self) -> dict[str, str] | None:
        if self.pending and self.remaining() == 0:
            batch, self.pending, self.first, self.last = self.pending, {}, None, None
            return batch
        return None


def snapshot(data_dir: Path) -> dict[str, tuple[int, int]]:
    """{absolute path: (mtime_ns, size)} for supported files."""
    from .ingest import SUPPORTED

    out = {}
    for p in data_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED and not p.name.startswith("."):
            try:
                st = p.stat()
            except FileNotFoundError:
                continue
            out[str(p.resolve())] = (st.st_mtime_ns, st.st_size)
    return out


class Watcher:
    """Polls the data folder and runs debounced, versioned syncs.

    on_event(event, info) receives:
      "change"     {path, kind, pending, sync_in}
      "sync_start" {files: {path: kind}}
      ingest events ("diff", "split", "activated", ...)
      "sync_done"  {files, stats, seconds}
      "sync_error" {error}
    """

    def __init__(self, data_dir: Path | None = None, quiet: float | None = None,
                 max_wait: float | None = None, poll: float | None = None, on_event=None):
        self.data_dir = Path(data_dir or config.DATA_DIR)
        self.debouncer = Debouncer(config.DEBOUNCE_SECONDS if quiet is None else quiet,
                                   config.DEBOUNCE_MAX_SECONDS if max_wait is None else max_wait)
        self.poll = config.WATCH_POLL_SECONDS if poll is None else poll
        self.on_event = on_event or (lambda e, i: None)
        self.state = snapshot(self.data_dir)
        self.history: list[dict] = []     # completed syncs (newest last)
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None

    def _detect(self) -> None:
        now = snapshot(self.data_dir)
        for path in now.keys() - self.state.keys():
            self._changed(path, "added")
        for path in self.state.keys() - now.keys():
            self._changed(path, "deleted")
        for path in now.keys() & self.state.keys():
            if now[path] != self.state[path]:
                self._changed(path, "modified")
        self.state = now

    def _changed(self, path: str, kind: str) -> None:
        self.debouncer.touch(path, kind)
        self.on_event("change", {"path": path, "kind": kind, "pending": len(self.debouncer.pending),
                                 "sync_in": self.debouncer.remaining()})

    def step(self) -> dict | None:
        """Poll once; run a sync if the debounce window has passed."""
        self._detect()
        batch = self.debouncer.ready()
        if not batch:
            return None
        return self.sync(batch)

    def sync(self, batch: dict[str, str]) -> dict:
        from .ingest import ingest

        self.on_event("sync_start", {"files": batch})
        t0 = time.time()
        try:
            stats = ingest(progress=self.on_event, only=set(batch))
        except Exception as e:
            self.on_event("sync_error", {"error": f"{type(e).__name__}: {e}"})
            return {"error": str(e)}
        result = {"files": batch, "stats": stats, "seconds": round(time.time() - t0, 1),
                  "finished": time.strftime("%H:%M:%S")}
        self.history.append(result)
        self.on_event("sync_done", result)
        return result

    def run(self) -> None:
        while not self._stop.is_set():
            self.step()
            self._stop.wait(self.poll)

    def start(self) -> "Watcher":
        if not (self.thread and self.thread.is_alive()):
            self._stop.clear()
            self.thread = threading.Thread(target=self.run, name="data-watcher", daemon=True)
            self.thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
