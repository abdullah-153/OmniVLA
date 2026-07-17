class MockCollection:
    def __init__(self, name):
        self.name = name
        self.items = [] # list of (id, doc, meta)

    def add(self, documents, metadatas, ids):
        for d, m, i in zip(documents, metadatas, ids):
            self.items.append((i, d, m))

    def count(self):
        return len(self.items)

    def query(self, query_texts, n_results, where=None):
        filtered = []
        for i, d, m in self.items:
            match = True
            if where:
                for k, v in where.items():
                    if m.get(k) != v:
                        match = False
            if match:
                filtered.append((d, m))
        
        res_docs = [d for d, m in filtered[:n_results]]
        res_metas = [m for d, m in filtered[:n_results]]
        
        return {
            "documents": [res_docs],
            "metadatas": [res_metas]
        }

    def get(self, where=None):
        res_metas = []
        for i, d, m in self.items:
            match = True
            if where:
                # Handle $and structure
                if "$and" in where:
                    for cond in where["$and"]:
                        for k, v in cond.items():
                            if m.get(k) != v:
                                match = False
                else:
                    for k, v in where.items():
                        if m.get(k) != v:
                            match = False
            if match:
                res_metas.append(m)
        return {"metadatas": res_metas}

class MockClient:
    def __init__(self, *args, **kwargs):
        self.collections = {}

    def get_or_create_collection(self, name):
        if name not in self.collections:
            self.collections[name] = MockCollection(name)
        return self.collections[name]

def PersistentClient(*args, **kwargs):
    return MockClient()
