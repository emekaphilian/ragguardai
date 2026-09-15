from contextlib import contextmanager
import time
import uuid

@contextmanager
def trace(name):
    trace_id = str(uuid.uuid4())
    start = time.perf_counter()
    payload = {"trace_id": trace_id, "name": name}
    try:
        yield payload
    finally:
        payload["duration_ms"] = (time.perf_counter() - start) * 1000
