"""LuminusRAG CLI: python main.py ingest [--rebuild] | ask "question" | chat | add FILES | eval | bench | eval-intent | chats | summarize | eval-guard | eval-security | graph | gc | versions | chunks | agent | eval-agent | eval-ocr | ocr | watch | eval-chunking | traces | cache"""
import argparse
import sys
from pathlib import Path

from rag import config


def stream_answer(chain, question: str, history: list[dict] | None = None) -> dict:
    """Print status lines and the answer as it streams; return the final result."""
    result, streaming = None, False
    for event in chain.events(question, history):
        if event["type"] == "status" and sys.stdout.isatty():
            print(f"\r\033[2K  … {event['message']}", end="", flush=True)
        elif event["type"] == "token":
            if not streaming:
                print("\r\033[2K" if sys.stdout.isatty() else "", end="")
                print()
                streaming = True
            print(event["text"], end="", flush=True)
        elif event["type"] == "final":
            result = event["result"]
    print("\n")
    return result


def print_result(result: dict, answer_shown: bool = False) -> None:
    intent = result.get("intent")
    tags = []
    if intent:
        tags.append(f"intent: {intent.category}")
    if result.get("origin"):
        tags.append(f"answered from: {result['origin']}")
    if tags:
        print(f"\n[{' | '.join(tags)}]")
    if result.get("standalone_question"):
        print(f"[read as: {result['standalone_question']}]")
    if result.get("pii_redacted"):
        print(f"[redacted before use: {', '.join(result['pii_redacted'])}]")
    if result.get("web_error"):
        print(f"[web search failed: {result['web_error']}]")
    if result.get("stored"):
        print(f"[saved {result['stored']} web passages to the knowledge base]")
    if result.get("trace_id"):
        print(f"[trace {result['trace_id'][:8]}: python main.py traces {result['trace_id'][:8]}]")
    if not answer_shown:
        print(f"\n{result['answer']}\n")
    if intent and intent.error and intent.category in ("error", "guard_error"):
        print(f"[check failed: {intent.error}]\n", file=sys.stderr)
    if not result["context"]:
        return
    print("Sources:")
    for i, d in enumerate(result["context"], start=1):
        page = d.metadata.get("page")
        loc = f", page {page + 1}" if page is not None else ""
        title = f"{d.metadata['title']} — " if d.metadata.get("title") else ""
        print(f"  [{i}] {title}{d.metadata.get('source', 'unknown')}{loc}")
    print()


def show_traces(args) -> int:
    from rag import observability as obs

    if args.purge:
        print(f"Removed {obs.purge()} traces older than {config.TRACE_RETENTION_DAYS} days.")
        return 0
    if args.stats:
        print(f"{'span':<34}{'type':<11}{'count':>6}{'p50 ms':>9}{'p95 ms':>9}{'errors':>8}{'tokens':>9}")
        for r in obs.span_stats():
            print(f"{r['name'][:33]:<34}{r['type']:<11}{r['count']:>6}{r['p50_ms'] or 0:>9.0f}"
                  f"{r['p95_ms'] or 0:>9.0f}{r['error_rate']:>8.2f}{r['tokens'] or '':>9}")
        return 0
    if args.trace_id:
        t = obs.get_trace(args.trace_id)
        if not t:
            print(f"No trace {args.trace_id}")
            return 1
        print(f"{t['name']}  {t['trace_id']}  {t['latency_ms']} ms  {len(t['spans'])} spans  "
              f"{t['llm_calls']} LLM calls  {t['tokens'] or 0} tokens  status {t['status']}")
        print(f"question: {t['question']}\n")
        for sp in t["spans"]:
            llm = (f"  {sp['model']} in={sp['tokens_in']} out={sp['tokens_out']}"
                   if sp["run_type"] in ("llm", "chat_model") else "")
            err = f"  ERROR {sp['error'][:80]}" if sp["error"] else ""
            print(f"{'  ' * sp['depth']}{sp['name']} [{sp['run_type']}] {sp['latency_ms']} ms{llm}{err}")
        return 0
    rows = obs.list_traces(args.limit, args.chat)
    if not rows:
        print("No traces yet.")
    for r in rows:
        print(f"{(r['start'] or '')[:19].replace('T', ' ')}  {r['trace_id'][:8]}  {r['name']:<17} "
              f"{r['latency_ms'] or 0:>6} ms  {r['spans']:>3} spans  {r['llm_calls']:>2} LLM  "
              f"{r['status']:<5}  {(r['question'] or '')[:60]}")
    return 0


