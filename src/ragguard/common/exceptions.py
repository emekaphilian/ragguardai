class RAGGuardError(Exception):
    pass

class IngestionError(RAGGuardError):
    pass

class RetrievalError(RAGGuardError):
    pass

class RepairError(RAGGuardError):
    pass

class ValidationError(RAGGuardError):
    pass
