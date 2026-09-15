from pathlib import Path

class LocalObjectStore:
    def __init__(self, root="data/processed"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_text(self, key, text):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def get_text(self, key):
        return (self.root / key).read_text(encoding="utf-8")
