"""ChargePlus Ingestion Module.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.1 (Define Canonical Station/Connector Input Contract)
"""

from backend.ingestion.base import (
    AdapterResult,
    BaseSourceAdapter,
    BatchAdapterResult,
)
from backend.ingestion.adapters.openchargemap import OpenChargeMapAdapter
from backend.ingestion.constants import (
    CONTRACT_VERSION,
    AvailabilityStatus,
    OperationalStatus,
    PricingType,
    QueueLevel,
    StandardConnectorType,
    ValidationOutcome,
)
from backend.ingestion.contracts import (
    NormalizedConnectorRecord,
    NormalizedObservationRecord,
    NormalizedStationRecord,
    ProvenanceInfo,
    RawSourceRecord,
)
from backend.ingestion.validation import DataQualityValidator, ValidationResult

from backend.ingestion.persistence import (
    IngestionPersistenceService,
    PersistenceStatus,
    StationPersistenceResult,
)
from backend.ingestion.runner import (
    IngestionRunner,
    IngestionSummary,
)

__all__ = [
    "CONTRACT_VERSION",
    "AvailabilityStatus",
    "OperationalStatus",
    "PricingType",
    "QueueLevel",
    "StandardConnectorType",
    "ValidationOutcome",
    "RawSourceRecord",
    "ProvenanceInfo",
    "NormalizedConnectorRecord",
    "NormalizedObservationRecord",
    "NormalizedStationRecord",
    "DataQualityValidator",
    "ValidationResult",
    "BaseSourceAdapter",
    "AdapterResult",
    "BatchAdapterResult",
    "OpenChargeMapAdapter",
    "IngestionPersistenceService",
    "PersistenceStatus",
    "StationPersistenceResult",
    "IngestionRunner",
    "IngestionSummary",
]
