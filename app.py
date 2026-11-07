"""LuminusRAG web UI: upload documents, watch them get processed, ask questions, run evals.

Run:  streamlit run app.py
"""
import json
from pathlib import Path

import pandas as pd
import streamlit as st

from rag import config
from rag.chain import build_guarded_chain, get_llm
from rag.history import (
    add_exchange, delete_chat, list_chats, load_messages, new_chat_id, redact_question,
    summarize_all, summarize_chat, summarize_messages,
)
from rag.ingest import get_chunks, ingest, list_indexed, remove_source, save_upload

st.set_page_config(page_title="LuminusRAG", page_icon="✨", layout="wide")


@st.cache_resource(show_spinner="Loading language model…")
def cached_llm():
    return get_llm()


def source_label(meta: dict) -> str:
    if meta.get("origin") == "graph":
        return "🕸 Knowledge graph facts"
    if meta.get("origin") == "web":
        return f"🌐 [{meta.get('title') or meta['source']}]({meta['source']})"
    name = Path(meta.get("source", "unknown")).name
    page = meta.get("page")
    return f"{name}, page {page + 1}" if page is not None else name


ORIGIN_LABELS = {"local": "📚 local documents", "web": "🌐 web search", "none": "nothing found"}


def answer_meta(result: dict) -> str:
    parts = []
    if result.get("standalone_question"):
        parts.append(f"↪ read as: “{result['standalone_question']}”")
    if result.get("intent"):
        parts.append(f"Intent: `{result['intent'].category}`")
    if result.get("origin"):
        parts.append(f"Answered from: {ORIGIN_LABELS[result['origin']]}")
    if result.get("local_score") is not None:
        parts.append(f"best local match: {result['local_score']:.2f}")
    if result.get("pii_redacted"):
        parts.append(f"🔒 redacted: {', '.join(result['pii_redacted'])}")
    if result.get("stored"):
        parts.append(f"💾 saved {result['stored']} web passages")
    if result.get("output_actions"):
        parts.append(f"🧹 answer cleaned: {'; '.join(result['output_actions'])}")
    guard = result.get("guard")
    if guard is not None and not guard.safe:
        parts.append(f"🛡 rejected by {guard.rule_id or 'guard'} ({guard.source})")
    return " · ".join(parts)


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
            elif event == "sanitized":
                parts = []
                if info["dropped"]:
                    rules = ", ".join(sorted({d["rule"] for d in info["dropped"]}))
                    parts.append(f"removed **{len(info['dropped'])} prompt-injection passage(s)** ({rules})")
                if info["hidden"]:
                    parts.append(f"removed {info['hidden']} hidden comment/image(s)")
                if info["redacted"]:
                    parts.append(f"redacted **{', '.join(info['redacted'])}**")
                st.write(f"🛡 **Policy check** — `{name}`: " + ("; ".join(parts) or "no issues found"))
                for d in info["dropped"]:
                    st.caption(f"{d['rule']}: {d['text'][:100]}…")
            elif event == "skip":
                st.write(f"↷ `{name}` unchanged, skipped")
            elif event == "split":
                pages = f"{info['pages_with_text']}/{info['pages']} pages with text, " if info["pages"] else ""
                st.write(
                    f"**3. Chunk by structure** — `{name}`: {pages}{info['characters']:,} characters → "
                    f"**{info['chunks']} chunks** by heading and paragraph; "
                    f"**{info['reused']} unchanged (reused)**, {info['embedded']} new"
                )
                if info["chunks"] == 0:
                    st.warning(f"No extractable text in `{name}` — scanned PDFs need OCR.")
                bars[name] = st.progress(1.0 if not info["embedded"] else 0.0,
                                         text=f"4. Embed + store `{name}`"
                                              + (" (nothing new)" if not info["embedded"] else ""))
            elif event == "embed":
                bars[name].progress(
                    info["done"] / info["total"],
                    text=f"4. Embed + store `{name}`: {info['done']}/{info['total']} chunks",
                )
            elif event == "activated":
                st.write(f"🔀 `{name}` **version {info['version']} is live** (switched atomically)")
            elif event == "stored":
                st.write(f"✅ `{name}` indexed in {info['seconds']}s")
            elif event == "gc_scheduled":
                st.write(f"🧹 Old versions will be garbage-collected in the background "
                         f"(after {info['delay']:.0f}s)")
            elif event == "graph":
                st.write("**5. Knowledge graph** — extracting entities and relations from new chunks")
                bars["__graph__"] = st.progress(0.0, text="Updating knowledge graph…")
            elif event == "graph_progress":
                bars["__graph__"].progress(info["done"] / info["total"],
                                           text=f"Knowledge graph: {info['done']}/{info['total']} chunks")
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
    st.header("✨ LuminusRAG")
    st.caption("Guarded GraphRAG for AI questions")
    total_chunks = sum(d["chunks"] for d in docs)
    c1, c2 = st.columns(2)
    c1.metric("Documents", len(docs))
    c2.metric("Chunks", total_chunks)
    model = config.HF_LLM_MODEL if config.LLM_PROVIDER == "huggingface" else config.LLM_MODEL
    st.caption(
        f"**LLM:** `{model}`  \n**Embeddings:** `{config.EMBED_MODEL.split('/')[-1]}`  \n"
        f"**Chunking:** {config.CHUNK_SIZE} chars, {config.CHUNK_OVERLAP} overlap  \n"
        f"**Retrieval:** {config.RETRIEVAL_MODE}, top {config.TOP_K}"
        f"{', reranked' if config.RERANK else ''}  \n"
        f"**Intent gate:** {'`' + config.INTENT_MODEL + '`' if config.INTENT_ENABLED else 'off'}  \n"
        f"**Policy guard:** regex + {'`' + config.GUARD_MODEL + '`' if config.GUARD_LLM else 'no LLM'}  \n"
        f"**Web fallback:** {'on (DuckDuckGo)' if config.WEB_FALLBACK else 'off'}"
        f"{', saves results' if config.WEB_FALLBACK and config.WEB_STORE else ''}"
    )

    # ----- chat history -----
    st.divider()
    st.subheader("💬 Chats")
    if st.button("➕ New chat", width="stretch"):
        st.session_state.chat_id = new_chat_id()
        st.session_state.messages = []
        st.session_state.pop("chat_summary", None)
        st.rerun()
    st.session_state.setdefault("chat_id", new_chat_id())
    previous = list_chats()
    if not previous:
        st.caption("No saved chats yet. Chats are saved after each answer.")
    for c in previous[:15]:
        current = c["id"] == st.session_state.chat_id
        col_open, col_del = st.columns([5, 1])
        label = f"{'▶ ' if current else ''}{c['title']}"
        if col_open.button(label, key=f"open-{c['id']}", help=f"{c['updated']} · "
                           f"{c['n_messages']} messages", width="stretch", disabled=current):
            st.session_state.chat_id = c["id"]
            st.session_state.messages = load_messages(c["id"])
            st.session_state.pop("chat_summary", None)
            st.rerun()
        if col_del.button("✕", key=f"delchat-{c['id']}", help="Delete this chat"):
            delete_chat(c["id"])
            if current:
                st.session_state.chat_id = new_chat_id()
                st.session_state.messages = []
            st.rerun()

