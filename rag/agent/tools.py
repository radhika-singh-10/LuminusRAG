"""Every layer of the agent harness as a LangChain tool.

Each tool is a typed StructuredTool (name, description, argument schema), so
the layers can be called by the harness, inspected, tested on their own, or
handed to a tool-calling agent. The harness (rag/agent/harness.py) calls
them in a fixed order: safety must run before anything sees the question, so
the order is not left to a model.

Layer           Tool                 Does
--------------  -------------------  --------------------------------------------
memory          recall_memory        chat messages, session (steps, rolling summary), interests
safety          safety_check         policy guard: prompt injection + PII (regex + LLM judge)
context         build_context        recent turns + rolling summary + interests, within budget
context         contextualize        rewrite a follow-up into a standalone question
safety          intent_check         only AI questions; action requests refused
retrieval       retrieve             personalized GraphRAG retrieval (ANN + personalized PageRank)
generation      generate_answer      answer from the passages (the harness streams it instead)
personalization update_interests     learn interests from the answered question
followups       suggest_followups    up to 3 grounded, novel, safe follow-up questions
summarization   summarize_session    rolling summary of turns older than the recent window
eval            evaluate_turn        online quality signals for one turn
memory          save_turn            persist the exchange (PII-redacted) and session state
"""
from functools import lru_cache

from langchain_core.documents import Document
from langchain_core.tools import tool

from .. import config


@lru_cache(maxsize=1)
def _ollama():
    from ..prompt_cache import chat_ollama

    return chat_ollama(config.AGENT_MODEL, temperature=0, num_predict=300)


# ---------- memory ----------

@tool
def recall_memory(chat_id: str, user_id: str = "local") -> dict:
    """Load the chat's messages, its session state (step count, rolling summary,
    closed flag) and the user's interest profile."""
    from ..history import load_messages
    from .memory import get_interests, get_session

    return {"messages": load_messages(chat_id),
            "session": get_session(chat_id, user_id),
            "interests": get_interests(user_id, chat_id) if config.PERSONALIZE else []}


@tool
def save_turn(chat_id: str, user_id: str, question: str, answer: str, step: int,
              closed: bool, meta: str = "", sources: list[dict] | None = None,
              followups: list[dict] | None = None, trace_id: str | None = None) -> dict:
    """Persist one exchange (question already PII-redacted) and the session's step
    count. trace_id links the saved answer to its trace (observability)."""
    from ..history import add_exchange
    from .memory import save_session

    add_exchange(chat_id, question, answer, meta, sources,
                 extra={"followups": followups or [], "step": step, "trace_id": trace_id})
    save_session(chat_id, user_id, steps=step, closed=closed)
    return {"saved": True, "step": step, "closed": closed}


# ---------- safety ----------

@tool
def safety_check(text: str, use_llm: bool = True):
    """Check text against the prompt-injection and PII policies. Returns a
    GuardResult: safe flag, rule, and the PII-redacted text."""
    from ..policy import check_query

    return check_query(text, use_llm=use_llm)


@tool
def intent_check(question: str, recent: list[str] | None = None):
    """Classify the question's intent; only AI-related questions are allowed.
    `recent` (earlier questions in the chat) disambiguates terms like "guardrails"."""
    from ..intent import classify_intent

    return classify_intent(question, recent)


# ---------- context ----------

@tool
def build_context(messages: list[dict], summary: str | None = None,
                  interests: list[dict] | None = None, max_chars: int = 3000) -> dict:
    """Assemble the conversation context: the last HISTORY_TURNS exchanges, the
    rolling summary of older ones, the interest names, and every question asked
    so far (for follow-up novelty). Older text is trimmed first to fit max_chars."""
    recent = messages[-2 * config.HISTORY_TURNS:]
    while recent and sum(len(m["content"]) for m in recent) > max_chars:
        recent = recent[2:]
    return {
        "recent": recent,
        "summary": (summary or "")[:800] or None,
        "interests": [i["name"] for i in interests or []],
        "asked": [m["content"] for m in messages if m["role"] == "user"],
    }


