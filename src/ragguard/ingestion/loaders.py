from pathlib import Path
from ragguard.common.schemas import Document

def load_text_file(path: str | Path) -> Document:
    p = Path(path)
    return Document(document_id=p.stem, text=p.read_text(encoding="utf-8"), metadata={"source": str(p)})

def load_directory(path: str | Path) -> list[Document]:
    return [load_text_file(p) for p in sorted(Path(path).glob("*.txt"))]
