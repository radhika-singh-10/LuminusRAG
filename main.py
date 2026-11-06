"""CLI: python main.py ingest [--rebuild] | ask "question" | chat | add FILES | eval | bench"""
import argparse
import sys
from pathlib import Path

from rag import config


def print_result(result: dict) -> None:
    print(f"\n{result['answer']}\n")
    print("Sources:")
    for i, d in enumerate(result["context"], start=1):
        page = d.metadata.get("page")
        loc = f", page {page + 1}" if page is not None else ""
        print(f"  [{i}] {d.metadata.get('source', 'unknown')}{loc}")
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
    bench = sub.add_parser("bench", help="Run and compare eval variants from an experiments file")
    bench.add_argument("--config", type=Path, default=config.ROOT / "eval" / "experiments.json")
    bench.add_argument("--only", default=None, help="Comma-separated variant names")
    bench.add_argument("-v", "--verbose", action="store_true", help="Full report per variant")

    args = parser.parse_args()

    if args.cmd == "ingest":
        from rag.ingest import ingest

        ingest(rebuild=args.rebuild)
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

    from rag.chain import build_chain

    chain = build_chain()

    if args.cmd == "ask":
        print_result(chain.invoke(args.question))
        return 0

    print("Type a question (or 'exit').")
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if q.lower() in {"exit", "quit", ""}:
            return 0
        print_result(chain.invoke(q))


if __name__ == "__main__":
    sys.exit(main())
