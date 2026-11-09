"""Build the "messy" retrieval corpus and its question set.

    python eval/messy/build_corpus.py

Writes eval/messy/corpus/*.md (a synthetic ML-platform wiki, about 3x the
words and chunks of data/) and eval/messy_dataset.jsonl. The corpus is deterministic
(fixed seed) and is deliberately hard for a bi-encoder:

- near-duplicate sections: every vector collection has a production, a
  staging and often a retired config that differ only in their numbers;
  benchmark runs are repeated after a "tokenizer fix";
- long templated documents (changelog, incident postmortems) whose sections
  share most of their wording;
- rambling meeting notes where a later meeting reverses an earlier decision;
- noise: repeated page boilerplate, filler sentences, OCR-style hyphenated
  line breaks.

Every evidence string is checked to occur in exactly one section, so
retrieval metrics are unambiguous. The facts are invented; this corpus exists
only to stress retrieval and reranking.
"""
import json
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from rag.eval.metrics import normalize  # noqa: E402

rng = random.Random(20261108)
CORPUS = HERE / "corpus"
DATASET = ROOT / "eval" / "messy_dataset.jsonl"

FILLER = [
    "This section was migrated from the old Confluence space and may still contain stale links.",
    "Ping the on-call channel before changing anything here outside a maintenance window.",
    "Numbers below were copied from the dashboard at the time of writing and are not updated automatically.",
    "See the runbook for the general procedure; this page only records what is specific to this case.",
    "Owners are expected to review this entry every quarter, although in practice that rarely happens.",
    "A previous version of this text lived in a Google Doc that has since been archived.",
    "The retrieval platform serves embeddings, vector search, reranking and answer generation for internal teams.",
    "Values marked as defaults can be overridden per tenant through the platform config service.",
    "If something here contradicts the code, the code wins and this page should be fixed.",
    "Latency figures are measured at the gateway and include network time between availability zones.",
    "Questions about this page can go to the platform guild sync on Thursdays.",
    "Several teams copy this layout into their own docs, so keep the structure stable.",
]
FOOTER = "_Maintained by Platform Infra. Generated sections are refreshed nightly; manual edits may be overwritten._"

sections: dict[str, list[str]] = {}   # file -> list of section texts
questions: list[dict] = []


def filler(n: tuple[int, int] = (1, 2)) -> str:
    return " ".join(rng.sample(FILLER, rng.randint(*n)))


def ocr_noise(text: str) -> str:
    """Hyphenate a couple of long words across a line break, like a bad PDF export."""
    # only filler words, so the facts (and evidence strings) stay intact
    filler_words = set(re.findall(r"\b[a-z]{9,}\b", " ".join(FILLER)))
    fact_words = set(re.findall(r"\b[a-z]{9,}\b", " ".join(
        line for line in text.split("\n") if not any(f in line for f in FILLER))))
    words = [w for w in set(re.findall(r"\b[a-z]{9,}\b", text)) if w in filler_words - fact_words]
    for w in rng.sample(sorted(words), min(2, len(words))):
        cut = len(w) // 2
        text = text.replace(w, f"{w[:cut]}-\n{w[cut:]}", 1)
    return text


def add(file: str, text: str, noisy: bool = False) -> None:
    sections.setdefault(file, []).append(ocr_noise(text) if noisy else text)


def ask(qid, question, reference, must_include, evidence, answerable=True):
    q = {"id": qid, "question": question, "reference": reference,
         "must_include": must_include, "evidence": evidence}
    if not answerable:
        q = {"id": qid, "question": question, "answerable": False,
             "reference": "I don't know based on the provided documents."}
    questions.append(q)


# ---------- 1. vector index configs: prod / staging / retired near-duplicates ----------

COLLECTIONS = ["support-tickets", "legal-contracts", "product-docs", "hr-policies", "code-search",
               "sales-calls", "research-papers", "release-notes", "onboarding-guides",
               "security-advisories", "customer-faq", "finance-reports"]
TEAMS = ["Support Tooling", "Contracts Intelligence", "Docs Platform", "People Systems", "Developer Productivity",
         "Revenue Insights", "Research Enablement", "Release Engineering", "Learning Platform",
         "Security Operations", "Customer Experience", "Finance Systems"]
MODELS = [("bge-small-en-v1.5", 384), ("bge-base-en-v1.5", 768), ("e5-base-v2", 768),
          ("gte-base", 768), ("all-MiniLM-L6-v2", 384), ("nomic-embed-text-v1.5", 768)]
used_cfg: set[tuple] = set()