@tool
def contextualize(question: str, recent: list[dict], summary: str | None = None) -> str:
    """Rewrite a follow-up ("what about its cost?") into a standalone question
    using the recent turns and rolling summary. Standalone questions pass through."""
    from ..followup import standalone_question

    return standalone_question(question, recent, summary)


# ---------- retrieval and generation ----------

@tool
def retrieve(question: str, interests: list[dict] | None = None) -> list[Document]:
    """Personalized GraphRAG retrieval: ANN vector search nudged toward the
    user's interests, reranked with personalized PageRank over the knowledge graph."""
    from .personalize import PersonalizedRetriever

    return PersonalizedRetriever(interests=interests or [], k=config.TOP_K,
                                 graph_k=config.GRAPH_K).invoke(question)


@tool
def generate_answer(question: str, docs: list[Document]) -> str:
    """Answer the question from the passages, citing them as [n]. (The harness
    streams the answer through GuardedPipeline.answer_events instead.)"""
    from ..chain import build_answer_chain, get_llm

    return build_answer_chain(get_llm()).invoke({"context": docs, "question": question})


# ---------- personalization ----------

@tool
def update_interests(user_id: str, chat_id: str, question: str, docs: list[Document]) -> list[dict]:
    """Learn from an answered question: decay old interests, add the graph
    entities in the question (and, weaker, in the answering chunks)."""
    from .memory import add_interests, get_interests
    from .personalize import interests_from_turn

    if config.PERSONALIZE:
        add_interests(user_id, chat_id, interests_from_turn(question, docs))
    return get_interests(user_id, chat_id) if config.PERSONALIZE else []


# ---------- follow-ups ----------

@tool
def suggest_followups(question: str, answer: str, docs: list[Document],
                      interests: list[dict] | None = None, asked: list[str] | None = None,
                      limit: int | None = None) -> list[dict]:
    """Up to AGENT_MAX_FOLLOWUPS follow-up questions: answerable from the store,
    not already asked, safe, and ranked toward the user's interests."""
    from .followups import suggest

    return suggest(question, answer, docs, interests or [], asked or [], limit)


# ---------- summarization ----------

@tool
def summarize_session(messages: list[dict], previous: str | None = None) -> str | None:
    """Rolling summary of the turns older than the recent window, so long chats
    keep their earlier context in a few lines. Refused questions are marked,
    never answered by the summarizer."""
    from ..history import summarize_messages

    older = messages[:-2 * config.HISTORY_TURNS]
    if len(older) < 2:
        return previous
    try:
        return summarize_messages(older, _ollama())
    except Exception:  # Ollama unavailable: keep the previous summary
        return previous


# ---------- eval ----------

@tool
def evaluate_turn(question: str, answer: str, docs: list[Document],
                  local_score: float | None = None, followups: list[dict] | None = None) -> dict:
    """Online quality signals for one turn: retrieval score, refusal, citation
    validity, lexical grounding in the passages, follow-up count and
    answerability, and (AGENT_ONLINE_NLI) NLI faithfulness."""
    from ..eval.metrics import citation_metrics, is_refusal, tokens

    refused = is_refusal(answer)
    ctx = [d.page_content for d in docs]
    ctx_tokens = set(t for c in ctx for t in tokens(c))
    ans_tokens = [t for t in tokens(answer) if len(t) > 3]
    grounding = (sum(t in ctx_tokens for t in ans_tokens) / len(ans_tokens)) if ans_tokens else None
    out = {
        "retrieval_score": local_score,
        "refused": refused,
        **citation_metrics(answer, len(docs)),
        "lexical_grounding": grounding,
        "n_followups": len(followups or []),
        "followup_answerability": (sum(f["answerability"] for f in followups) / len(followups))
        if followups else None,
    }
    if config.AGENT_ONLINE_NLI and not refused and ctx:
        from ..eval.truthfulness import get_scorer

        out["faithfulness"] = get_scorer().faithfulness(answer, ctx)["faithfulness"]
    return out


TOOLS = [recall_memory, safety_check, build_context, contextualize, intent_check, retrieve,
         generate_answer, update_interests, suggest_followups, summarize_session,
         evaluate_turn, save_turn]
