_active_worker = None

_switching = False


def is_simulator(worker) -> bool:
    """Command injection is supported by both workers; it does not identify simulation."""
    return getattr(worker, "is_simulator", False) is True
