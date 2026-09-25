"""ChargePlus Source-Specific Ingestion Adapters.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.2 (Build Source-Specific Adapters)
"""

from backend.ingestion.adapters.openchargemap import OpenChargeMapAdapter

__all__ = ["OpenChargeMapAdapter"]
