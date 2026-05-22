"""Chunked retrieval demo — shows why chunking (T3) beats whole-doc embedding.

Splits each docs/rag_sources/*.md into section chunks (by '## ' headers,
each chunk carries the doc title for context), embeds every chunk, and ranks
chunks (and docs, by their best chunk) against the query.

Compare with rag_smoke.py (whole-doc), where E-3002 lost to the chiller
manual. With chunking the E-3002 'refrigerant leak' section should win.
"""
from __future__ import annotations

import glob
import math
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs" / "rag_sources"
EMBED_MODEL = "text-embedding-3-small"
QUERY = "냉매가 새는 것 같아요"
load_dotenv(ROOT / ".env")


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def chunk_doc(name: str, text: str) -> list[dict]:
    lines = text.splitlines()
    title = lines[0].lstrip("# ").strip() if lines else name
    parts = re.split(r"(?m)^##\s+(.+)$", text)  # [pre, hdr, body, hdr, body...]
    chunks, it = [], iter(parts[1:])
    for header in it:
        body = next(it, "").strip()
        chunks.append({
            "doc": name,
            "header": header.strip(),
            "text": f"{title} — {header.strip()}\n{body}",
        })
    return chunks


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set — add it to .env.")

    chunks: list[dict] = []
    for path in sorted(glob.glob(str(DOCS_DIR / "*.md"))):
        chunks += chunk_doc(Path(path).name,
                            Path(path).read_text(encoding="utf-8"))

    client = OpenAI()
    resp = client.embeddings.create(
        model=EMBED_MODEL, input=[c["text"] for c in chunks] + [QUERY])
    vecs = [e.embedding for e in resp.data]
    qv = vecs[-1]
    for c, v in zip(chunks, vecs[:-1]):
        c["sim"] = cosine(qv, v)

    ndocs = len({c["doc"] for c in chunks})
    print(f"\nQuery : {QUERY!r}")
    print(f"Chunks: {len(chunks)} (from {ndocs} docs)\n")

    print("=== Top 5 chunks (chunked retrieval) ===")
    for i, c in enumerate(sorted(chunks, key=lambda c: c["sim"], reverse=True)[:5], 1):
        print(f"  {i}. {c['doc']:<38} {c['sim']:.4f}  [{c['header']}]")

    print("\n=== Doc ranking (best chunk per doc) ===")
    best: dict[str, float] = {}
    for c in chunks:
        best[c["doc"]] = max(best.get(c["doc"], -1.0), c["sim"])
    for i, (doc, s) in enumerate(sorted(best.items(), key=lambda kv: kv[1], reverse=True), 1):
        print(f"  {i}. {doc:<42} {s:.4f}")


if __name__ == "__main__":
    main()