tab_upload, tab_ask, tab_history, tab_docs, tab_graph, tab_eval = st.tabs(
    ["📤 Upload & process", "💬 Ask", "🗂 History", "📚 Documents", "🕸 Graph", "📊 Evaluate"]
)

# ---------- upload & process ----------

with tab_upload:
    st.subheader("Upload documents")
    st.caption("PDF, TXT or Markdown. New files are processed automatically: "
               "extract text → policy check (remove prompt injection, redact PII) → "
               "split into chunks → embed → store in Chroma.")
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
                ["file", "status", "version", "chunks", "reused", "embedded", "injections_removed",
                 "pii_redacted", "seconds"]
            ],
            hide_index=True,
            width="stretch",
        )

# ---------- ask ----------

with tab_ask:
    messages = st.session_state.setdefault("messages", [])
    head, b_this, b_all = st.columns([4, 1.4, 1.6])
    head.subheader("Ask your documents")
    if b_this.button("📝 Summarize chat", disabled=not messages, width="stretch"):
        with st.spinner("Summarizing this chat…"):
            st.session_state.chat_summary = {
                "title": "Summary of this chat",
                "overview": summarize_messages(messages, cached_llm()),
                "chats": [],
            }
    if b_all.button("🗂 Summarize all chats", disabled=not list_chats(), width="stretch"):
        bar = st.progress(0.0, text="Summarizing previous chats…")

        def on_progress(i, total, title):
            bar.progress(i / (total + 1), text=f"Summarizing chat {i}/{total}: {title}")

        result = summarize_all(cached_llm(), progress=on_progress)
        bar.empty()
        st.session_state.chat_summary = {"title": "Summary of previous chats", **result}

    if summary := st.session_state.get("chat_summary"):
        with st.container(border=True):
            top, close = st.columns([8, 1])
            top.markdown(f"**{summary['title']}**")
            if close.button("Close", key="close-summary"):
                st.session_state.pop("chat_summary")
                st.rerun()
            st.markdown(summary["overview"])
            if summary["chats"]:
                with st.expander(f"Per-chat summaries ({len(summary['chats'])})"):
                    for c in summary["chats"]:
                        st.markdown(f"**{c['title']}** · {c['updated'][:16].replace('T', ' ')}")
                        st.markdown(c["summary"])
                        st.divider()

    def render_sources(sources: list[dict]) -> None:
        with st.expander(f"Sources ({len(sources)})"):
            for i, s in enumerate(sources, 1):
                st.markdown(f"**[{i}] {s['label']}**")
                # Plain text: source text never renders as markdown (no images or links).
                st.text(s["text"][:600] + ("…" if len(s["text"]) > 600 else ""))

    if not docs:
        st.info("Upload a document in the **Upload & process** tab first.")

    chat = st.container()
    with chat:
        for m in messages:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])
                if m.get("meta"):
                    st.caption(m["meta"])
                if m.get("sources"):
                    render_sources(m["sources"])

    question = st.chat_input("Ask a question about your documents", disabled=not docs)
    if question:
        question = redact_question(question)  # PII never shown back or saved
        messages.append({"role": "user", "content": question})
        with chat:
            with st.chat_message("user"):
                st.markdown(question)
            with st.chat_message("assistant"):
                # Built per question so the retriever sees freshly indexed files.
                pipeline = build_guarded_chain(cached_llm())
                status_line = st.empty()
                final: dict = {}

                def answer_tokens():
                    for event in pipeline.events(question, history=messages[:-1]):
                        if event["type"] == "status":
                            status_line.caption(f"⏳ {event['message']}")
                        elif event["type"] == "token":
                            status_line.empty()
                            yield event["text"]  # already sanitized, segment by segment
                        elif event["type"] == "final":
                            final.update(event["result"])

                st.write_stream(answer_tokens())
                status_line.empty()
                result = final
                sources = [
                    {"label": source_label(d.metadata), "text": d.page_content}
                    for d in result["context"]
                ]
                intent = result.get("intent")
                meta_line = answer_meta(result)
                if meta_line:
                    st.caption(meta_line)
                if result.get("web_error"):
                    st.warning(f"Web search failed: {result['web_error']}")
                if sources:
                    render_sources(sources)
        messages.append({
            "role": "assistant",
            "content": result["answer"],
            "sources": sources,
            "meta": meta_line,
        })
        add_exchange(st.session_state.chat_id, question, result["answer"], meta_line, sources)

