"""FAISS + BM25 hybrid store.

Layout on disk (under VECTORSTORE_DIR):
    index.faiss       - FAISS vector index
    index.pkl         - LangChain FAISS docstore
    bm25.pkl          - pickled BM25Okapi + tokenized corpus + raw texts/metadata

FAISS is a flat binary file — no SQLite, no locks, survives concurrent reads.
"""
from __future__ import annotations

import pickle
import re
import shutil
from pathlib import Path

from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader, TextLoader
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi

from agent.config import settings
from agent.models import build_embeddings


# ---------- loaders ----------------------------------------------------------


def load_policies(policies_dir: Path | None = None) -> list[Document]:
    policies_dir = policies_dir or settings.policies_dir
    policies_dir.mkdir(parents=True, exist_ok=True)

    docs: list[Document] = []
    loaders = [
        DirectoryLoader(str(policies_dir), glob="**/*.pdf", loader_cls=PyPDFLoader, show_progress=True),
        DirectoryLoader(
            str(policies_dir), glob="**/*.md",
            loader_cls=TextLoader, loader_kwargs={"encoding": "utf-8"}, show_progress=True,
        ),
        DirectoryLoader(
            str(policies_dir), glob="**/*.txt",
            loader_cls=TextLoader, loader_kwargs={"encoding": "utf-8"}, show_progress=True,
        ),
    ]
    for loader in loaders:
        try:
            docs.extend(loader.load())
        except Exception as e:
            print(f"load_policies: {loader.__class__.__name__} failed: {e}")
    return docs


def split_docs(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, chunk_overlap=200,
        separators=["\n\n", "\n", " ", ""],
    )
    return splitter.split_documents(docs)


# ---------- BM25 sidecar -----------------------------------------------------


_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _bm25_path() -> Path:
    return settings.vectorstore_dir / "bm25.pkl"


def _save_bm25(docs: list[Document]) -> None:
    tokens = [_tokenize(d.page_content) for d in docs]
    bm25 = BM25Okapi(tokens) if tokens else None
    payload = {
        "bm25": bm25,
        "texts": [d.page_content for d in docs],
        "metadatas": [d.metadata for d in docs],
    }
    _bm25_path().parent.mkdir(parents=True, exist_ok=True)
    with open(_bm25_path(), "wb") as f:
        pickle.dump(payload, f)


def load_bm25() -> dict | None:
    p = _bm25_path()
    if not p.exists():
        return None
    try:
        with open(p, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


# ---------- FAISS store ------------------------------------------------------


def build_vectorstore(docs: list[Document]) -> FAISS | None:
    settings.vectorstore_dir.mkdir(parents=True, exist_ok=True)
    embeddings = build_embeddings()
    if not docs:
        _save_bm25([])
        return None
    store = FAISS.from_documents(docs, embeddings)
    store.save_local(str(settings.vectorstore_dir))
    _save_bm25(docs)
    return store


def load_vectorstore() -> FAISS | None:
    faiss_index = settings.vectorstore_dir / "index.faiss"
    if not faiss_index.exists():
        return None
    return FAISS.load_local(
        folder_path=str(settings.vectorstore_dir),
        embeddings=build_embeddings(),
        allow_dangerous_deserialization=True,
    )


def _all_docs(store: FAISS) -> list[Document]:
    docstore = getattr(store, "docstore", None)
    data = getattr(docstore, "_dict", None) or {}
    return list(data.values())


# ---------- UI-facing helpers -----------------------------------------------


def _load_one(path: Path) -> list[Document]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return PyPDFLoader(str(path)).load()
    if suffix in {".md", ".txt"}:
        return TextLoader(str(path), encoding="utf-8").load()
    return []


def add_files(file_paths: list[str | Path]) -> dict:
    """Copy uploads into POLICIES_DIR and extend the live store.

    BM25 has to be rebuilt over the full corpus after each add (no incremental
    update in rank_bm25). FAISS is extended in-place.
    """
    settings.policies_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    skipped: list[str] = []

    for src in file_paths:
        src_path = Path(src)
        if not src_path.exists():
            skipped.append(f"{src_path.name} (missing)")
            continue
        if src_path.suffix.lower() not in {".pdf", ".md", ".txt"}:
            skipped.append(f"{src_path.name} (unsupported)")
            continue
        dest = settings.policies_dir / src_path.name
        if dest.resolve() != src_path.resolve():
            shutil.copy2(src_path, dest)
        copied.append(dest)

    raw: list[Document] = []
    for p in copied:
        raw.extend(_load_one(p))
    if not raw:
        return {"copied": [p.name for p in copied], "skipped": skipped, "chunks_added": 0}

    new_splits = split_docs(raw)

    store = load_vectorstore()
    if store is None:
        store = build_vectorstore(new_splits)
    else:
        store.add_documents(new_splits)
        store.save_local(str(settings.vectorstore_dir))
        _save_bm25(_all_docs(store))

    return {
        "copied": [p.name for p in copied],
        "skipped": skipped,
        "chunks_added": len(new_splits),
    }


def list_policy_files() -> list[dict]:
    settings.policies_dir.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for p in sorted(settings.policies_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in {".pdf", ".md", ".txt"}:
            out.append({"name": p.name, "size_kb": round(p.stat().st_size / 1024, 1)})
    return out


def vectorstore_stats() -> dict:
    try:
        store = load_vectorstore()
        if store is None:
            return {"chunks": 0, "ok": True}
        return {"chunks": len(_all_docs(store)), "ok": True}
    except Exception as e:
        return {"chunks": 0, "ok": False, "error": f"{type(e).__name__}: {e}"}


def rebuild_from_policies_dir() -> dict:
    # Drop any cached retriever holding onto files.
    try:
        from agent.nodes.retrieve import reset_retriever
        reset_retriever()
    except Exception:
        pass

    if settings.vectorstore_dir.exists():
        shutil.rmtree(settings.vectorstore_dir)
    raw = load_policies()
    if not raw:
        build_vectorstore([])
        return {"chunks": 0, "files": 0}
    splits = split_docs(raw)
    build_vectorstore(splits)
    return {"chunks": len(splits), "files": len(raw)}


def ingest() -> FAISS | None:
    raw = load_policies()
    if not raw:
        print(f"No policy documents found in {settings.policies_dir}. Vector store will be empty.")
        return build_vectorstore([])
    print(f"Loaded {len(raw)} documents.")
    splits = split_docs(raw)
    print(f"Split into {len(splits)} chunks.")
    store = build_vectorstore(splits)
    print(f"Persisted to {settings.vectorstore_dir}.")
    return store
