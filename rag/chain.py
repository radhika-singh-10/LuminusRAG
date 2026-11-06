"""Retrieval-augmented generation chain (LCEL) with source citations."""
from functools import lru_cache

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableParallel

from . import config
from .store import get_retriever

REFUSAL = "I don't know based on the provided documents."

PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You answer questions using only the provided context. Be concise. "
            f'If the context does not contain the answer, reply exactly: "{REFUSAL}" '
            "Cite sources inline as [1], [2] matching the numbered context blocks.",
        ),
        ("human", "Context:\n{context}\n\nQuestion: {question}"),
    ]
)


def format_docs(docs: list[Document]) -> str:
    blocks = []
    for i, d in enumerate(docs, start=1):
        src = d.metadata.get("source", "unknown")
        page = d.metadata.get("page")
        label = f"{src}" + (f" (page {page + 1})" if page is not None else "")
        blocks.append(f"[{i}] {label}\n{d.page_content}")
    return "\n\n".join(blocks)


@lru_cache(maxsize=1)
def _load_hf_model(model_id: str):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if torch.backends.mps.is_available():
        device = "mps"
    elif torch.cuda.is_available():
        device = "cuda"
    else:
        device = "cpu"
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(
        model_id, dtype=torch.float16 if device != "cpu" else torch.float32
    ).to(device)
    return tokenizer, model


def get_llm(temperature: float = 0.0) -> BaseChatModel:
    """Chat model for the configured provider. temperature > 0 enables sampling."""
    if config.LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=config.LLM_MODEL, temperature=temperature)

    from langchain_huggingface import ChatHuggingFace, HuggingFacePipeline
    from transformers import pipeline

    tokenizer, model = _load_hf_model(config.HF_LLM_MODEL)
    gen_kwargs = {"do_sample": temperature > 0}
    if temperature > 0:
        gen_kwargs.update(temperature=temperature, top_p=0.95)
    pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        max_new_tokens=config.HF_MAX_NEW_TOKENS,
        return_full_text=False,
        **gen_kwargs,
    )
    return ChatHuggingFace(llm=HuggingFacePipeline(pipeline=pipe))


def build_answer_chain(llm: BaseChatModel) -> Runnable:
    """{"context": list[Document], "question": str} -> answer str."""
    return (
        (lambda x: {"context": format_docs(x["context"]), "question": x["question"]})
        | PROMPT
        | llm
        | StrOutputParser()
    )


def build_chain(llm: BaseChatModel | None = None) -> Runnable:
    """Returns a runnable: question (str) -> {"question", "context" (docs), "answer"}."""
    llm = llm or get_llm()
    return RunnableParallel(
        context=get_retriever(), question=lambda q: q
    ).assign(answer=build_answer_chain(llm))
