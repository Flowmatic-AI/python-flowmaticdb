from enum import StrEnum


class PubSubBackendEnum(StrEnum):
    """Which delivery mechanism a database's pubsub uses.

    Passed as the ``pubsub_backend`` option to any ``connect_*()``; left unset,
    the backend follows the dialect -- PostgreSQL pushes, MySQL polls, SQLite
    stays in process.

    A StrEnum because options often arrive from configuration as plain strings:
    ``"memory"`` and ``PubSubBackendEnum.MEMORY`` are interchangeable, while a
    misspelling is refused rather than silently falling back to the default.

    Naming one explicitly is mostly for a custom dialect, where the library has
    no basis for guessing. Prefer POLLING there: it is the only member that
    delivers between processes on a database this library has never seen, and it
    fails loudly when a dialect cannot express its SQL. MEMORY never fails and
    never crosses a process boundary, which is a silent hole in any deployment
    running more than one worker."""

    MEMORY = "memory"
    POLLING = "polling"
    POSTGRES = "postgres"
