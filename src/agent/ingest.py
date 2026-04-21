"""Load policy docs, split, embed, and persist to Chroma."""
from __future__ import annotations

import shutil
from pathlib import Path

from langchain_chroma import Chroma
from langchain_community.document_loaders import DirectoryLoader, PyPDFLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from agent.config import settings
from agent.models import build_embeddings


def load_policies(policies_dir: Path | None = None) -> list[Document]:
    policies_dir = policies_dir or settings.policies_dir
    policies_dir.mkdir(parents=True, exist_ok=True)

    docs: list[Document] = []
    pdfs = DirectoryLoader(
        str(policies_dir), glob="**/*.pdf", loader_cls=PyPDFLoader, show_progress=True
    )
    txts = DirectoryLoader(
        str(policies_dir),
        glob="**/*.{md,txt}",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
        show_progress=True,
    )
    docs.extend(pdfs.load())
    docs.extend(txts.load())
    return docs


def split_docs(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", " ", ""],
    )
    return splitter.split_documents(docs)


def build_vectorstore(docs: list[Document]) -> Chroma:
    settings.vectorstore_dir.mkdir(parents=True, exist_ok=True)
    return Chroma.from_documents(
        documents=docs,
        embedding=build_embeddings(),
        collection_name=settings.vectorstore_collection,
        persist_directory=str(settings.vectorstore_dir),
    )


def load_vectorstore() -> Chroma:
    return Chroma(
        collection_name=settings.vectorstore_collection,
        embedding_function=build_embeddings(),
        persist_directory=str(settings.vectorstore_dir),
    )


def ingest() -> Chroma:
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


# ---- UI-facing helpers --------------------------------------------------------


def _load_one(path: Path) -> list[Document]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return PyPDFLoader(str(path)).load()
    if suffix in {".md", ".txt"}:
        return TextLoader(str(path), encoding="utf-8").load()
    return []


def add_files(file_paths: list[str | Path]) -> dict:
    """Copy uploaded files into POLICIES_DIR and add their chunks to the live store.

    Returns a summary dict with counts.
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

    splits = split_docs(raw)
    store = load_vectorstore()
    store.add_documents(splits)
    return {
        "copied": [p.name for p in copied],
        "skipped": skipped,
        "chunks_added": len(splits),
    }


def list_policy_files() -> list[dict]:
    """Enumerate files currently in POLICIES_DIR."""
    settings.policies_dir.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for p in sorted(settings.policies_dir.rglob("*")):
        if p.is_file() and p.suffix.lower() in {".pdf", ".md", ".txt"}:
            out.append({"name": p.name, "size_kb": round(p.stat().st_size / 1024, 1)})
    return out


def vectorstore_stats() -> dict:
    """Chunk count in the current vector store."""
    try:
        store = load_vectorstore()
        count = store._collection.count()  # type: ignore[attr-defined]
        return {"chunks": int(count), "ok": True}
    except Exception as e:
        return {"chunks": 0, "ok": False, "error": f"{type(e).__name__}: {e}"}


def rebuild_from_policies_dir() -> dict:
    """Wipe the vector store and re-ingest everything from POLICIES_DIR."""
    if settings.vectorstore_dir.exists():
        shutil.rmtree(settings.vectorstore_dir)
    raw = load_policies()
    if not raw:
        build_vectorstore([])
        return {"chunks": 0, "files": 0}
    splits = split_docs(raw)
    build_vectorstore(splits)
    return {"chunks": len(splits), "files": len(raw)}