def cfg_values():
    while True:
        v = (rng.choice([8, 12, 16, 24, 32, 48]), rng.choice([100, 128, 160, 200, 256, 320, 400]),
             rng.choice([40, 64, 80, 96, 128, 150, 180, 200, 256]), rng.choice([1, 2, 3, 4, 6, 8]))
        if v not in used_cfg:
            used_cfg.add(v)
            return v


index_facts = {}
for name, team in zip(COLLECTIONS, TEAMS):
    model, dims = rng.choice(MODELS)
    variants = ["production", "staging"] + (["production, retired"] if rng.random() < 0.6 else [])
    for variant in variants:
        m, efc, efs, shards = cfg_values()
        tag = variant.split(",")[0] + (" (retired)" if "retired" in variant else "")
        vmodel = model if variant != "production, retired" else rng.choice([x for x in MODELS if x[0] != model])[0]
        index_facts[(name, variant)] = dict(m=m, efc=efc, efs=efs, shards=shards, model=vmodel)
        add("index_configs.md",
            f"## Collection: {name} ({variant})\n\n"
            f"Owner: {team} team. Embedding model: {vmodel}. Distance metric: cosine.\n\n"
            f"HNSW parameters for {name} in {tag}: M = {m}, ef_construction = {efc}, "
            f"ef_search = {efs}. Shard count for {name} in {tag}: {shards}.\n\n{filler()}",
            noisy=rng.random() < 0.3)

for name in rng.sample(COLLECTIONS, 6):
    f = index_facts[(name, "production")]
    ask(f"idx_efs_{name}", f"What ef_search value does the production {name} collection use?",
        f"The production {name} collection uses ef_search = {f['efs']}.", [str(f["efs"])],
        [f"HNSW parameters for {name} in production: M = {f['m']}"])
for name in rng.sample(COLLECTIONS, 4):
    f = index_facts[(name, "staging")]
    ask(f"idx_shards_{name}", f"How many shards does the staging {name} collection have?",
        f"The staging {name} collection has {f['shards']} shards.", [str(f["shards"])],
        [f"Shard count for {name} in staging: {f['shards']}"])
for name in [n for n in COLLECTIONS if (n, "production, retired") in index_facts][:3]:
    f = index_facts[(name, "production, retired")]
    ask(f"idx_retired_{name}", f"Which embedding model did the retired production config of {name} use?",
        f"The retired production config of {name} used {f['model']}.", [f["model"]],
        [f"HNSW parameters for {name} in production (retired): M = {f['m']}"])

# ---------- 2. embedding benchmarks: original runs + reruns after a tokenizer fix ----------

DATASETS = ["support-qa", "contracts-qa", "code-qa", "faq-qa"]
bench = {}
for model, _ in MODELS:
    for ds in DATASETS:
        for kind in ["original run", "rerun after the tokenizer fix"]:
            if kind != "original run" and rng.random() < 0.5:
                continue
            r10 = round(rng.uniform(0.55, 0.95), 3)
            mrr = round(r10 - rng.uniform(0.08, 0.2), 3)
            p50 = rng.randint(6, 48)
            bench[(model, ds, kind)] = (r10, mrr, p50)
            add("embedding_benchmarks.md",
                f"### {model} on {ds} ({kind})\n\n"
                f"Benchmark {model} / {ds} / {kind}: recall@10 = {r10}, MRR = {mrr}, "
                f"p50 query latency = {p50} ms on one A10G.\n\n{filler((1, 3))}",
                noisy=rng.random() < 0.3)

reruns = [k for k in bench if k[2] != "original run"]
for model, ds, kind in rng.sample(reruns, 5):
    r10, _, _ = bench[(model, ds, kind)]
    ask(f"bench_rerun_{model}_{ds}", f"What recall@10 did {model} reach on {ds} in the rerun after the tokenizer fix?",
        f"{model} reached recall@10 = {r10} on {ds} after the tokenizer fix.", [str(r10)],
        [f"Benchmark {model} / {ds} / {kind}: recall@10 = {r10}"])
originals = [k for k in bench if k[2] == "original run"]
for model, ds, kind in rng.sample(originals, 4):
    _, _, p50 = bench[(model, ds, kind)]
    ask(f"bench_p50_{model}_{ds}", f"What was the p50 query latency of {model} on {ds} in the original benchmark run?",
        f"{p50} ms.", [f"{p50} ms"], [f"Benchmark {model} / {ds} / {kind}: recall@10"])

# ---------- 3. incident postmortems: same template, different causes ----------

