"""Observability and traceability on LangChain's callback / tracer system.

Every question becomes one trace: a tree of runs that LangChain reports to
its callback handlers automatically. The LangGraph agent turn is the root run;
its nodes, the layer tools, the retriever, prompts, LLM calls (Qwen and the
Ollama judges) and output parsers are child runs.

Sinks:
- LocalTracer (default on, TRACE_LOCAL): a LangChain BaseTracer that writes
  each finished trace to SQLite (TRACE_DB_URL). Each run is stored as a span
  with id, parent, type, timing, status, error, tokens, and inputs/outputs.
  Nothing leaves the machine.
- LangSmith (opt-in, TRACE_LANGSMITH=true + LANGSMITH_API_KEY): LangChain's
  LangChainTracer with a LangSmith client whose hide_inputs / hide_outputs
  hooks redact PII before upload, because the raw question appears in the
  safety-check span. Don't set LANGSMITH_TRACING=true instead: that turns
  on LangChain's automatic tracer, which uploads without this redaction.

Both sinks redact PII (policies/pii.json detectors) and truncate payloads to
TRACE_MAX_CHARS. Traceability: the root run id is the trace id; the harness
stores it with each saved answer in the chat history, so an answer can be
traced back to the spans, documents and model calls that produced it.
"""
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import sqlalchemy as sa
from langchain_core.tracers.base import BaseTracer

from . import config
from .prompt_cache import is_cache_hit

_meta = sa.MetaData()
traces = sa.Table(
    "traces", _meta,
    sa.Column("trace_id", sa.String(36), primary_key=True),
    sa.Column("name", sa.String(200)),
    sa.Column("start", sa.String(40), index=True),
    sa.Column("latency_ms", sa.Integer),
    sa.Column("status", sa.String(16)),
    sa.Column("error", sa.Text),
    sa.Column("chat_id", sa.String(32), index=True),
    sa.Column("question", sa.Text),
    sa.Column("spans", sa.Integer),
    sa.Column("llm_calls", sa.Integer),
    sa.Column("tokens", sa.Integer),
    sa.Column("cache_hits", sa.Integer),
    sa.Column("tags", sa.Text),
    sa.Column("metadata", sa.Text),
)
spans = sa.Table(
    "spans", _meta,
    sa.Column("run_id", sa.String(36), primary_key=True),
    sa.Column("trace_id", sa.String(36), index=True),
    sa.Column("parent_id", sa.String(36)),
    sa.Column("depth", sa.Integer),
    sa.Column("seq", sa.Integer),
    sa.Column("name", sa.String(200)),
    sa.Column("run_type", sa.String(20)),
    sa.Column("start", sa.String(40)),
    sa.Column("latency_ms", sa.Integer),
    sa.Column("status", sa.String(16)),
    sa.Column("error", sa.Text),
    sa.Column("model", sa.String(120)),
    sa.Column("tokens_in", sa.Integer),
    sa.Column("tokens_out", sa.Integer),
    sa.Column("prompt_ms", sa.Integer),      # Ollama prompt evaluation time
    sa.Column("cache_hit", sa.Boolean),      # system prompt served from the prompt cache
    sa.Column("inputs", sa.Text),
    sa.Column("outputs", sa.Text),
)


@lru_cache(maxsize=1)
def _engine() -> sa.Engine:
    url = config.TRACE_DB_URL
    if url.startswith("sqlite:///"):
        from pathlib import Path

        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    eng = sa.create_engine(url)
    _meta.create_all(eng)
    # Add columns introduced after the tables were first created.
    insp = sa.inspect(eng)
    with eng.begin() as conn:
        for table in (traces, spans):
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    conn.execute(sa.text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} '
                                         f'{col.type.compile(eng.dialect)}'))
    return eng


# ---------- redaction ----------

def _serialize(value) -> str:
    try:
        return json.dumps(value, default=lambda o: getattr(o, "page_content", None) or str(o),
                          ensure_ascii=False)
    except Exception:
        return str(value)


def redact(value, limit: int | None = None) -> str:
    """JSON-ish text of a payload with PII redacted, truncated."""
    from .safety import redact_pii

    text = redact_pii(_serialize(value))[0]
    limit = limit or config.TRACE_MAX_CHARS
    return text if len(text) <= limit else text[:limit] + f"… [+{len(text) - limit} chars]"


def _redact_dict(d: dict) -> dict:
    """For LangSmith's hide_inputs / hide_outputs hooks: redact every value."""
    from .safety import redact_pii

    def walk(v):
        if isinstance(v, str):
            return redact_pii(v)[0]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [walk(x) for x in v]
        return v

    return walk(d or {})


# ---------- local tracer ----------

