"""
vector_db.py — APG Policy Knowledge Base ("The Law Library")

Manages the Qdrant in-memory vector store for corporate procurement policies.
Implements Hybrid Search: semantic similarity + hard categorical payload
filtering to guarantee we never miss a policy due to vector distance alone.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from langchain_openai import OpenAIEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from src.apg.schema import Policy, SpendIntent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLLECTION_NAME = "corporate_policies"
VECTOR_SIZE = 1536  # text-embedding-3-small output dimension
TOP_K = 5  # Max policies to retrieve per query


# ---------------------------------------------------------------------------
# Client singleton
# ---------------------------------------------------------------------------

_client: Optional[QdrantClient] = None
_embedder: Optional[OpenAIEmbeddings] = None


def _get_client() -> QdrantClient:
    """Return (or lazily create) the in-memory Qdrant client."""
    global _client
    if _client is None:
        _client = QdrantClient(":memory:")
    return _client


def _get_embedder() -> OpenAIEmbeddings:
    """Return (or lazily create) the OpenAI embeddings model."""
    global _embedder
    if _embedder is None:
        _embedder = OpenAIEmbeddings(model="text-embedding-3-small")
    return _embedder


# ---------------------------------------------------------------------------
# Initialisation — ingest policies.json into Qdrant
# ---------------------------------------------------------------------------


def ingest_policies(policies_path: Path) -> None:
    """
    Read policies.json, embed each rule, and upsert into Qdrant.
    Safe to call multiple times — recreates the collection each time.
    """
    client = _get_client()
    embedder = _get_embedder()

    # Load raw policies from disk
    raw_policies: list[dict] = json.loads(policies_path.read_text())

    # Validate each policy against our Pydantic model
    policies = [Policy(**p) for p in raw_policies]

    # (Re)create vector collection
    if client.collection_exists(COLLECTION_NAME):
        client.delete_collection(COLLECTION_NAME)

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
    )

    # Embed rules and build points
    texts = [f"{p.category}: {p.rule}" for p in policies]
    vectors = embedder.embed_documents(texts)

    points = [
        PointStruct(
            id=idx,
            vector=vec,
            payload={
                "policy_id": p.id,
                "category": p.category,
                "rule": p.rule,
                "exception_path": p.exception_path,
            },
        )
        for idx, (p, vec) in enumerate(zip(policies, vectors))
    ]

    client.upsert(collection_name=COLLECTION_NAME, points=points)
    print(f"[vector_db] Ingested {len(points)} policies into '{COLLECTION_NAME}'")


# ---------------------------------------------------------------------------
# Retrieval — Hybrid Search (semantic + categorical hard filter)
# ---------------------------------------------------------------------------


def retrieve_policies(intent: SpendIntent) -> list[Policy]:
    """
    Retrieve the most relevant policies for a given SpendIntent.

    Strategy (Hybrid Search):
    1. Semantic: embed the intent description and run cosine similarity.
    2. Hard filter: restrict results to payloads where `category` matches
       the intent's category. This guarantees category-specific thresholds
       are never missed due to pure vector distance.

    Falls back to unfiltered search when category is 'Unknown'.
    """
    client = _get_client()
    embedder = _get_embedder()

    query_text = (
        f"{intent.category}: purchase from {intent.vendor} "
        f"for ${intent.amount} — {intent.justification}"
    )
    query_vector = embedder.embed_query(query_text)

    # Build categorical filter unless category is Unknown
    search_filter: Optional[Filter] = None
    if intent.category != "Unknown":
        search_filter = Filter(
            must=[
                FieldCondition(
                    key="category",
                    match=MatchValue(value=intent.category),
                )
            ]
        )

    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_vector,
        query_filter=search_filter,
        limit=TOP_K,
        with_payload=True,
    )

    policies: list[Policy] = []
    for hit in results:
        payload = hit.payload or {}
        try:
            policies.append(
                Policy(
                    id=payload["policy_id"],
                    category=payload["category"],
                    rule=payload["rule"],
                    exception_path=payload["exception_path"],
                )
            )
        except Exception:
            continue  # Skip malformed payloads

    return policies


# ---------------------------------------------------------------------------
# Utility — parse a dollar threshold from a rule string
# ---------------------------------------------------------------------------

_THRESHOLD_RE = re.compile(r"\$\s*([\d,]+)(k)?", re.IGNORECASE)


def extract_threshold_from_rule(rule: str) -> int | None:
    """
    Parse the first dollar-amount threshold from a policy rule string.
    Handles both plain numbers and k-suffix (thousands).

    Examples:
        "All laptop purchases exceeding $2,500 require VP approval."  -> 2500
        "GPU credits exceeding $5k/month require CTO approval."       -> 5000
        "Marketing expenses over $500 cannot use personal cards."     -> 500
    """
    match = _THRESHOLD_RE.search(rule)
    if match:
        amount = int(match.group(1).replace(",", ""))
        if match.group(2) and match.group(2).lower() == "k":
            amount *= 1000
        return amount
    return None

