from __future__ import annotations


class DatabaseError(Exception):
    pass

class AdapterError(Exception):
    pass

class ConnectionLimitError(AdapterError):
    """No connection slot came free within the configured timeout.

    Subclasses :class:`AdapterError` so callers that already catch connection
    trouble keep working without knowing about the limit."""

class DriverError(Exception):
    pass

class QueryError(Exception):
    pass

class QueryWithParamsError(Exception):
    pass
