from fastapi import Request
from fastapi.responses import JSONResponse

from ragguard.common.exceptions import (
    IngestionError,
    RAGGuardError,
    RepairError,
    RetrievalError,
    ValidationError,
)

_ERROR_CODES = {
    IngestionError: "INGESTION_ERROR",
    RetrievalError: "RETRIEVAL_ERROR",
    RepairError: "REPAIR_ERROR",
    ValidationError: "VALIDATION_ERROR",
    RAGGuardError: "RAGGUARD_ERROR",
}

async def ragguard_exception_handler(
    request: Request,
    exc: RAGGuardError,
) -> JSONResponse:
    error_code = _ERROR_CODES.get(type(exc), "RAGGUARD_ERROR")

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": error_code,
                "message": str(exc),
            }
        },
    )
