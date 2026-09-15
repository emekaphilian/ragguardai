class MetadataStore:
    def __init__(self):
        self.items = {}

    def put(self, key, value):
        self.items[key] = value

    def get(self, key, default=None):
        return self.items.get(key, default)
