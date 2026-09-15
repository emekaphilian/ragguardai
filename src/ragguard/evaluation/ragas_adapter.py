def evaluate_with_ragas(*args, **kwargs):
    try:
        import ragas  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("Install ragas to enable this optional adapter.") from exc
    raise NotImplementedError("Map project schemas to the installed RAGAS version.")
