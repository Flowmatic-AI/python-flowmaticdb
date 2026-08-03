from __future__ import annotations


class DatabaseError(Exception):
    pass

class AdapterError(DatabaseError):
    pass

class DriverError(DatabaseError):
    pass

class QueryError(DatabaseError):
    pass

class QueryWithParamsError(DatabaseError):
    pass