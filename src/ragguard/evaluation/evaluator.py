from .metrics import evaluate

class Evaluator:
    def evaluate(self, query, answer, retrieval, relevant_ids):
        return evaluate(query, answer, retrieval, relevant_ids)
