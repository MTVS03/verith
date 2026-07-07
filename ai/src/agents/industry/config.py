"""Environment loading, output paths, and the DART client factory.

Loads secrets from ``.env`` (see ``.env.example``) and exposes the on-disk
layout for Step 1 outputs. Keeping paths here means the collection script and
later pipeline stages agree on where filings live.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

INDUSTRY_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = INDUSTRY_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"              # per-company '사업의 내용' text + meta.json
STRUCTURED_DIR = DATA_DIR / "structured"  # accumulated CSV tables (holdings, shareholders)
EXTRACTED_DIR = DATA_DIR / "extracted"    # Step 3 outputs: reviewable triples + graph docs


def get_dart_api_key() -> str:
    """Return the DART Open API key, raising a clear error if unset."""
    key = os.getenv("DART_API_KEY")
    if not key:
        raise RuntimeError(
            "DART_API_KEY is not set. Set it in ai/.env with your "
            "DART Open API key (free at https://opendart.fss.or.kr)."
        )
    return key


def get_dart_client():
    """Build an OpenDartReader client from the configured API key."""
    # Imported lazily so importing config (e.g. for paths) doesn't require the
    # heavy OpenDartReader/pandas import chain. Note: OpenDartReader's __init__
    # rebinds sys.modules['OpenDartReader'] to the class itself, so `import
    # OpenDartReader` yields the callable class (not `from ... import ...`).
    import OpenDartReader

    return OpenDartReader(get_dart_api_key())


# --- Main LLM: self-hosted llama-server (OpenAI-compatible) -----------------

# Defaults target the local Qwen3.6 llama-server; override via .env.
DEFAULT_LLM_BASE_URL = "http://192.168.0.35:8000/v1"
DEFAULT_LLM_MODEL = "Qwen3.6-35B-A3B-UD-Q6_K.gguf"


def get_chat_llm(
    *,
    temperature: float = 0.0,
    enable_thinking: bool = False,
    max_tokens: int | None = None,
    **kwargs,
):
    """Return a ``ChatOpenAI`` pointed at the self-hosted LLM.

    The whole GraphRAG pipeline (extraction, Cypher generation, answering)
    should build its LLM through this factory so the endpoint/model live in
    one place.

    Qwen3.6 is a *reasoning* model: its ``<think>`` phase is emitted before the
    answer and can eat the entire ``max_tokens`` budget, leaving an empty
    ``content``. We disable it by default (``enable_thinking=False``) via
    llama.cpp's ``chat_template_kwargs`` so structured tasks (tool calls,
    Cypher) return promptly and deterministically. Pass
    ``enable_thinking=True`` for hard multi-hop reasoning, and give it room
    with ``max_tokens``.
    """
    from langchain_openai import ChatOpenAI

    base_url = os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL)
    model = os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL)
    api_key = os.getenv("LLM_API_KEY", "sk-no-key-required")

    return ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body={"chat_template_kwargs": {"enable_thinking": enable_thinking}},
        **kwargs,
    )


# --- Embeddings: DART 원문 청크 벡터화 (하이브리드 검색, 갈래 B) ---------------

# 한국어 리트리벌 특화 모델. verify: GPU 로딩·1024차원·query 프리픽스 내장 확인됨.
DEFAULT_EMBED_MODEL = "dragonkue/snowflake-arctic-embed-l-v2.0-ko"


def get_embeddings(*, device: str | None = None):
    """Return a ``HuggingFaceEmbeddings`` for chunk/query vectorization.

    Like :func:`get_chat_llm`, the single place the embedding model lives so
    vectorization (Step 1) and vector search (Step 2) agree on model + dims.

    ``dragonkue/snowflake-arctic-embed-l-v2.0-ko`` (1024-dim, max 8192 tokens)
    defines an **asymmetric** prompt map ``{'query': 'query: ', 'document': ''}``:
    queries must carry the ``query: `` prefix, documents must not. We wire that
    via ``query_encode_kwargs`` (``prompt_name='query'``) vs ``encode_kwargs``
    (``prompt_name='document'``) so ``embed_query`` and ``embed_documents``
    differ correctly — getting this wrong measurably hurts retrieval.

    GPU is used when available (verified on an RTX 4070); falls back to CPU.
    """
    from langchain_huggingface import HuggingFaceEmbeddings

    if device is None:
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
    model = os.getenv("EMBED_MODEL", DEFAULT_EMBED_MODEL)

    return HuggingFaceEmbeddings(
        model_name=model,
        model_kwargs={"device": device},
        encode_kwargs={"normalize_embeddings": True, "prompt_name": "document"},
        query_encode_kwargs={"normalize_embeddings": True, "prompt_name": "query"},
    )


# --- Neo4j: the knowledge graph store (Step 4 ingestion, Step 5 retrieval) ---


def get_neo4j_graph(**kwargs):
    """Return a ``Neo4jGraph`` pointed at the configured Neo4j instance.

    Like :func:`get_chat_llm`, this is the single place the connection lives so
    ingestion (Step 4) and the Cypher retrieval chain (Step 5) agree on the
    endpoint. Reads ``NEO4J_URI`` / ``NEO4J_USERNAME`` / ``NEO4J_PASSWORD`` from
    ``.env`` (see ``.env.example``). ``.query()`` on the returned object runs
    arbitrary Cypher.
    """
    # Imported lazily so importing config for paths doesn't pull in the neo4j
    # driver (mirrors the ChatOpenAI import above).
    from langchain_neo4j import Neo4jGraph

    uri = os.getenv("NEO4J_URI")
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    if not (uri and username and password):
        raise RuntimeError(
            "Neo4j is not configured. Set these values in ai/.env: "
            "NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD (start a local "
            "instance with: docker run -d --name neo4j -p 7474:7474 -p 7687:7687 "
            "-e NEO4J_AUTH=neo4j/<password> neo4j:5)."
        )
    return Neo4jGraph(url=uri, username=username, password=password, **kwargs)