def watch_loop(quiet: float | None) -> int:
    """Re-index changed files once data/ has been quiet for DEBOUNCE_SECONDS."""
    from rag.versioning import wait_for_gc
    from rag.watcher import Watcher

    def on_event(event: str, info: dict) -> None:
        name = Path(info.get("path") or info.get("source") or "").name
        if event == "change":
            print(f"  {info['kind']:<8} {name}  ({info['pending']} pending; "
                  f"sync in {info['sync_in']:.0f}s unless more changes)")
        elif event == "sync_start":
            print(f"Quiet for {w.debouncer.quiet:g}s -> syncing {len(info['files'])} file(s)")
        elif event == "diff":
            print(f"  diff {name}: {info['total']} chunks, {info['unchanged']} unchanged, "
                  f"{info['added']} new/changed, {info['removed']} removed")
        elif event == "activated":
            print(f"  {name}: version {info['version']} live")
        elif event == "removed":
            print(f"  {name}: deleted, retired")
        elif event == "sync_done":
            s = info["stats"]
            print(f"Synced in {info['seconds']}s: {s['chunks_written']} chunks embedded, "
                  f"{s['chunks_reused']} reused\n")
        elif event == "sync_error":
            print(f"Sync failed: {info['error']}")

    w = Watcher(quiet=quiet, on_event=on_event)
    print(f"Watching {w.data_dir} (debounce {w.debouncer.quiet:g}s, max wait "
          f"{w.debouncer.max_wait:g}s). Ctrl+C to stop.")
    try:
        w.run()
    except KeyboardInterrupt:
        pass
    wait_for_gc()
    return 0


def agent_loop(chat_id: str | None, user_id: str, show_trace: bool) -> int:
    """Interactive multi-step session: type a question, or 1-3 to take a suggestion."""
    from rag.agent.harness import build_agent
    from rag.history import new_chat_id
    from rag.prompt_cache import warm_in_background

    warm_in_background()  # prefill the system prompts while the user types

    agent = build_agent(user_id=user_id)
    chat_id = chat_id or new_chat_id()
    print(f"Chat {chat_id}: up to {agent.max_steps} questions. Type a question, "
          f"a number to take a suggested follow-up, or 'quit'.\n")
    followups: list[dict] = []
    while True:
        try:
            line = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if line.lower() in {"quit", "exit", "q"}:
            return 0
        if not line:
            continue
        from_fu = line.isdigit() and 1 <= int(line) <= len(followups)
        question = followups[int(line) - 1]["question"] if from_fu else line
        if from_fu:
            print(f"   → {question}")
        result = stream_answer(_AgentEvents(agent, chat_id, from_fu), question)
        print_result(result, answer_shown=True)
        if result.get("interests"):
            print("[interests: " + ", ".join(i["name"] for i in result["interests"][:5]) + "]")
        if show_trace:
            for t in result["trace"]:
                print(f"  · {t['layer']:<15} {t['tool']:<18} {t['ms']:>6} ms  {t.get('note', '')}")
        print(f"[step {result['step']}/{result['max_steps']}]")
        followups = result["followups"]
        for i, f in enumerate(followups, 1):
            print(f"  {i}. {f['question']}")
        if result.get("closed"):
            if result.get("summary"):
                print(f"\nConversation summary:\n{result['summary']}")
            print("\nThis conversation is complete. Start a new one with: python main.py agent")
            return 0
        print()


class _AgentEvents:
    """Adapts the harness to stream_answer's chain.events(question, history) call."""

    def __init__(self, agent, chat_id: str, from_followup: bool):
        self.agent, self.chat_id, self.from_followup = agent, chat_id, from_followup

    def events(self, question: str, history=None):
        return self.agent.events(self.chat_id, question, self.from_followup)


