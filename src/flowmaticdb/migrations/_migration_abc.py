from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flowmaticdb.database import DB


class MigrationABC(ABC):
    @abstractmethod
    def up(self, db: DB) -> None:
        """Apply the change"""

    @abstractmethod
    def down(self, db: DB) -> None:
        """Revert the change"""

    def in_transaction(self) -> bool:
        """Run this migration in a transaction"""

        return True
