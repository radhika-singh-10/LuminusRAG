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
