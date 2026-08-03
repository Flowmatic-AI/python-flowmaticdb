from __future__ import annotations

from abc import ABC, abstractmethod

from flowmaticdb.database import DB


class MigrationABC(ABC):
    def __init__(self, db: DB) -> None:
        self.db = db

    @abstractmethod
    def up(self) -> None:
        """Apply the change"""

    @abstractmethod
    def down(self) -> None:
        """Revert the change"""

    def in_transaction(self) -> bool:
        """Run this migration in a transaction"""

        return True