SERVICES = ["retrieval-api", "ingest-worker", "reranker-svc", "embedding-gateway", "vector-store"]
CAUSES = [
    ("ran out of disk space because old index snapshots were never pruned", "added a snapshot retention job"),
    ("exhausted its connection pool after a client stopped closing sessions", "capped connections per client"),
    ("loaded a cross-encoder checkpoint with the wrong tokenizer", "pinned tokenizer files next to the model"),
    ("hit GPU out-of-memory errors when batch size was doubled", "reverted the batch size and added a memory alarm"),
    ("served stale results because the cache TTL was set to a week", "reduced the cache TTL to ten minutes"),
    ("rejected requests after a TLS certificate expired", "automated certificate renewal"),
    ("deadlocked during a schema migration of the metadata table", "split the migration into online steps"),
    ("returned empty results when a shard failed health checks silently", "made shard failures fail the query loudly"),
    ("dropped documents whose PDFs contained only scanned images", "routed image-only PDFs through OCR"),
    ("throttled every tenant after a single tenant flooded the queue", "added per-tenant rate limits"),
    ("crashed on startup because an environment variable was renamed", "validated config at boot"),
    ("double-indexed documents after a retry storm", "made ingestion idempotent by content hash"),
    ("timed out because ef_search was raised to 1,000 in production", "restored ef_search and added a config review"),
    ("leaked memory in the tokenizer cache under long queries", "bounded the tokenizer cache"),
    ("ranked results randomly after a model file was half-downloaded", "verified model checksums on load"),
    ("lost writes when two leaders were elected during a network partition", "moved to a quorum-based lease"),
]
for i, (cause, fix) in enumerate(CAUSES):
    svc = SERVICES[i % len(SERVICES)]
    inc = f"INC-{2000 + rng.randint(10, 990)}"
    mins = rng.randint(7, 240)
    month = rng.randint(1, 12)
    text = (f"## Postmortem {inc}: {svc} degradation\n\n"
            f"Date: 2025-{month:02d}-{rng.randint(1, 28):02d}. Severity: SEV-{rng.randint(1, 3)}. Service: {svc}.\n\n"
            f"Summary: the {svc} {cause}. Customer impact lasted {mins} minutes. "
            f"Remediation: the team {fix}.\n\n{filler()}")
    add("incident_postmortems.md", text, noisy=rng.random() < 0.3)
    if i % 2 == 0:
        ask(f"inc_{i}", f"How long did customer impact last when the {svc} {cause}?",
            f"Customer impact lasted {mins} minutes.", [f"{mins} minutes"], [f"the {svc} {cause}"])
    elif i % 4 == 1:
        ask(f"inc_fix_{i}", f"What remediation followed the incident where the {svc} {cause}?",
            f"The team {fix}.", [fix.split()[-2] + " " + fix.split()[-1]], [f"the {svc} {cause}"])

# ---------- 4. changelog: many near-identical release entries ----------

CHANGES = [
    ("default rerank fetch_k", lambda: f"from {rng.choice([10, 20, 30])} to {rng.choice([40, 50, 60])}"),
    ("retrieval API request timeout", lambda: f"to {rng.choice([15, 20, 30, 45, 60])} seconds"),
    ("maximum chunk size", lambda: f"to {rng.choice([600, 800, 1000, 1200])} characters"),
    ("embedding batch size", lambda: f"to {rng.choice([32, 64, 96, 128, 256])}"),
    ("default top_k", lambda: f"to {rng.choice([3, 4, 5, 6, 8, 10])}"),
    ("ingest worker concurrency", lambda: f"to {rng.choice([2, 4, 8, 12, 16])} workers"),
]
release_facts = []
for minor in range(1, 9):
    for patch in range(0, rng.randint(4, 7)):
        ver = f"v3.{minor}.{patch}"
        what, val = rng.choice(CHANGES)
        change = f"Changed the {what} {val()}."
        extra = rng.choice(["Fixed a typo in the admin UI.", "Upgraded the Chroma client.",
                            "Improved log messages for failed ingests.", "Bumped dependency pins.",
                            "Removed an unused feature flag.", "Documented the tenant config schema."])
        add("changelog.md", f"## {ver}\n\n- {change}\n- {extra}\n\n{FOOTER}")
        release_facts.append((ver, change))

seen_changes = {}
for ver, change in release_facts:
    seen_changes.setdefault(change, []).append(ver)
unique = [(v, c) for v, c in release_facts if len(seen_changes[c]) == 1]
for ver, change in rng.sample(unique, 6):
    body = change[len("Changed the "):-1]
    ask(f"rel_{ver}", f"In which release was the {body}?", f"In {ver}.", [ver], [f"## {ver}\n\n- {change}"[3:]])

