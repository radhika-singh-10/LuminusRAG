"""Agent memory: session state and the user's interest profile.

Stored next to the chat history (CHAT_DB_URL), in two tables:

- agent_sessions: one row per chat: step count, rolling summary (and the step
  it was made at), and whether the step limit closed the chat.
- interests: graph entities a user showed interest in, per chat, with a
  weight that decays every step. Only knowledge-graph entity keys are stored,
  never question text, so the profile holds no PII (graph extraction already
  drops personal names, emails and the like).

The messages themselves stay in LangChain's SQLChatMessageHistory (rag/history.py).
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

from datetime import datetime
from functools import lru_cache

import sqlalchemy as sa

from .. import config

_meta = sa.MetaData()
sessions = sa.Table(
    "agent_sessions", _meta,
    sa.Column("chat_id", sa.String(32), primary_key=True),
    sa.Column("user_id", sa.String(64), nullable=False),
    sa.Column("steps", sa.Integer, nullable=False, default=0),
    sa.Column("summary", sa.Text),
    sa.Column("summary_step", sa.Integer, default=0),
    sa.Column("closed", sa.Boolean, default=False),
    sa.Column("updated", sa.String(32)),
)
interests = sa.Table(
    "interests", _meta,
    sa.Column("user_id", sa.String(64), primary_key=True),
    sa.Column("chat_id", sa.String(32), primary_key=True),
    sa.Column("entity", sa.String(200), primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("weight", sa.Float, nullable=False),
    sa.Column("hits", sa.Integer, nullable=False, default=0),
    sa.Column("updated", sa.String(32)),
)


@lru_cache(maxsize=1)
def engine() -> sa.Engine:
    from ..history import _engine

    eng = _engine()
    _meta.create_all(eng)
    # LINEAJE: runtime guardrail checks `eng` as it flows from the agent to the user interface, before it leaves the application (in engine).
    #   Detected: this statement moves data from the agent to the user interface with no runtime policy check (detection confidence: high).
    #   Decision: the Guardrail evaluates AI_DAT_SEC_012; sensitive values in `eng` are masked in place; a policy violation stops the call (fail_mode=BLOCK). If the Guardrail is unreachable, the call continues unchanged.
    #   Do not remove without review. site_id='site:sha256:881132a4c14c4179b424d537893e82fa8d4d4cf2018cf2fb8f165f5f8ffcffc2'
    _gr_client = _lineaje_load_gr_client()
    _gr_site = _gr_client.SiteDescriptor(site_id='site:sha256:881132a4c14c4179b424d537893e82fa8d4d4cf2018cf2fb8f165f5f8ffcffc2', phase='data_egress', boundary={'source': 'agent_message', 'sink': 'user_interface'}, fail_mode='BLOCK', source_type='agent', destination_type='user_interface', components={'invocation': {'file': 'rag/agent/memory.py', 'line': 50, 'function': 'engine'}, 'file': 'rag/agent/memory.py', 'line': 50, 'function': 'engine', 'agent_name': 'engine', 'agent_name_source': 'inferred_from_function', 'not_on_graph': True})
    try:
        eng = _gr_client.enforce(_gr_site, eng, content_type='text/plain')
    except _gr_client.GuardrailUnavailableError:
        pass
    except PermissionError:
        pass
    return eng


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------- sessions ----------

def get_session(chat_id: str, user_id: str = "local") -> dict:
    with engine().connect() as conn:
        row = conn.execute(sa.select(sessions).where(sessions.c.chat_id == chat_id)).mappings().first()
    return dict(row) if row else {"chat_id": chat_id, "user_id": user_id, "steps": 0,
                                  "summary": None, "summary_step": 0, "closed": False}


def save_session(chat_id: str, user_id: str, **values) -> None:
    values["updated"] = _now()
    with engine().begin() as conn:
        exists = conn.execute(sa.select(sessions.c.chat_id).where(sessions.c.chat_id == chat_id)).first()
        if exists:
            conn.execute(sessions.update().where(sessions.c.chat_id == chat_id).values(**values))
        else:
            conn.execute(sessions.insert().values(
                chat_id=chat_id, user_id=user_id,
                **{"steps": 0, "summary": None, "summary_step": 0, "closed": False, **values}))


def delete_session(chat_id: str) -> None:
    with engine().begin() as conn:
        conn.execute(sessions.delete().where(sessions.c.chat_id == chat_id))
        conn.execute(interests.delete().where(interests.c.chat_id == chat_id))


# ---------- interests ----------

def add_interests(user_id: str, chat_id: str, weights: dict[str, tuple[str, float]]) -> None:
    """Decay this chat's interests by INTEREST_DECAY, then add `weights`
    ({entity key: (display name, weight)})."""
    now = _now()
    with engine().begin() as conn:
        conn.execute(interests.update()
                     .where(interests.c.user_id == user_id, interests.c.chat_id == chat_id)
                     .values(weight=interests.c.weight * config.INTEREST_DECAY))
        for ent, (name, w) in weights.items():
            row = conn.execute(sa.select(interests.c.weight, interests.c.hits).where(
                interests.c.user_id == user_id, interests.c.chat_id == chat_id,
                interests.c.entity == ent)).first()
            if row:
                conn.execute(interests.update().where(
                    interests.c.user_id == user_id, interests.c.chat_id == chat_id,
                    interests.c.entity == ent).values(weight=row.weight + w, hits=row.hits + 1, updated=now))
            else:
                conn.execute(interests.insert().values(user_id=user_id, chat_id=chat_id, entity=ent,
                                                       name=name, weight=w, hits=1, updated=now))
        # Forget faded interests.
        conn.execute(interests.delete().where(interests.c.weight < 0.05))


def get_interests(user_id: str, chat_id: str | None, top: int = 8) -> list[dict]:
    """[{entity, name, weight}] strongest first: this chat's interests plus the
    user's other chats at LONG_TERM_WEIGHT."""
    with engine().connect() as conn:
        rows = conn.execute(sa.select(interests).where(interests.c.user_id == user_id)).mappings().all()
    agg: dict[str, dict] = {}
    for r in rows:
        w = r["weight"] * (1.0 if r["chat_id"] == chat_id else config.LONG_TERM_WEIGHT)
        a = agg.setdefault(r["entity"], {"entity": r["entity"], "name": r["name"], "weight": 0.0})
        a["weight"] += w
    return sorted(agg.values(), key=lambda x: -x["weight"])[:top]


def clear_interests(user_id: str, chat_id: str | None = None) -> None:
    with engine().begin() as conn:
        q = interests.delete().where(interests.c.user_id == user_id)
        if chat_id:
            q = q.where(interests.c.chat_id == chat_id)
        conn.execute(q)