# ---------- history ----------

with tab_history:
    chats = list_chats()
    head, b_each, b_all = st.columns([4, 1.6, 1.6])
    head.subheader("Chat history")
    head.caption("Stored with LangChain `SQLChatMessageHistory`. Questions are saved "
                 "with personal data redacted. Summaries use the local model.")
    pending = [c for c in chats if not c["has_summary"]]
    if b_each.button(f"📝 Summarize each chat ({len(pending)} new)", disabled=not pending,
                     width="stretch"):
        bar = st.progress(0.0)
        for i, c in enumerate(pending, 1):
            bar.progress((i - 1) / len(pending), text=f"Summarizing {i}/{len(pending)}: {c['title']}")
            summarize_chat(c["id"], cached_llm())
        bar.empty()
        st.rerun()
    if b_all.button("🗂 Overview of all chats", disabled=len(chats) < 2, width="stretch"):
        with st.spinner("Summarizing each chat, then combining…"):
            st.session_state.history_overview = summarize_all(cached_llm())["overview"]
        st.rerun()

    if overview := st.session_state.get("history_overview"):
        with st.container(border=True):
            st.markdown("**Overview of all chats**")
            st.markdown(overview)

    if not chats:
        st.info("No saved chats yet. Ask a question in the **Ask** tab to start one.")
    for c in chats:
        when = c["updated"][:16].replace("T", " ")
        with st.container(border=True):
            top, b_sum, b_open = st.columns([6, 1.2, 1])
            top.markdown(f"**{c['title']}**  \n{when} · {c['n_messages'] // 2} questions")
            if b_sum.button("Re-summarize" if c["has_summary"] else "Summarize",
                            key=f"sum-{c['id']}", width="stretch"):
                with st.spinner("Summarizing…"):
                    summarize_chat(c["id"], cached_llm(), force=c["has_summary"])
                st.rerun()
            if b_open.button("Open", key=f"hist-open-{c['id']}", width="stretch"):
                st.session_state.chat_id = c["id"]
                st.session_state.messages = load_messages(c["id"])
                st.rerun()
            if c["has_summary"]:
                st.markdown(c["summary"])
            elif c["summary"]:
                st.caption("Summary is out of date (new messages since):")
                st.markdown(c["summary"])
            else:
                st.caption("Not summarized yet.")