# ---------- 5. meeting notes: decisions reversed later ----------

MEETINGS = [
    ("2025-02-04", "Default chunk size", "We agreed to move the default chunk size to 512 tokens for all new tenants."),
    ("2025-05-13", "Default chunk size, revisited",
     "The 512-token default hurt long legal clauses, so the default chunk size is now 768 tokens."),
    ("2025-03-11", "Reranker rollout", "The reranker stays behind a flag and is enabled only for the support-tickets tenant."),
    ("2025-07-22", "Reranker rollout, phase two",
     "The reranker is now enabled for every tenant whose corpus is larger than 50,000 chunks."),
    ("2025-04-01", "Embedding model choice", "We pick bge-small-en-v1.5 as the default embedding model to keep costs down."),
    ("2025-09-09", "Embedding model choice, revisited",
     "After the tokenizer-fix reruns, the default embedding model becomes gte-base."),
    ("2025-06-17", "Eval cadence", "Retrieval evals run nightly against the frozen 400-question benchmark."),
    ("2025-08-05", "On-call rotation", "The retrieval on-call rotation moves from weekly to fortnightly shifts."),
]
for date, topic, decision in MEETINGS:
    chatter = " ".join(rng.sample(FILLER, 3))
    add("meeting_notes.md",
        f"## Platform sync {date}: {topic}\n\nAttendees: platform guild, two tenant reps.\n\n"
        f"{chatter}\n\nDecision recorded on {date}: {decision}\n\n{FOOTER}", noisy=True)

ask("mtg_chunk", "What is the current default chunk size after the decision was revisited?",
    "768 tokens.", ["768"], ["Decision recorded on 2025-05-13"])
ask("mtg_rerank", "In phase two of the reranker rollout, which tenants get the reranker?",
    "Every tenant whose corpus is larger than 50,000 chunks.", ["50,000"], ["Decision recorded on 2025-07-22"])
ask("mtg_embed", "Which default embedding model was chosen when the decision was revisited after the tokenizer-fix reruns?",
    "gte-base.", ["gte-base"], ["Decision recorded on 2025-09-09"])
ask("mtg_oncall", "How long are retrieval on-call shifts after the rotation change?",
    "Fortnightly.", ["fortnight"], ["Decision recorded on 2025-08-05"])

# ---------- unanswerable: plausible questions the corpus does not answer ----------

ask("na_collection", "What ef_search value does the production marketing-assets collection use?", "", [], [], False)
ask("na_bench", "What recall@10 did text-embedding-3-large reach on support-qa?", "", [], [], False)
ask("na_incident", "How long did the outage caused by a DNS misconfiguration in the reranker-svc last?", "", [], [], False)
ask("na_release", "In which release was GPU autoscaling for the embedding gateway introduced?", "", [], [], False)

# ---------- write + validate ----------

CORPUS.mkdir(parents=True, exist_ok=True)
for old in CORPUS.glob("*.md"):
    old.unlink()
titles = {"index_configs.md": "Vector index configuration registry",
          "embedding_benchmarks.md": "Embedding model benchmark log",
          "incident_postmortems.md": "Retrieval platform incident postmortems",
          "changelog.md": "Retrieval platform changelog",
          "meeting_notes.md": "Platform guild meeting notes"}
all_sections = []
for file, secs in sections.items():
    rng.shuffle(secs) if file in ("index_configs.md", "incident_postmortems.md") else None
    body = f"# {titles[file]}\n\n{FOOTER}\n\n" + "\n\n".join(secs) + "\n"
    (CORPUS / file).write_text(body, encoding="utf-8")
    all_sections += secs

norm_sections = [normalize(s.replace("-\n", "")) for s in all_sections]
norm_raw = [normalize(s) for s in all_sections]
problems = []
for q in questions:
    for ev in q.get("evidence", []):
        hits = sum(normalize(ev) in s for s in norm_raw)
        if hits != 1:
            problems.append(f"{q['id']}: evidence {ev!r} occurs in {hits} sections")
too_long = sum(len(s) > 1000 for s in all_sections)
if problems:
    sys.exit("Evidence check failed:\n" + "\n".join(problems))

DATASET.write_text("".join(json.dumps(q) + "\n" for q in questions), encoding="utf-8")
words = sum(len(s.split()) for s in all_sections)
print(f"{len(all_sections)} sections, {words} words in {len(sections)} files -> {CORPUS}")
print(f"{len(questions)} questions ({sum(q.get('answerable', True) for q in questions)} answerable) -> {DATASET}")
print(f"sections over 1,000 chars: {too_long}")
