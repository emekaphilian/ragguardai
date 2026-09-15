import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ragguard.ingestion.loaders import load_directory
from ragguard.ingestion.document_processor import process_document
from ragguard.storage.vector_store import VectorStore

def main():
    docs = load_directory("data/raw")
    store = VectorStore()
    chunks = [c for d in docs for c in process_document(d)]
    store.add(chunks)
    print(f"Loaded {len(docs)} documents and indexed {len(chunks)} chunks.")

if __name__ == "__main__":
    main()