# ---------- documents ----------

with tab_docs:
    st.subheader("Indexed documents")
    if not docs:
        st.info("Nothing indexed yet.")
    for d in docs:
        pages = f" · {d['pages']} pages" if d["pages"] else ""
        ver = f" · v{d['version']}" if d.get("version") else ""
        with st.expander(f"**{d['name']}** — {d['chunks']} chunks{pages}{ver}"):
            if d.get("origin") == "web":
                st.markdown(f"[{d['source']}]({d['source']})")
            else:
                st.caption(d["source"])
            if st.button("Remove document", key=f"del-{d['source']}", type="secondary"):
                remove_source(d["source"])
                st.rerun()
            if d.get("doc_id"):
                from rag.versioning import history

                st.caption("Versions: " + ", ".join(
                    f"v{h['version']} {h['status']} ({h['chunks']} chunks)" for h in history(d["doc_id"])))
            for c in get_chunks(d["source"]):
                where = f"page {c['page'] + 1} · " if c["page"] is not None else ""
                head = f" · {c['heading']}" if c.get("heading") else ""
                st.markdown(f"**Chunk {c['index']}**{head} · {where}{len(c['text'])} chars · `{c['chunk_id'][:12]}`")
                st.text(c["text"])

# ---------- knowledge graph ----------

with tab_graph:
    from rag.graph import graph_stats, load_graph, to_dot, update_graph

    head, b_build = st.columns([5, 1.5])
    head.subheader("Knowledge graph")
    head.caption(f"Entities and relations extracted from your chunks by `{config.GRAPH_MODEL}`. "
                 f"Retrieval mode: **{config.RETRIEVAL_MODE}** (set `RETRIEVAL_MODE` to "
                 "`vector`, `graph` or `hybrid`).")
    if b_build.button("Update graph", width="stretch"):
        bar = st.progress(0.0, text="Extracting…")
        update_graph(progress=lambda i, n: bar.progress(i / n, text=f"Extracting {i}/{n} chunks"))
        bar.empty()
        st.rerun()

    gs = graph_stats(top=20)
    c1, c2, c3 = st.columns(3)
    c1.metric("Entities", gs["nodes"])
    c2.metric("Relations", gs["edges"])
    c3.metric("Chunks read", gs["chunks"])
    if not gs["nodes"]:
        st.info("The graph is empty. Click **Update graph** to build it.")
    else:
        g, _ = load_graph()
        names = sorted({d["name"] for _, d in g.nodes(data=True)}, key=str.lower)
        top_names = [n for n, _, _ in gs["top"]]
        left, right = st.columns([1, 3])
        with left:
            st.markdown("**Most connected**")
            st.dataframe(pd.DataFrame(gs["top"], columns=["entity", "type", "links"]),
                         hide_index=True, width="stretch", height=420)
        with right:
            entity = st.selectbox("Explore an entity", names,
                                  index=names.index(top_names[0]) if top_names else 0)
            st.graphviz_chart(to_dot(entity), width="stretch")
            from rag.graph import graph_context

            seeds, facts, _ = graph_context(entity)
            if facts:
                with st.expander(f"Facts about {entity} ({len(facts)})"):
                    st.text("\n".join(facts))

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
