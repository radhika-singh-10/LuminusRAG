"""Web UI: upload documents, watch them get processed, ask questions, run evals.

Run:  streamlit run app.py
"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from rag import config
from rag.chain import build_chain, get_llm
from rag.ingest import get_chunks, ingest, list_indexed, remove_source, save_upload

st.set_page_config(page_title="Document Q&A", page_icon="📄", layout="wide")


@st.cache_resource(show_spinner="Loading language model…")
def cached_llm():
    return get_llm()


def source_label(meta: dict) -> str:
    name = Path(meta.get("source", "unknown")).name
    page = meta.get("page")
    return f"{name}, page {page + 1}" if page is not None else name


def indexed_docs() -> list[dict]:
    return list_indexed() if config.PERSIST_DIR.exists() else []


# ---------- processing ----------

def process_uploads(files) -> None:
    """Save uploads, then run ingestion with a live step-by-step view."""
    status = st.status(f"Processing {len(files)} file(s)…", expanded=True)
    with status:
        st.write("**1. Save** — writing uploads to `data/uploads/`")
        for f in files:
            save_upload(f.name, f.getvalue())

        bars: dict[str, st.delta_generator.DeltaGenerator] = {}

        def on_event(event: str, info: dict) -> None:
            name = Path(info.get("source", "")).name
            if event == "loaded":
                st.write(f"**2. Extract** — read text from {info['files']} file(s) in the data folder")
            elif event == "skip":
                st.write(f"↷ `{name}` unchanged, skipped")
            elif event == "split":
                pages = f"{info['pages_with_text']}/{info['pages']} pages with text, " if info["pages"] else ""
                st.write(
                    f"**3. Split** — `{name}`: {pages}{info['characters']:,} characters → "
                    f"**{info['chunks']} chunks** (~{info['avg_chunk_chars']} chars each)"
                )
                if info["chunks"] == 0:
                    st.warning(f"No extractable text in `{name}` — scanned PDFs need OCR.")
                bars[name] = st.progress(0.0, text=f"4. Embed + store `{name}`")
            elif event == "embed":
                bars[name].progress(
                    info["done"] / info["total"],
                    text=f"4. Embed + store `{name}`: {info['done']}/{info['total']} chunks",
                )
            elif event == "stored":
                st.write(f"✅ `{name}` indexed in {info['seconds']}s")
            elif event == "removed":
                st.write(f"🗑 `{name}` no longer in data folder, removed from index")

        try:
            stats = ingest(progress=on_event)
        except Exception as e:  # surface errors in the UI instead of a stack trace
            status.update(label=f"Processing failed: {e}", state="error")
            return

    status.update(
        label=(
            f"Done — {stats['added_files']} new, {stats['updated_files']} updated, "
            f"{stats['chunks_written']} chunks written · {stats['total_chunks']} chunks in index"
        ),
        state="complete",
        expanded=True,
    )
    st.session_state.last_report = stats["files"]


# ---------- sidebar ----------

docs = indexed_docs()
with st.sidebar:
    st.header("📄 Document Q&A")
    total_chunks = sum(d["chunks"] for d in docs)
    c1, c2 = st.columns(2)
    c1.metric("Documents", len(docs))
    c2.metric("Chunks", total_chunks)
    model = config.HF_LLM_MODEL if config.LLM_PROVIDER == "huggingface" else config.LLM_MODEL
    st.caption(
        f"**LLM:** `{model}`  \n**Embeddings:** `{config.EMBED_MODEL.split('/')[-1]}`  \n"
        f"**Chunking:** {config.CHUNK_SIZE} chars, {config.CHUNK_OVERLAP} overlap  \n"
        f"**Retrieval:** top {config.TOP_K}, {config.SEARCH_TYPE}"
    )

tab_upload, tab_ask, tab_docs, tab_eval = st.tabs(
    ["📤 Upload & process", "💬 Ask", "📚 Documents", "📊 Evaluate"]
)

# ---------- upload & process ----------

with tab_upload:
    st.subheader("Upload documents")
    st.caption("PDF, TXT or Markdown. New files are processed automatically: "
               "extract text → split into chunks → embed → store in Chroma.")
    files = st.file_uploader(
        "Drop files here",
        type=["pdf", "txt", "md"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    processed = st.session_state.setdefault("processed", set())
    new_files = [f for f in files or [] if (f.name, f.size) not in processed]
    if new_files:
        process_uploads(new_files)
        processed.update((f.name, f.size) for f in new_files)
        docs = indexed_docs()
    elif files:
        st.success("All uploaded files are processed. Ask questions in the **Ask** tab.")

    if report := st.session_state.get("last_report"):
        st.markdown("**Last processing run**")
        st.dataframe(
            pd.DataFrame(report).assign(file=lambda d: d["source"].map(lambda s: Path(s).name))[
                ["file", "status", "pages", "pages_with_text", "characters", "chunks",
                 "avg_chunk_chars", "seconds"]
            ],
            hide_index=True,
            width="stretch",
        )

# ---------- ask ----------

with tab_ask:
    messages = st.session_state.setdefault("messages", [])
    head, clear = st.columns([6, 1])
    head.subheader("Ask your documents")
    if clear.button("Clear chat", disabled=not messages):
        messages.clear()
        st.rerun()

    def render_sources(sources: list[dict]) -> None:
        with st.expander(f"Sources ({len(sources)})"):
            for i, s in enumerate(sources, 1):
                st.markdown(f"**[{i}] {s['label']}**")
                st.caption(s["text"][:600] + ("…" if len(s["text"]) > 600 else ""))

    if not docs:
        st.info("Upload a document in the **Upload & process** tab first.")

    chat = st.container()
    with chat:
        for m in messages:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
                if m.get("sources"):
                    render_sources(m["sources"])

    question = st.chat_input("Ask a question about your documents", disabled=not docs)
    if question:
        messages.append({"role": "user", "content": question})
        with chat:
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                with st.spinner("Retrieving and generating…"):
                    # Built per question so the retriever sees freshly indexed files.
                    result = build_chain(cached_llm()).invoke(question)
                sources = [
                    {"label": source_label(d.metadata), "text": d.page_content}
                    for d in result["context"]
                ]
                st.markdown(result["answer"])
                render_sources(sources)
        messages.append({"role": "assistant", "content": result["answer"], "sources": sources})

# ---------- documents ----------

with tab_docs:
    st.subheader("Indexed documents")
    if not docs:
        st.info("Nothing indexed yet.")
    for d in docs:
        pages = f" · {d['pages']} pages" if d["pages"] else ""
        with st.expander(f"**{d['name']}** — {d['chunks']} chunks{pages}"):
            st.caption(d["source"])
            if st.button("Remove document", key=f"del-{d['source']}", type="secondary"):
                remove_source(d["source"])
                st.rerun()
            for c in get_chunks(d["source"]):
                where = f"page {c['page'] + 1} · " if c["page"] is not None else ""
                st.markdown(f"**Chunk {c['index']}** · {where}{len(c['text'])} chars")
                st.text(c["text"])

# ---------- evaluate ----------

with tab_eval:
    st.subheader("Evaluate the pipeline")
    st.caption(
        f"Runs every question in `{config.EVAL_DATASET.relative_to(config.ROOT)}` "
        "through retrieval + generation, scores each answer, and reports accuracy, "
        "pass@k / pass^k, retrieval precision/recall, and truthfulness."
    )
    c1, c2, c3 = st.columns(3)
    n = c1.number_input("Samples per question (n)", 1, 10, 3)
    temperature = c2.slider("Temperature", 0.0, 1.5, 0.7, disabled=n == 1)
    top_k = c3.number_input("Chunks retrieved (top_k)", 1, 20, config.TOP_K)

    if st.button("Run evaluation", type="primary", disabled=not docs):
        from rag.eval.runner import run_eval

        with st.spinner(f"Evaluating with n={n}… (loads an NLI model on first run)"):
            ks = tuple(k for k in (1, 3, 5) if k <= n)
            st.session_state.eval_summary = run_eval(
                n=int(n), ks=ks, temperature=temperature, top_k=int(top_k)
            )

    if s := st.session_state.get("eval_summary"):
        def pct(v):
            return "n/a" if v is None else f"{v:.0%}"

        st.markdown("#### Generation")
        gen = {"Accuracy": s["accuracy"], **{k: v for k, v in s.items() if k.startswith("pass")}}
        for col, (label, v) in zip(st.columns(len(gen)), gen.items()):
            col.metric(label, pct(v))

        st.markdown("#### Truthfulness")
        t = s["truthfulness"]
        cols = st.columns(4)
        cols[0].metric("Faithfulness", pct(t["faithfulness"]))
        cols[1].metric("Hallucination rate", pct(t["hallucination_rate"]))
        cols[2].metric("Contradiction rate", pct(t["contradiction_rate"]))
        cols[3].metric("Reference entailment", pct(t["reference_entailment"]))

        left, mid, right = st.columns(3)
        for col, key, title in ((left, "retrieval", "Retrieval"), (mid, "answer", "Answer"),
                                (right, "abstention", "Abstention (\"I don't know\")")):
            col.markdown(f"#### {title}")
            col.dataframe(
                pd.DataFrame({"metric": list(s[key]), "value": [pct(v) for v in s[key].values()]}),
                hide_index=True, width="stretch",
            )

        rows = [
            {k: v for k, v in r.items() if k not in ("samples", "sources", "retrieval")}
            | {"first_answer": r["samples"][0]["answer"][:200]}
            for r in map(json.loads,
                         open(Path(s["results_dir"]) / "per_question.jsonl"))
        ]
        st.markdown("#### Per question")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        cfg = s["config"]
        st.caption(f"{cfg['n_questions']} questions × {cfg['n_samples']} samples in "
                   f"{cfg['seconds']}s · saved to `{s['results_dir']}`")
