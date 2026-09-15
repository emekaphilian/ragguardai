import asyncio

from fastapi import Request

from ragguard.api.exceptions import ragguard_exception_handler
from ragguard.common.exceptions import RetrievalError


def test_retrieval_error_returns_structured_api_response():
    request = Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/api/v1/query",
            "headers": [],
        }
    )

    response = asyncio.run(
        ragguard_exception_handler(
            request,
            RetrievalError("Retrieval failed."),
        )
    )

    assert response.status_code == 500
    assert response.body == (
        b'{"error":{"code":"RETRIEVAL_ERROR",'
        b'"message":"Retrieval failed."}}'
    )
