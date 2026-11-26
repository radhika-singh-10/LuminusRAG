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
# Copyright (c) Lineaje, Inc. All rights reserved.
# Lineaje UnifAI guardrail  version=2.0.0-alpha
def _lineaje_gr_load(_f):
    """Lineaje-added: load gr_stub_client.py beside _f or in one of its 7 parent folders. Missing or broken:
    a pass-through client and ONE warning per process (GR_REQUIRE_CLIENT=1: ImportError instead)."""
    import sys, os, logging, importlib.util as u, pathlib
    n = "_lineaje_gr_stub_client"
    if n in sys.modules: return sys.modules[n]
    h = pathlib.Path(_f or ".").resolve().parent
    d = [h, *h.parents][:8]
    p = next((x / "gr_stub_client.py" for x in d if (x / "gr_stub_client.py").is_file()), None)
    try:
        s = u.spec_from_file_location(n, p) if p else None
        if s is None: raise FileNotFoundError("gr_stub_client.py")
        m = sys.modules[n] = u.module_from_spec(s); s.loader.exec_module(m); return m
    except Exception as e:
        sys.modules.pop(n, None)
        w = ("gr_stub_client.py not found for %s (searched: %s)" % (_f or "<no __file__>", ", ".join(map(str, d)))
             if p is None else "%s failed to load (%s%s)" % (p, type(e).__name__,
                                                          " line %s" % e.lineno if isinstance(e, SyntaxError) else ""))
        w = ("Lineaje guardrail NOT active: " + w + ". Calls pass through unchecked; set GR_REQUIRE_CLIENT=1 to fail "
             "instead. Each deploy unit needs gr_stub_client.py beside its code and GR_SERVICE_URL plus credentials as "
             "environment variables.")
        if os.environ.get("GR_REQUIRE_CLIENT", "").strip() == "1": raise ImportError(w) from (None if p is None else e)
        z = sys.__dict__.setdefault("_lineaje_gr_null", __import__('types').SimpleNamespace(STUB_API=999999, GuardrailUnavailableError=type('GuardrailUnavailableError', (PermissionError,), {}), SiteDescriptor=lambda *a, **k: None, new_interaction_id=lambda *a, **k: None, enforce=lambda _s, _p, *a, **k: _p, enforce_request=lambda _s, _p, *a, **k: _p, enforce_reply=lambda _s, _p, *a, **k: _p, _lineaje_seen=set()))
        k = "missing" if p is None else (str(p), type(e).__name__)
        if k not in z._lineaje_seen:
            z._lineaje_seen.add(k); g = logging.getLogger("lineaje.guardrail"); g.log(30 if p is None else 40, w)
            if g.hasHandlers(): sys.stderr.write(w + "\n")
        return z
__import__("sys").__dict__.setdefault("_lineaje_gr_load_v1", _lineaje_gr_load)
del _lineaje_gr_load
def _lineaje_load_gr_client():
    """Lineaje-added: this file's gr_stub_client.py (the loader _lineaje_gr_load registered)."""
    return __import__("sys").__dict__["_lineaje_gr_load_v1"](globals().get("__file__"))
if __import__("os").environ.get("GR_REQUIRE_CLIENT", "").strip() == "1": __import__("sys").__dict__["_lineaje_gr_load_v1"](globals().get("__file__"))

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
            # LINEAJE: runtime guardrail checks `batch` as it flows from the agent to the user interface, before it leaves the application (in Debouncer.ready).
            #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
            #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `batch` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
            #   Do not remove without review. site_id='site:sha256:82e4928511bedf346cd8fd15638f7a05606ce6b03ec86fe98c141a0fdf884bee'
            _gr_client = _lineaje_load_gr_client()
            _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:82e4928511bedf346cd8fd15638f7a05606ce6b03ec86fe98c141a0fdf884bee', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/watcher.py', 'line': 57, 'function': 'Debouncer.ready'}, 'file': 'rag/watcher.py', 'line': 57, 'function': 'ready', 'agent_name': 'Debouncer', 'agent_name_source': 'inferred_from_class', 'not_on_graph': True})
            try:
                batch = _gr_client.enforce(_gr_site, batch, content_type='text/plain')
            except _gr_client.GuardrailUnavailableError:
                pass
            except PermissionError:
                pass
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
    # LINEAJE: runtime guardrail checks `out` as it flows from the agent to the user interface, before it leaves the application (in snapshot).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `out` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:0d735497c7cf2bad3afac76324270183f7e9faab61ca25b8a37507cbc57dcd61'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:0d735497c7cf2bad3afac76324270183f7e9faab61ca25b8a37507cbc57dcd61', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/watcher.py', 'line': 73, 'function': 'snapshot'}, 'file': 'rag/watcher.py', 'line': 73, 'function': 'snapshot', 'agent_name': 'snapshot', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        out = _gr_client.enforce(_gr_site, out, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
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
        # LINEAJE: runtime guardrail checks `result` as it flows from the agent to the user interface, before it leaves the application (in Watcher.sync).
        #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
        #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `result` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
        #   Do not remove without review. site_id='site:sha256:4dd34566fa71448a7a445eff777a0e167216d5ed85f2b9180445c1f1d19e7447'
        _gr_client = _lineaje_load_gr_client()
        _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:4dd34566fa71448a7a445eff777a0e167216d5ed85f2b9180445c1f1d19e7447', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/watcher.py', 'line': 137, 'function': 'Watcher.sync'}, 'file': 'rag/watcher.py', 'line': 137, 'function': 'sync', 'agent_name': 'Watcher', 'agent_name_source': 'inferred_from_class', 'not_on_graph': True})
        try:
            result = _gr_client.enforce(_gr_site, result, content_type='text/plain')
        except _gr_client.GuardrailUnavailableError:
            pass
        except PermissionError:
            pass
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