def _tokens(run) -> tuple[int | None, int | None]:
    """Prompt / completion tokens from an LLM run's output, if reported."""
    try:
        for gen in (run.outputs or {}).get("generations", [[]])[0]:
            usage = (gen.get("message", {}) or {}).get("kwargs", {}).get("usage_metadata") \
                or (gen.get("message", {}) or {}).get("usage_metadata")
            if usage:
                return usage.get("input_tokens"), usage.get("output_tokens")
        usage = ((run.outputs or {}).get("llm_output") or {}).get("token_usage") or {}
        if usage:
            return usage.get("prompt_tokens"), usage.get("completion_tokens")
    except Exception:
        pass
    return None, None


def _prompt_eval(run) -> tuple[int | None, int | None]:
    """(prompt_eval ms, prompt tokens) reported by Ollama for an LLM run."""
    try:
        for gen in (run.outputs or {}).get("generations", [[]])[0]:
            msg = gen.get("message", {}) or {}
            md = (msg.get("kwargs", {}) or {}).get("response_metadata") or msg.get("response_metadata") or {}
            if "prompt_eval_duration" in md:
                return round(md["prompt_eval_duration"] / 1e6), md.get("prompt_eval_count")
    except Exception:
        pass
    return None, None


def _model(run) -> str | None:
    params = (run.extra or {}).get("invocation_params", {}) or {}
    meta = (run.extra or {}).get("metadata", {}) or {}
    model = params.get("model") or params.get("model_name") or meta.get("ls_model_name")
    if not model and "HuggingFace" in (run.name or ""):
        model = config.HF_LLM_MODEL  # the local HF pipeline doesn't report its model id
    return model


def _ms(run) -> int | None:
    if run.start_time and run.end_time:
        return int((run.end_time - run.start_time).total_seconds() * 1000)
    return None


class LocalTracer(BaseTracer):
    """Writes each finished trace (root run with its children) to SQLite."""

    name: str = "luminus_local_tracer"

    def _persist_run(self, run) -> None:
        try:
            self._write(run)
        except Exception as e:  # tracing must never break answering
            print(f"[trace] could not save trace {run.id}: {type(e).__name__}: {e}")

    def _write(self, root) -> None:
        rows, seq = [], [0]

        def walk(run, depth):
            is_llm = run.run_type in ("llm", "chat_model")
            tin, tout = _tokens(run) if is_llm else (None, None)
            pms, ptok = _prompt_eval(run) if is_llm else (None, None)
            rows.append({
                "run_id": str(run.id), "trace_id": str(root.id),
                "parent_id": str(run.parent_run_id) if run.parent_run_id else None,
                "depth": depth, "seq": seq[0], "name": run.name[:200], "run_type": run.run_type,
                "start": run.start_time.isoformat() if run.start_time else None,
                "latency_ms": _ms(run), "status": "error" if run.error else "ok",
                "error": (run.error or "")[:2000] or None, "model": _model(run),
                "tokens_in": tin, "tokens_out": tout, "prompt_ms": pms,
                "cache_hit": is_cache_hit(pms, ptok or tin),
                "inputs": redact(run.inputs), "outputs": redact(run.outputs),
            })
            seq[0] += 1
            for child in sorted(run.child_runs, key=lambda r: r.start_time or datetime.min):
                walk(child, depth + 1)

        walk(root, 0)
        meta = (root.extra or {}).get("metadata", {}) or {}
        question = (root.inputs or {}).get("raw_question") or (root.inputs or {}).get("question")
        llm = [r for r in rows if r["run_type"] in ("llm", "chat_model")]
        tokens = sum((r["tokens_in"] or 0) + (r["tokens_out"] or 0) for r in llm) or None
        errors = [r for r in rows if r["status"] == "error"]
        with _engine().begin() as conn:
            conn.execute(spans.delete().where(spans.c.trace_id == str(root.id)))
            conn.execute(traces.delete().where(traces.c.trace_id == str(root.id)))
            conn.execute(traces.insert().values(
                trace_id=str(root.id), name=root.name[:200],
                start=root.start_time.isoformat() if root.start_time else None,
                latency_ms=_ms(root), status="error" if errors else "ok",
                error=(errors[0]["error"] if errors else None),
                chat_id=meta.get("chat_id"), question=redact(question, 300) if question else None,
                spans=len(rows), llm_calls=len(llm), tokens=tokens,
                cache_hits=sum(bool(r["cache_hit"]) for r in llm),
                tags=json.dumps(root.tags or []), metadata=redact(meta, 1000)))
            conn.execute(spans.insert(), rows)


# ---------- callbacks ----------

@lru_cache(maxsize=1)
def _langsmith_tracer():
    from langchain_core.tracers.langchain import LangChainTracer
    from langsmith import Client

    client = Client(hide_inputs=_redact_dict, hide_outputs=_redact_dict)
    return LangChainTracer(project_name=config.LANGSMITH_PROJECT, client=client)


def get_callbacks() -> list:
    """Tracers for one request (a new LocalTracer per request: it holds run state)."""
    import os

    cbs = []
    if config.TRACE_LOCAL:
        cbs.append(LocalTracer())
    if config.TRACE_LANGSMITH and os.getenv("LANGSMITH_API_KEY"):
        cbs.append(_langsmith_tracer())
    return cbs


