"""CLI: python main.py ingest [--rebuild] | ask "question" | chat | add FILES | eval | bench | eval-intent | chats | summarize | eval-guard | eval-security"""
import argparse
import sys
from pathlib import Path

from rag import config


def stream_answer(chain, question: str) -> dict:
    """Print status lines and the answer as it streams; return the final result."""
    result, streaming = None, False
    for event in chain.events(question):
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
    if result.get("pii_redacted"):
        print(f"[redacted before use: {', '.join(result['pii_redacted'])}]")
    if result.get("web_error"):
        print(f"[web search failed: {result['web_error']}]")
    if result.get("stored"):
        print(f"[saved {result['stored']} web passages to the knowledge base]")
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


def main() -> int:
    parser = argparse.ArgumentParser(description="LangChain RAG demo")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ing = sub.add_parser("ingest", help=f"Sync the index with files in {config.DATA_DIR}")
    ing.add_argument("--rebuild", action="store_true", help="Drop and rebuild the index")
    add = sub.add_parser("add", help="Add .pdf/.txt/.md files to the knowledge base")
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
    bench = sub.add_parser("bench", help="Run and compare eval variants from an experiments file")
    bench.add_argument("--config", type=Path, default=config.ROOT / "eval" / "experiments.json")
    bench.add_argument("--only", default=None, help="Comma-separated variant names")
    bench.add_argument("-v", "--verbose", action="store_true", help="Full report per variant")

    args = parser.parse_args()

    if args.cmd == "ingest":
        from rag.ingest import ingest

        ingest(rebuild=args.rebuild)
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

        add_files(args.files)
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

    chat_id = new_chat_id()
    print(f"Type a question (or 'exit'). Chat id: {chat_id}")
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if q.lower() in {"exit", "quit", ""}:
            return 0
        result = stream_answer(chain, q)
        print_result(result, answer_shown=True)
        add_exchange(chat_id, redact_question(q), result["answer"])


if __name__ == "__main__":
    sys.exit(main())
