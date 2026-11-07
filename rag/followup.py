"""History-aware retrieval: turn a follow-up into a standalone question.

"What is HNSW?" ... "What is its main cost?" -> "What is the main cost of HNSW?"

This is LangChain's history-aware retriever pattern (contextualize the
question with the chat history, then retrieve), with worked examples in the
prompt because the small local model otherwise returns follow-ups unchanged. The rewrite uses the local
Ollama model and runs only when the question looks like a follow-up
(pronouns, "what about ...", "the other ..."), so standalone questions
pass through unchanged. History messages are the stored, PII-redacted chat.
"""
import re
from functools import lru_cache

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from . import config

CONTEXTUALIZE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You rewrite the user's latest question so it can be understood without the "
     "conversation. Replace pronouns such as it, its, they, this, or that with the "
     "thing they refer to in the conversation. Do NOT answer the question. If the "
     "question is already standalone, return it unchanged. Reply with the rewritten "
     "question only.\n\n"
     "Examples:\n"
     "Conversation: User: What is LoRA? / Assistant: LoRA is a parameter-efficient "
     "fine-tuning method.\n"
     "Latest question: How much memory does it save?\n"
     "Rewritten: How much memory does LoRA save?\n\n"
     "Conversation: User: Which vector databases exist? / Assistant: Chroma, FAISS "
     "and Qdrant.\n"
     "Latest question: What about pgvector?\n"
     "Rewritten: Is pgvector a vector database, and how does it compare to Chroma, "
     "FAISS and Qdrant?\n\n"
     "Conversation: User: What is RLHF? / Assistant: Reinforcement learning from "
     "human feedback.\n"
     "Latest question: What is a context window?\n"
     "Rewritten: What is a context window?"),
    ("human", "Conversation: {conversation}\nLatest question: {question}\nRewritten:"),
])

_FOLLOWUP = re.compile(
    r"\b(?:it|its|it's|they|them|their|this|that|these|those|he|she|his|her|the former|"
    r"the latter|the same|what about|how about|and what|also|instead|compared to that|"
    r"the other|another one|which one|the two|both|either|neither)\b", re.IGNORECASE)


def looks_like_followup(question: str) -> bool:
    return bool(_FOLLOWUP.search(question))


@lru_cache(maxsize=1)
def _contextualizer():
    from langchain_ollama import ChatOllama

    llm = ChatOllama(model=config.GUARD_MODEL, base_url=config.OLLAMA_BASE_URL,
                     temperature=0, num_predict=80)
    return CONTEXTUALIZE_PROMPT | llm | StrOutputParser()


def to_messages(history: list[dict], turns: int | None = None) -> list:
    """UI/CLI history ({role, content}) -> the last `turns` Q&A pairs as LangChain messages."""
    turns = turns or config.HISTORY_TURNS
    msgs = [HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(m["content"][:600])
            for m in history if m.get("content")]
    return msgs[-turns * 2:]


def conversation_text(history: list[dict], turns: int | None = None) -> str:
    return " / ".join(
        f"{'User' if isinstance(m, HumanMessage) else 'Assistant'}: {' '.join(m.content.split())}"
        for m in to_messages(history, turns))


def standalone_question(question: str, history: list[dict] | None) -> str:
    """Rewrite a follow-up using the history; otherwise return the question as is."""
    if not (config.HISTORY_AWARE and history and looks_like_followup(question)):
        return question
    try:
        out = _contextualizer().invoke({"conversation": conversation_text(history), "question": question})
    except Exception:  # Ollama unavailable: fall back to the original question
        return question
    out = out.strip().strip('"').strip()
    out = out.splitlines()[0].strip() if out else ""
    out = re.sub(r"^(?:rewritten|standalone question)\s*:\s*", "", out, flags=re.IGNORECASE).strip('" ')
    # Guard against the model answering instead of rewriting.
    if not out or len(out) > max(200, 4 * len(question)) or not out.endswith("?"):
        return question
    return out