def main() -> int:
    parser = argparse.ArgumentParser(description="LuminusRAG: guarded GraphRAG for AI questions")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ing = sub.add_parser("ingest", help=f"Sync the index with files in {config.DATA_DIR}")
    ing.add_argument("--rebuild", action="store_true", help="Drop and rebuild the index")
    add = sub.add_parser("add", help="Add .pdf/.txt/.md or source-code files to the knowledge base")
    add.add_argument("files", nargs="+", type=Path)
    sub.add_parser("docs", help="List indexed documents")
    ask = sub.add_parser("ask", help="Ask a single question")
    ask.add_argument("question")
    sub.add_parser("chat", help="Interactive Q&A loop")
    ev = sub.add_parser("eval", help="Evaluate the pipeline on a labeled dataset")
    ev.add_argument("--dataset", type=Path, default=config.EVAL_DATASET)
    ev.add_argument("-n", type=int, default=5, help="Samples per question (for pass@k)")
    ev.add_argument("-k", default="1,3,5", help="Comma-separated k values for pass@k / pass^k")
    ev.add_argument("--temperature", type=float, default=0.7)
    ev.add_argument("--top-k", type=int, default=None, help="Chunks to retrieve")
    ev.add_argument("--limit", type=int, default=None, help="Only the first N questions")
    gr = sub.add_parser("graph", help="Knowledge graph: build, stats, or show an entity")
    gr.add_argument("action", choices=["build", "rebuild", "stats", "show"])
    gr.add_argument("entity", nargs="?", help="Entity name for 'show'")
    sub.add_parser("gc", help="Garbage-collect retired document versions now")
    sub.add_parser("versions", help="Show document versions and registry state")
    ch = sub.add_parser("chunks", help="Show the active chunks of a file")
    ch.add_argument("file")
    sub.add_parser("chats", help="List saved chats")
    summ = sub.add_parser("summarize", help="Summarize each saved chat with the local LLM")
    summ.add_argument("chat_id", nargs="?", help="One chat id (default: every chat)")
    summ.add_argument("--limit", type=int, default=None, help="Only the N most recent chats")
    summ.add_argument("--overview", action="store_true", help="Also combine into one overview")
    es = sub.add_parser("eval-security", help="Full-pipeline security eval: PII and prompt injection")
    es.add_argument("-n", type=int, default=3, help="Samples per case (for pass@k)")
    es.add_argument("-k", default="1,3", help="Comma-separated k values")
    es.add_argument("--temperature", type=float, default=0.7)
    es.add_argument("--limit", type=int, default=None)
    eg = sub.add_parser("eval-guard", help="Measure the policy guard on labeled attack/benign questions")
    eg.add_argument("--no-llm", action="store_true", help="Regex rules only")
    sub.add_parser("eval-intent", help="Measure the Ollama intent gate on labeled queries")
    ag = sub.add_parser("agent", help="Multi-step agent chat with follow-up suggestions (max 10 steps)")
    ag.add_argument("--chat", default=None, help="Continue a saved chat id")
    ag.add_argument("--user", default="local", help="User id for the interest profile")
    ag.add_argument("--trace", action="store_true", help="Print the tool trace per turn")
    ea = sub.add_parser("eval-agent", help="Evaluate personalization and multi-step follow-up sessions")
    ea.add_argument("--steps", type=int, default=None, help="Steps per session (default AGENT_MAX_STEPS)")
    ea.add_argument("--limit", type=int, default=None, help="Only the first N sessions")
    ea.add_argument("--compare", action="store_true", help="Also run sessions with personalization off")
    ea.add_argument("--no-sessions", action="store_true", help="Personalized retrieval only")
    ea.add_argument("--no-retrieval", action="store_true", help="Sessions only")
    wa = sub.add_parser("watch", help="Watch data/ and re-index changed files after a quiet period")
    wa.add_argument("--quiet", type=float, default=None,
                    help=f"Seconds without changes before syncing (default {config.DEBOUNCE_SECONDS:g})")
    sub.add_parser("eval-chunking", help="Chunking checks (no overlap, exact partition) + code retrieval eval")
    tr = sub.add_parser("traces", help="Observability: list traces, show one as a span tree, or stats")
    tr.add_argument("trace_id", nargs="?", help="Trace id (or prefix) to show")
    tr.add_argument("--stats", action="store_true", help="Latency / errors / tokens by span name")
    tr.add_argument("--chat", default=None, help="Only traces of this chat id")
    tr.add_argument("--limit", type=int, default=20)
    tr.add_argument("--purge", action="store_true", help="Delete traces older than TRACE_RETENTION_DAYS")
    ca = sub.add_parser("cache", help="Prompt cache: prefill system prompts (warm) or show hit rates")
    ca.add_argument("action", choices=["warm", "status"])
    sub.add_parser("eval-ocr", help="OCR accuracy (CER/WER) and retrieval on synthetic scanned PDFs")
    oc = sub.add_parser("ocr", help="OCR a PDF and print the text of its scanned pages")
    oc.add_argument("file", type=Path)
    oc.add_argument("--all", action="store_true", help="OCR every page, not only pages without text")
    bench = sub.add_parser("bench", help="Run and compare eval variants from an experiments file")
    bench.add_argument("--config", type=Path, default=config.ROOT / "eval" / "experiments.json")
    bench.add_argument("--only", default=None, help="Comma-separated variant names")
    bench.add_argument("-v", "--verbose", action="store_true", help="Full report per variant")

    args = parser.parse_args()

    if args.cmd == "ingest":
        from rag.ingest import ingest

        from rag.versioning import wait_for_gc

        ingest(rebuild=args.rebuild)
        wait_for_gc()  # the background GC must finish before this process exits
        return 0

    if args.cmd == "cache":
        if args.action == "warm":
            from rag.prompt_cache import warm

            for name, r in warm().items():
                print(f"{name:<42} " + (r["error"] if "error" in r else
                      f"{r['prompt_tokens']} tokens, prompt {r['prompt_ms']} ms, load {r['load_ms']} ms"))
            return 0
        from rag import observability as obs

        rows = [r for r in obs.span_stats() if r.get("cache_hit_rate") is not None]
        if not rows:
            print("No Ollama calls traced yet.")
        for r in sorted(rows, key=lambda r: r["name"]):
            print(f"{r['name']:<16} {r['count']:>5} calls  cache hit rate {r['cache_hit_rate']:.2f}  "
                  f"prompt p50 {r['prompt_ms_p50'] or 0:.0f} ms")
        return 0

    if args.cmd == "traces":
        return show_traces(args)

    if args.cmd == "watch":
        return watch_loop(args.quiet)

    if args.cmd == "eval-chunking":
        from rag.eval.chunk_eval import run_chunk_eval

        out = run_chunk_eval()
        print(f"\nSaved to {out['path']}  ({out['seconds']}s)")
        return 0

    if args.cmd == "eval-ocr":
        from rag.eval.ocr_eval import run_ocr_eval

        out = run_ocr_eval()
        print(f"\nSaved to {out['path']}  ({out['seconds']}s)")
        return 0

    if args.cmd == "ocr":
        from langchain_community.document_loaders import PyPDFLoader

        from rag.ocr import needs_ocr, ocr_pdf_pages

        pages = PyPDFLoader(str(args.file)).load()
        todo = [i for i, d in enumerate(pages) if args.all or needs_ocr(d.page_content)]
        if not todo:
            print(f"All {len(pages)} pages have a text layer; nothing to OCR (use --all to force).")
            return 0
        for i, r in ocr_pdf_pages(args.file, todo).items():
            conf = f"{r.confidence:.2f}" if r.confidence is not None else "n/a"
            print(f"--- page {i + 1} (OCR, {r.lines} lines, confidence {conf}, {r.seconds:.1f}s) ---")
            print(r.text or "[no text found]")
        return 0

    if args.cmd == "eval-agent":
        from rag.eval.agent_eval import print_agent_report, run_agent_eval

        print_agent_report(run_agent_eval(sessions=not args.no_sessions, retrieval=not args.no_retrieval,
                                          compare=args.compare, steps=args.steps, limit=args.limit))
        return 0

    if args.cmd == "agent":
        return agent_loop(args.chat, args.user, args.trace)

    if args.cmd == "gc":
        from rag.versioning import collect_garbage

        print(collect_garbage(grace_seconds=0))
        return 0

    if args.cmd == "versions":
        from rag import versioning as V

        print(V.registry_stats())
        for d in sorted(V.documents(), key=lambda d: d["source"]):
            print(f"\n{Path(d['source']).name}  ({d['doc_id']}, active v{d['active_version']}, {d['chunks']} chunks)")
            for h in V.history(d["doc_id"]):
                print(f"  v{h['version']:<3} {h['status']:<9} {h['chunks']:>3} chunks  {h['created']}")
        return 0

    if args.cmd == "chunks":
        from rag.ingest import get_chunks

        for c in get_chunks(str(Path(args.file).resolve())):
            print(f"[{c['index']}] {c['chunk_id'][:14]}  {c['heading'] or '-'}  ({len(c['text'])} chars)")
        return 0

    if args.cmd == "graph":
        from rag.graph import graph_context, graph_stats, update_graph

        if args.action in ("build", "rebuild"):
            update_graph(rebuild=args.action == "rebuild",
                         progress=lambda i, n: print(f"\r  extracting {i}/{n}", end="", flush=True))
            print()
        elif args.action == "stats":
            st_ = graph_stats()
            print(f"{st_['nodes']} entities, {st_['edges']} relations from {st_['chunks']} chunks")
            for name, etype, deg in st_["top"]:
                print(f"  {deg:>3}  {name} ({etype})")
        else:
            seeds, facts, chunks = graph_context(args.entity or "")
            print(f"Matched: {', '.join(seeds) or 'nothing'}")
            for f_ in facts:
                print(f"  {f_}")
        return 0

    if args.cmd == "chats":
        from rag.history import list_chats

        chats = list_chats()
        if not chats:
            print("No saved chats yet.")
        for c in chats:
            mark = " (summarized)" if c["has_summary"] else ""
            print(f"  {c['id']}  {c['updated'][:16].replace('T', ' ')}  "
                  f"{c['n_messages'] // 2:>3} questions  {c['title']}{mark}")
        return 0

    if args.cmd == "summarize":
        from rag.chain import get_llm
        from rag.history import summarize_all, summarize_chat, summarize_each

        llm = get_llm()
        if args.chat_id:
            print(f"\n{summarize_chat(args.chat_id, llm)}\n")
            return 0
        progress = lambda i, n, t: print(f"  summarizing {i}/{n}: {t}", file=sys.stderr)  # noqa: E731
        if args.overview:
            result = summarize_all(llm, limit=args.limit or 10, progress=progress)
            chats, overview = result["chats"], result["overview"]
        else:
            chats, overview = summarize_each(llm, limit=args.limit, progress=progress), None
        for c in chats:
            print(f"\n=== {c['title']}  ({c['id']}, {c['updated'][:16].replace('T', ' ')})")
            print(c["summary"])
        if overview:
            print(f"\n=== Overview of all chats\n{overview}")
        print()
        return 0

    if args.cmd == "eval-security":
        from rag.eval.security_eval import print_security_report, run_security_eval

        summary = run_security_eval(n=args.n, ks=tuple(int(k) for k in args.k.split(",")),
                                    temperature=args.temperature, limit=args.limit)
        print_security_report(summary)
        return 0

    if args.cmd == "eval-guard":
        from rag.eval.guard_eval import run_guard_eval

        run_guard_eval(use_llm=False if args.no_llm else None)
        return 0

    if args.cmd == "eval-intent":
        from rag.eval.intent_eval import run_intent_eval

        run_intent_eval()
        return 0

    if args.cmd == "add":
        from rag.ingest import add_files

        from rag.versioning import wait_for_gc

        add_files(args.files)
        wait_for_gc()
        return 0

    if args.cmd == "docs":
        from rag.ingest import list_indexed

        for d in list_indexed():
            pages = f", {d['pages']} pages" if d["pages"] else ""
            print(f"  {d['name']}: {d['chunks']} chunks{pages}  ({d['source']})")
        return 0

    if not config.PERSIST_DIR.exists():
        print("No index found. Run: python main.py ingest", file=sys.stderr)
        return 1

    if args.cmd == "bench":
        from rag.eval.harness import run_experiments

        run_experiments(
            args.config,
            only=args.only.split(",") if args.only else None,
            verbose=args.verbose,
        )
        return 0

    if args.cmd == "eval":
        from rag.eval.runner import print_report, run_eval

        summary = run_eval(
            dataset=args.dataset,
            n=args.n,
            ks=tuple(int(k) for k in args.k.split(",")),
            temperature=args.temperature,
            top_k=args.top_k,
            limit=args.limit,
        )
        print_report(summary)
        return 0

    from rag.chain import build_guarded_chain

    chain = build_guarded_chain()

    if args.cmd == "ask":
        print_result(stream_answer(chain, args.question), answer_shown=True)
        return 0

    from rag.history import add_exchange, new_chat_id, redact_question

    from rag.prompt_cache import warm_in_background

    warm_in_background()  # prefill the judges' system prompts while you type
    chat_id, history = new_chat_id(), []
    print(f"Type a question (or 'exit'). Chat id: {chat_id}")
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if q.lower() in {"exit", "quit", ""}:
            return 0
        result = stream_answer(chain, q, history)
        print_result(result, answer_shown=True)
        add_exchange(chat_id, redact_question(q), result["answer"])
        history += [{"role": "user", "content": redact_question(q)},
                    {"role": "assistant", "content": result["answer"]}]


if __name__ == "__main__":
    sys.exit(main())
