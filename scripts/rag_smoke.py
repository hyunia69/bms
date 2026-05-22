"""
RAG smoke test — BMS POC T1 first slice verification.

Embeds every doc in docs/rag_sources/ plus a test query with OpenAI
(text-embedding-3-small, 1536d) and verifies semantic retrieval two ways:

  1. Pure-Python cosine ranking            (needs only OPENAI_API_KEY)
  2. Supabase match_documents RPC via       (needs SUPABASE_URL +
     PostgREST: insert + retrieve            SUPABASE_SERVICE_ROLE_KEY)

The query "냉매가 새는 것 같아요" should rank the E-3002 (refrigerant
leak) doc first, ahead of the filter / chiller distractor docs.

Run:  .venv\\Scripts\\python scripts\\rag_smoke.py
"""
from __future__ import annotations

import glob
import math
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

try:  # make Korean print cleanly regardless of console codepage
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs" / "rag_sources"
EMBED_MODEL = "text-embedding-3-small"  # 1536d (eng-review locked)
QUERY = "냉매가 새는 것 같아요"

load_dotenv(ROOT / ".env")


def cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def load_docs() -> list[dict]:
    docs = []
    for path in sorted(glob.glob(str(DOCS_DIR / "*.md"))):
        docs.append({"name": Path(path).name,
                     "content": Path(path).read_text(encoding="utf-8")})
    return docs


def main() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set — add it to .env. Aborting.")

    docs = load_docs()
    if not docs:
        sys.exit(f"No .md docs found in {DOCS_DIR}")

    client = OpenAI()
    resp = client.embeddings.create(
        model=EMBED_MODEL,
        input=[d["content"] for d in docs] + [QUERY],
    )
    vecs = [e.embedding for e in resp.data]
    query_vec, doc_vecs = vecs[-1], vecs[:-1]
    for d, v in zip(docs, doc_vecs):
        d["embedding"] = v

    print(f"\nQuery : {QUERY!r}")
    print(f"Model : {EMBED_MODEL} ({len(query_vec)}d), docs={len(docs)}\n")

    # 1) Pure-Python cosine ranking ------------------------------------
    print("=== [1] Python cosine ranking (OpenAI embeddings only) ===")
    ranked = sorted(docs, key=lambda d: cosine(query_vec, d["embedding"]),
                    reverse=True)
    for i, d in enumerate(ranked, 1):
        print(f"  {i}. {d['name']:<42} sim={cosine(query_vec, d['embedding']):.4f}")

    # 2) Supabase full end-to-end via PostgREST ------------------------
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not (url and key):
        print("\n[2] Supabase end-to-end skipped — set SUPABASE_URL + "
              "SUPABASE_SERVICE_ROLE_KEY in .env to enable.")
        return

    import httpx

    rest = url.rstrip("/") + "/rest/v1"
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    with httpx.Client(timeout=30) as http:
        http.request("DELETE", f"{rest}/rag_documents", headers=headers,
                     params={"id": "gt.0"}).raise_for_status()      # clear
        http.post(f"{rest}/rag_documents", headers=headers, json=[
            {"content": d["content"], "metadata": {"source": d["name"]},
             "embedding": d["embedding"]} for d in docs
        ]).raise_for_status()                                       # insert
        r = http.post(f"{rest}/rpc/match_documents", headers=headers, json={
            "query_embedding": query_vec, "match_count": 3, "filter": {}})
        r.raise_for_status()                                        # retrieve
        rows = r.json()

    print("\n=== [2] Supabase match_documents RPC via PostgREST ===")
    for i, row in enumerate(rows, 1):
        src = (row.get("metadata") or {}).get("source", "?")
        print(f"  {i}. {src:<42} sim={row['similarity']:.4f}")


if __name__ == "__main__":
    main()
