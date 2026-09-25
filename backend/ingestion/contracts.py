"""ChargePlus — Canonical Station, Connector & Observation Data Contracts.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.1 (Define Canonical Station/Connector Input Contract)

Defines strongly-typed, source-neutral Pydantic models for:
- Layer 1: RawSourceRecord (unaltered external payload & retrieval metadata)
- Layer 2: NormalizedStationRecord, NormalizedConnectorRecord, NormalizedObservationRecord
- Layer 3/4/5: Canonical operational representations (stations, connectors, observations)

Key Principles:
- Source Neutrality: No single external provider defines our schema.
- Missing means Missing: Missing values are None/null, never fabricated (0 kW, free ₹0, etc.).
- Provenance Preserved: Every normalized record retains origin identifiers and hashes.
- Connector Flexibility: Supports both individually identified plugs and aggregated counts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field, validator

from backend.ingestion.constants import (
    CONTRACT_VERSION,
    AvailabilityStatus,
    OperationalStatus,
    PricingType,
    QueueLevel,
    StandardConnectorType,
)


class RawSourceRecord(BaseModel):
    """Layer 1 — Verbatim Raw Source Record.
    
    Preserves exactly what an external adapter retrieved before any lossy parsing
    or normalization. Never silently rewritten.
    """
    source_id: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Unique identifier of external data source (e.g. 'open_charge_map', 'tata_power_api')"
    )
    source_station_id: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="External source station primary key / record identifier"
    )
    retrieval_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when ChargePlus adapter fetched this record"
    )
    source_timestamp: Optional[datetime] = Field(
        default=None,
        description="Timestamp reported by source for this record, if provided"
    )
    source_url: Optional[str] = Field(
        default=None,
        description="Web URL / API endpoint reference for this external entity"
    )
    raw_payload: dict[str, Any] = Field(
        ...,
        description="Verbatim unaltered dictionary/JSON received from source"
    )
    source_priority: int = Field(
        default=100,
        description="Configured priority for conflict resolution in multi-source ingestion"
    )

    class Config:
        extra = "allow"
        allow_mutation = False

    @property
    def payload_hash(self) -> str:
        """Computes deterministic SHA-256 hash of raw_payload for change detection and idempotency."""
        serialized = json.dumps(self.raw_payload, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def to_provenance(self) -> ProvenanceInfo:
        """Generates a ProvenanceInfo object from this raw source record."""
        return ProvenanceInfo(
            source_id=self.source_id,
            source_station_id=self.source_station_id,
            retrieval_timestamp=self.retrieval_timestamp,
            source_timestamp=self.source_timestamp,
            source_url=self.source_url,
            raw_payload_hash=self.payload_hash,
            contract_version=CONTRACT_VERSION,
        )


class ProvenanceInfo(BaseModel):
    """Provenance tracking information for ingested entities."""
    source_id: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Unique identifier of data source"
    )
    source_station_id: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Provider primary record key"
    )
    retrieval_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when record was retrieved"
    )
    source_timestamp: Optional[datetime] = Field(
        default=None,
        description="Timestamp reported by external source if available"
    )
    source_url: Optional[str] = Field(
        default=None,
        description="URL or endpoint reference"
    )
    raw_payload_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="SHA-256 hash of Layer 1 payload"
    )
    contract_version: str = Field(
        default=CONTRACT_VERSION,
        description="Contract version at time of ingestion"
    )

    class Config:
        extra = "forbid"


class NormalizedConnectorRecord(BaseModel):
    """Layer 2 — Normalized Connector Record.
    
    Standardizes charging point capabilities while retaining original raw labels.
    Supports both individual plugs and aggregated capacity groups without fabricating IDs.
    """
    source_connector_id: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Individual physical connector ID if source identifies plugs individually; None if aggregated"
    )
    connector_type: str = Field(
        ...,
        description="Normalized connector standard (e.g. 'CCS2', 'Type 2', 'CHAdeMO', 'Other')"
    )
    raw_connector_type: str = Field(
        ...,
        description="Exact raw label or code string provided by external source before normalization"
    )
    charging_standard: Optional[str] = Field(
        default=None,
        max_length=120,
        description="Underlying electrical standard if reported (e.g. 'IEC 62196-3', 'GB/T 20234')"
    )
    power_kw: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Peak output power in kilowatts (kW). Must be positive. None if missing, NEVER 0.0"
    )
    voltage_v: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Rated voltage in Volts (V) if reported by source"
    )
    amperage_a: Optional[float] = Field(
        default=None,
        gt=0.0,
        description="Rated current in Amperes (A) if reported by source"
    )
    quantity: int = Field(
        default=1,
        ge=1,
        description="Number of physical chargers matching this specification (supports aggregated sources)"
    )
    is_aggregated: bool = Field(
        default=False,
        description="True if quantity > 1 represents an aggregated group rather than a single physical plug"
    )
    pricing_type: PricingType = Field(
        default=PricingType.UNKNOWN,
        description="Pricing category: free, paid, or unknown. NEVER assumed free if omitted"
    )
    price_per_kwh: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Price in specified currency per kWh. None if unknown; NEVER 0.0 unless confirmed free"
    )
    price_per_session: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Fixed connection or session fee if applicable"
    )
    currency: str = Field(
        default="INR",
        min_length=1,
        max_length=10,
        description="Currency code for tariff (default 'INR')"
    )
    status: Optional[AvailabilityStatus] = Field(
        default=None,
        description="Real-time occupancy status if reported at individual connector level"
    )

    class Config:
        extra = "forbid"

    @validator("power_kw")
    def validate_power(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("power_kw must be strictly positive (> 0); cannot be 0.0 or negative")
        return v


class NormalizedObservationRecord(BaseModel):
    """Layer 2 & 5 — Normalized Station/Connector Telemetry Observation.
    
    Point-in-time evidence stream distinct from static station identity.
    Reflects telemetry snapshots, status polling, or real-time vendor feeds.
    """
    source_id: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Identifier of data source providing this observation"
    )
    source_station_id: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Source station identifier"
    )
    source_connector_id: Optional[str] = Field(
        default=None,
        description="Source connector identifier if observation is connector-specific"
    )
    observed_at: datetime = Field(
        ...,
        description="Timestamp when event occurred in reality or at upstream source"
    )
    retrieved_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when ChargePlus ingested the telemetry"
    )
    availability_status: AvailabilityStatus = Field(
        default=AvailabilityStatus.UNKNOWN,
        description="Observed availability state: available, busy, broken, unknown"
    )
    queue_level: QueueLevel = Field(
        default=QueueLevel.UNKNOWN,
        description="Observed queue state: none, short, medium, long, unknown"
    )
    available_connectors: Optional[int] = Field(
        default=None,
        ge=0,
        description="Count of currently vacant plugs. None if source does not report count"
    )
    total_connectors: Optional[int] = Field(
        default=None,
        ge=0,
        description="Total connector count observed at this timestamp"
    )
    raw_status_label: Optional[str] = Field(
        default=None,
        description="Exact raw status string from external source (e.g. 'In Use', 'Faulted', 'Available')"
    )
    confidence_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Estimated confidence in telemetry (0.0 to 1.0) based on source latency and quality"
    )
    source_payload_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of raw telemetry payload"
    )

    class Config:
        extra = "forbid"

    @validator("available_connectors")
    def validate_connector_counts(cls, v: Optional[int], values) -> Optional[int]:
        total = values.get("total_connectors")
        if v is not None and total is not None and v > total:
            raise ValueError(f"available_connectors ({v}) cannot exceed total_connectors ({total})")
        return v


class NormalizedStationRecord(BaseModel):
    """Layer 2 — Normalized Station Record.
    
    Standardized, source-neutral representation of a physical charging location
    produced by a Python source adapter before entity resolution or database insertion.
    """
    # Provenance Identity (Layer 1 connection)
    contract_version: str = Field(
        default=CONTRACT_VERSION,
        description="ChargePlus canonical contract version"
    )
    source_id: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="Unique source registry identifier (e.g. 'open_charge_map', 'plugshare')"
    )
    source_station_id: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="External source primary record key"
    )
    source_url: Optional[str] = Field(
        default=None,
        description="Canonical URL of this station on external provider site"
    )
    raw_payload_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 hash of original raw payload for change detection"
    )

    # Physical Station Identity
    name: str = Field(
        ...,
        min_length=2,
        max_length=300,
        description="Cleaned, standardized display name of charging station"
    )
    raw_name: Optional[str] = Field(
        default=None,
        description="Original name string before whitespace trimming or title casing"
    )

    # Ownership / Operator
    operator_name: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Commercial operator name (e.g. 'Tata Power EZ Charge', 'Jio-bp pulse')"
    )
    operator_slug: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Normalized safe slug token for operator mapping (e.g. 'tata-power', 'jio-bp')"
    )

    # Geospatial Coordinates (Strictly mandatory for discovery)
    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="WGS 84 latitude in decimal degrees. Must be within [-90, 90]"
    )
    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="WGS 84 longitude in decimal degrees. Must be within [-180, 180]"
    )

    # Address & Hierarchy
    address_line: Optional[str] = Field(
        default=None,
        description="Street address, building name, or road specification"
    )
    locality: Optional[str] = Field(
        default=None,
        description="Neighborhood, suburb, or district (e.g. 'Bandra West', 'Andheri East')"
    )
    city: str = Field(
        default="Mumbai",
        min_length=1,
        max_length=120,
        description="City name (defaults to 'Mumbai' for pilot, India-ready)"
    )
    state: str = Field(
        default="Maharashtra",
        min_length=1,
        max_length=120,
        description="State or province name (defaults to 'Maharashtra')"
    )
    postal_code: Optional[str] = Field(
        default=None,
        max_length=20,
        description="Postal / PIN code (e.g. '400050'). Validated against country rules"
    )
    country: str = Field(
        default="India",
        min_length=1,
        max_length=120,
        description="Country name (defaults to 'India')"
    )

    # Operational & Access Attributes
    is_24_hours: Optional[bool] = Field(
        default=None,
        description="True if open 24 hours daily; None if unknown"
    )
    opening_time: Optional[str] = Field(
        default=None,
        description="Opening time in HH:MM format (24-hour clock)"
    )
    closing_time: Optional[str] = Field(
        default=None,
        description="Closing time in HH:MM format (24-hour clock)"
    )
    access_type: Optional[str] = Field(
        default=None,
        description="Access restriction descriptor (e.g. 'Public', 'Customer Only', 'Restricted')"
    )
    is_public: bool = Field(
        default=True,
        description="True if accessible to general public drivers"
    )
    operational_status: OperationalStatus = Field(
        default=OperationalStatus.UNKNOWN,
        description="Physical site operational state ('operational', 'temporarily_unavailable', etc.)"
    )

    # Contact & External References
    phone: Optional[str] = Field(
        default=None,
        description="Support or site telephone number"
    )
    website_url: Optional[str] = Field(
        default=None,
        description="Operator or site specific website URL"
    )

    # Child Entities
    connectors: list[NormalizedConnectorRecord] = Field(
        default_factory=list,
        description="List of charging connectors available at this physical station"
    )
    observation: Optional[NormalizedObservationRecord] = Field(
        default=None,
        description="Initial telemetry observation accompanying this record, if present"
    )

    # Source-Specific Extension Payload
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific attributes (parking fees, amenities, network flags) preserved without schema pollution"
    )

    class Config:
        extra = "forbid"

    @validator("longitude")
    def validate_not_null_island(cls, v: float, values) -> float:
        """Detects and rejects (0.0, 0.0) placeholder coordinates (Null Island)."""
        lat = values.get("latitude")
        if lat is not None and abs(lat) < 1e-6 and abs(v) < 1e-6:
            raise ValueError("Coordinates (0.0, 0.0) indicate placeholder/missing geolocation (Null Island)")
        return v
