"""Chunking and debounce tests. Run: python -m pytest tests  (or: python tests/test_chunking.py)

- Code is chunked by imports / function / class / method, partitioning the
  file exactly: every line in exactly one chunk, nothing lost, no overlap.
- Documents are chunked by heading / paragraph with no overlap.
- Edit locality: editing one function or paragraph changes only that chunk's
  hash; inserting code above a function does not change the function's hash.
- The debouncer releases a batch only after DEBOUNCE quiet seconds.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rag.chunking import chunk_code, chunk_text  # noqa: E402
from rag.code_chunking import code_units, language_for  # noqa: E402
from rag.watcher import Debouncer  # noqa: E402

SAMPLES = {
    "a.ts": '''import { readFile } from "fs/promises";
import path from "path";

// Embeds text.
export async function embed(text: string): Promise<number[]> {
  const s = "brace in string { not counted";
  if (text.length === 0) { return []; }
  return [text.length];
}

export const cosine = (a: number[], b: number[]): number => {
  return a.reduce((s, x, i) => s + x * b[i], 0);
};

/** A tiny vector store. */
export class VectorStore {
  private items: Map<string, number[]> = new Map();

  add(id: string, v: number[]): void {
    this.items.set(id, v);
  }

  search(q: number[], k = 3): string[] {
    // } a brace in a comment
    return [...this.items.keys()].slice(0, k);
  }
}
''',
    "b.go": '''package store

import (
\t"fmt"
\t"sort"
)

// Item is a stored vector.
type Item struct {
\tID  string
\tVec []float64
}

func Cosine(a, b []float64) float64 {
\ts := 0.0
\tfor i := range a {
\t\ts += a[i] * b[i]
\t}
\treturn s
}

func (s *Store) Search(q []float64, k int) []string {
\tsort.Slice(s.items, func(i, j int) bool { return true })
\tfmt.Println("searched")
\treturn nil
}
''',
    "c.java": '''package com.example.rag;

import java.util.List;

/** Retriever. */
public class Retriever {
    private final int k;

    public Retriever(int k) {
        this.k = k;
    }

    @Override
    public String toString() {
        return "Retriever{" + k + "}";
    }

    public List<String> retrieve(String query) throws Exception {
        if (query.isEmpty()) {
            return List.of();
        }
        return List.of(query);
    }
}
''',
    "d.rs": '''use std::collections::HashMap;

/// A chunk.
pub struct Chunk {
    pub id: String,
}

impl Chunk {
    pub fn new(id: &str) -> Self {
        Chunk { id: id.to_string() }
    }

    pub fn len(&self) -> usize {
        self.id.len()
    }
}

pub fn hash(text: &str) -> u64 {
    text.len() as u64
}
''',
}


def nonblank(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def body(chunk_text_: str) -> str:
    return chunk_text_.partition("\n\n")[2]


def assert_partition(source: str, language: str, size: int = 1000) -> list:
    units = code_units(source, language, size)
    assert nonblank("\n".join(t for _, t in units)) == nonblank(source), "chunks must partition the file"
    starts = [u.start for u, _ in units]
    assert starts == sorted(starts), "chunks must be in file order"
    for (a, _), (b, _) in zip(units, units[1:]):
        assert a.end < b.start, "chunks must not overlap"
    return units


# ---------- code ----------

def test_python_files_partition_exactly():
    for f in sorted((ROOT / "rag").rglob("*.py")):
        assert_partition(f.read_text(), "python")


def test_python_one_symbol_per_chunk():
    src = (ROOT / "rag" / "eval" / "metrics.py").read_text()
    units = assert_partition(src, "python")
    funcs = [u.name for u, _ in units if u.kind == "function"]
    defined = re.findall(r"^def (\w+)", src, flags=re.M)
    assert funcs == defined, "every top-level function is its own chunk, in order"
    for u, text in units:
        if u.kind == "function":
            assert len(re.findall(r"^def ", text, flags=re.M)) == 1


def test_python_large_class_split_by_method():
    src = (ROOT / "rag" / "agent" / "harness.py").read_text()
    units = assert_partition(src, "python", size=1000)
    methods = [u.name for u, _ in units if u.kind == "method" and u.parent == "AgentHarness"]
    assert methods[:3] == ["__init__", "events", "turn"]
    assert all(u.kind != "class" or u.name != "AgentHarness" for u, _ in units)


def test_imports_grouped():
    src = (ROOT / "rag" / "chain.py").read_text()
    units = assert_partition(src, "python")
    assert units[0][0].kind == "imports"
    assert "from langchain_core.documents import Document" in units[0][1]


def test_brace_languages():
    expected = {
        "a.ts": ["imports", "def embed", "def cosine", "class VectorStore"],
        "b.go": ["imports", "struct Item", "def Cosine", "def Search"],
        "c.java": ["imports", "class Retriever"],
        "d.rs": ["imports", "struct Chunk", "impl Chunk", "def hash"],
    }
    from rag.code_chunking import unit_heading

    for name, src in SAMPLES.items():
        units = assert_partition(src, language_for(name))
        labels = [unit_heading("", u) for u, _ in units]
        assert labels == expected[name], (name, labels)


def test_brace_class_split_by_method():
    units = assert_partition(SAMPLES["c.java"], "java", size=150)
    assert [u.name for u, _ in units if u.kind == "method"] == ["Retriever", "toString", "retrieve"]
    units = assert_partition(SAMPLES["a.ts"], "typescript", size=150)
    assert [u.name for u, _ in units if u.kind == "method"] == ["add", "search"]


def test_unparseable_python_falls_back():
    src = "import os\n\ndef ok():\n    return 1\n\ndef broken(:\n    pass\n"
    units = assert_partition(src, "python")
    assert [u.kind for u, _ in units] == ["imports", "function", "function"]


# ---------- documents ----------

def test_markdown_no_overlap():
    for f in sorted((ROOT / "data").glob("*.md")):
        src = f.read_text()
        chunks = chunk_text(src)
        got = [l for c in chunks for l in nonblank(body(c.text) if c.heading else c.text)
               if not re.match(r"^\s*(```|~~~)", l)]
        want, in_fence = [], False
        for l in nonblank(src):
            if re.match(r"^\s*(```|~~~)", l):
                in_fence = not in_fence
                continue
            if in_fence or not re.match(r"^#{1,6}\s", l):  # "# comment" inside code is code
                want.append(l)
        assert got == want, f.name


def test_long_code_fence_split_by_function():
    code = (ROOT / "rag" / "eval" / "metrics.py").read_text()
    md = f"# Guide\n\nIntro.\n\n```python\n{code}\n```\n\nAfter.\n"
    chunks = chunk_text(md, size=1000)
    fenced = [c for c in chunks if "```python" in c.text]
    assert all(len(re.findall(r"^def ", body(c.text), flags=re.M)) <= 1 for c in fenced)
    assert sum("def pass_at_k" in c.text for c in chunks) == 1


# ---------- edit locality (why there is no overlap) ----------

def _hashes(chunks) -> list[str]:
    return [c.content_hash for c in chunks]


def test_edit_one_function_changes_one_chunk():
    src = (ROOT / "rag" / "eval" / "metrics.py").read_text()
    edited = src.replace("return 1.0 - math.comb(n - c, k) / math.comb(n, k)",
                         "return 1 - math.comb(n - c, k) / math.comb(n, k)")
    assert edited != src
    before = set(_hashes(chunk_code(src, "python", "metrics.py")))
    after = set(_hashes(chunk_code(edited, "python", "metrics.py")))
    assert len(after - before) == 1, "only the edited function's chunk changes"


def test_insert_above_keeps_function_hash():
    src = (ROOT / "rag" / "eval" / "metrics.py").read_text()
    edited = src.replace("def pass_at_k", "def helper():\n    return 0\n\n\ndef pass_at_k", 1)
    before = {c.heading: c.content_hash for c in chunk_code(src, "python", "metrics.py")}
    after = {c.heading: c.content_hash for c in chunk_code(edited, "python", "metrics.py")}
    assert before["metrics.py > def pass_at_k"] == after["metrics.py > def pass_at_k"]
    assert len(set(after.values()) - set(before.values())) == 1  # just the new helper


def test_edit_one_paragraph_changes_one_chunk():
    src = (ROOT / "data" / "vector_databases.md").read_text()
    edited = src.replace("Approximate nearest neighbour", "Approximate nearest-neighbour", 1)
    assert edited != src
    assert len(set(_hashes(chunk_text(edited))) - set(_hashes(chunk_text(src)))) == 1


# ---------- debounce ----------

class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_debouncer_waits_for_quiet_period():
    clock = FakeClock()
    d = Debouncer(quiet=10, max_wait=60, clock=clock)
    for t in (0, 3, 6):          # three saves, 3 s apart
        clock.t = t
        d.touch("/data/a.py")
    clock.t = 15.9
    assert d.ready() is None     # only 9.9 s since the last save
    clock.t = 16.0
    assert d.ready() == {"/data/a.py": "modified"}
    assert d.ready() is None     # released once


def test_debouncer_max_wait():
    clock = FakeClock()
    d = Debouncer(quiet=10, max_wait=30, clock=clock)
    for t in range(0, 40, 5):    # a save every 5 s, never quiet for 10 s
        clock.t = t
        d.touch("/data/a.py")
        if t >= 30:
            assert d.ready() is not None
            break
        assert d.ready() is None


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted((k, v) for k, v in globals().items() if k.startswith("test_")):
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
    print(f"\n{'all passed' if not failed else f'{failed} failed'}")
    sys.exit(1 if failed else 0)