def trace_config(name: str, metadata: dict | None = None, tags: list[str] | None = None) -> dict:
    """RunnableConfig for a traced root run; its run_id is the trace id."""
    return {"callbacks": get_callbacks(), "run_id": uuid.uuid4(), "run_name": name,
            "tags": ["luminusrag", *(tags or [])], "metadata": metadata or {}}


@contextmanager
def traced(name: str, inputs: dict, metadata: dict | None = None, tags: list[str] | None = None):
    """Trace code that is not itself a Runnable (e.g. GuardedPipeline.events).
    Yields {"trace_id", "context", "outputs"}: run the work with
    out["context"].run(fn, ...) so the Runnables it calls become children of
    this root run, and set out["outputs"] to record the result.

    (LangChain's trace_as_chain_group drops custom callbacks unless LangSmith
    env tracing is on, so the root run is started on a CallbackManager directly.)"""
    from langchain_core.callbacks.manager import CallbackManager
    from langchain_core.runnables.config import set_config_context

    cbs = get_callbacks()
    out: dict = {"trace_id": None, "outputs": None, "context": None}
    if not cbs:
        yield out
        return
    run_id = uuid.uuid4()
    out["trace_id"] = str(run_id)
    cm = CallbackManager.configure(inheritable_callbacks=cbs, inheritable_tags=["luminusrag", *(tags or [])],
                                   inheritable_metadata=metadata or {})
    run = cm.on_chain_start({"name": name}, inputs, run_id=run_id, name=name)
    try:
        with set_config_context({"callbacks": run.get_child()}) as ctx:
            out["context"] = ctx  # run work via ctx.run(...) so child runs attach here
            yield out
    except BaseException as e:
        run.on_chain_error(e)
        raise
    else:
        run.on_chain_end(out["outputs"] or {})


# ---------- reading ----------

def list_traces(limit: int = 50, chat_id: str | None = None) -> list[dict]:
    q = sa.select(traces).order_by(traces.c.start.desc()).limit(limit)
    if chat_id:
        q = q.where(traces.c.chat_id == chat_id)
    with _engine().connect() as conn:
        return [dict(r) for r in conn.execute(q).mappings()]


def get_trace(trace_id: str) -> dict | None:
    with _engine().connect() as conn:
        t = conn.execute(sa.select(traces).where(traces.c.trace_id.startswith(trace_id))).mappings().first()
        if not t:
            return None
        rows = conn.execute(sa.select(spans).where(spans.c.trace_id == t["trace_id"])
                            .order_by(spans.c.seq)).mappings().all()
    return {**dict(t), "spans": [dict(r) for r in rows]}


def span_stats(limit_traces: int = 500) -> list[dict]:
    """Per span name: count, p50 / p95 latency, error rate, tokens (recent traces)."""
    import statistics

    recent = [t["trace_id"] for t in list_traces(limit_traces)]
    if not recent:
        return []
    with _engine().connect() as conn:
        rows = conn.execute(sa.select(spans.c.name, spans.c.run_type, spans.c.latency_ms, spans.c.status,
                                      spans.c.tokens_in, spans.c.tokens_out, spans.c.prompt_ms,
                                      spans.c.cache_hit)
                            .where(spans.c.trace_id.in_(recent))).all()
    by: dict[tuple, list] = {}
    for r in rows:
        by.setdefault((r.name, r.run_type), []).append(r)
    out = []
    for (name, kind), rs in by.items():
        lat = sorted(r.latency_ms for r in rs if r.latency_ms is not None)
        out.append({
            "name": name, "type": kind, "count": len(rs),
            "p50_ms": statistics.median(lat) if lat else None,
            "p95_ms": lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else None,
            "error_rate": round(sum(r.status == "error" for r in rs) / len(rs), 3),
            "tokens": sum((r.tokens_in or 0) + (r.tokens_out or 0) for r in rs) or None,
            "prompt_ms_p50": statistics.median(pm) if (pm := [r.prompt_ms for r in rs if r.prompt_ms is not None])
            else None,
            "cache_hit_rate": round(sum(bool(r.cache_hit) for r in hits) / len(hits), 3)
            if (hits := [r for r in rs if r.cache_hit is not None]) else None,
        })
    return sorted(out, key=lambda x: -(x["p95_ms"] or 0))


def purge(days: int | None = None) -> int:
    """Delete traces older than TRACE_RETENTION_DAYS. Returns traces removed."""
    days = config.TRACE_RETENTION_DAYS if days is None else days
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _engine().begin() as conn:
        old = [r.trace_id for r in conn.execute(sa.select(traces.c.trace_id).where(traces.c.start < cutoff))]
        if old:
            conn.execute(spans.delete().where(spans.c.trace_id.in_(old)))
            conn.execute(traces.delete().where(traces.c.trace_id.in_(old)))
    return len(old)
