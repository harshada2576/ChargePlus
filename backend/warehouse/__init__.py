"""ChargePlus — Analytical Warehouse (Phase 4/6).

Layer B (OLAP): Python ETL jobs moving legitimate operational history
from public (OLTP) into analytics (warehouse). Deterministic, idempotent,
provenance-preserving. No synthetic history, ever.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.warehouse.etl import WarehouseETL, WarehouseSummary

__all__ = ["WarehouseETL", "WarehouseSummary"]


def __getattr__(name: str):
    if name in ("WarehouseETL", "WarehouseSummary"):
        from backend.warehouse.etl import WarehouseETL, WarehouseSummary
        return {"WarehouseETL": WarehouseETL, "WarehouseSummary": WarehouseSummary}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
