"""ChargePlus — Canonical Input Contract Constants & Enums.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.1 (Define Canonical Station/Connector Input Contract)

Defines system-wide constants, contract versions, and standard enumeration types
for external data ingestion, normalization, and quality validation.
"""

from enum import Enum
from typing import Final

# Authoritative Contract Specification Version
CONTRACT_VERSION: Final[str] = "1.0.0"

# Geographic bounding boxes for validation
# India geographic bounding box (approximate with marine/island safety margin)
INDIA_LAT_MIN: Final[float] = 6.0
INDIA_LAT_MAX: Final[float] = 38.0
INDIA_LNG_MIN: Final[float] = 68.0
INDIA_LNG_MAX: Final[float] = 98.0

# Mumbai Metropolitan Region (MMR) pilot bounding box
MUMBAI_LAT_MIN: Final[float] = 18.70
MUMBAI_LAT_MAX: Final[float] = 19.50
MUMBAI_LNG_MIN: Final[float] = 72.70
MUMBAI_LNG_MAX: Final[float] = 73.30

# Physical power limits (kW) for plausibility checks
MIN_PLAUSIBLE_POWER_KW: Final[float] = 1.0     # Slow AC outlet (e.g. 15A / 3.3 kW)
MAX_PLAUSIBLE_POWER_KW: Final[float] = 500.0   # Ultra-fast DC megawatt charger limit


class ValidationOutcome(str, Enum):
    """Categorical outcome of data quality contract validation."""
    ACCEPT = "ACCEPT"
    ACCEPT_WITH_WARNINGS = "ACCEPT_WITH_WARNINGS"
    QUARANTINE = "QUARANTINE"
    REJECT = "REJECT"


class OperationalStatus(str, Enum):
    """Station-level physical operational state.
    
    Matches public.stations.operational_status constraint:
    ('unknown', 'operational', 'temporarily_unavailable', 'permanently_closed')
    """
    OPERATIONAL = "operational"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    PERMANENTLY_CLOSED = "permanently_closed"
    UNKNOWN = "unknown"


class AvailabilityStatus(str, Enum):
    """Point-in-time observed connector/station occupancy state.
    
    Matches public.station_observations.availability_status constraint:
    ('available', 'busy', 'broken', 'unknown')
    """
    AVAILABLE = "available"
    BUSY = "busy"
    BROKEN = "broken"
    UNKNOWN = "unknown"


class QueueLevel(str, Enum):
    """Point-in-time observed queue severity.
    
    Matches public.station_observations.queue_level constraint:
    ('none', 'short', 'medium', 'long', 'unknown')
    """
    NONE = "none"
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"
    UNKNOWN = "unknown"


class StandardConnectorType(str, Enum):
    """Standardized connector mechanical and electrical interfaces.
    
    Maps external source labels into ChargePlus canonical types supported
    by public.connectors.connector_type.
    """
    CCS2 = "CCS2"
    CCS1 = "CCS1"
    CHADEMO = "CHAdeMO"
    TYPE_2 = "Type 2"
    TYPE_1 = "Type 1"
    GB_T = "GB/T"
    BHARAT_AC001 = "Bharat AC001"
    BHARAT_DC001 = "Bharat DC001"
    OTHER = "Other"


class PricingType(str, Enum):
    """Broad pricing classification without fabricating rate details."""
    FREE = "free"
    PAID = "paid"
    UNKNOWN = "unknown"
