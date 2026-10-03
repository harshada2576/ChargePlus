"""OpenChargeMap (OCM) Representative Test Fixture Payloads.

Phase: 2/6 (Real Data Ingestion & Data Quality)
Step: 2.2 (Build Source-Specific Adapters)

These fixtures replicate authentic OpenChargeMap v3 POI JSON response structures
for deterministic, offline testing of the OpenChargeMapAdapter.

All fixtures are explicitly labeled as TEST FIXTURES and are isolated from production.
"""

from typing import Any

# 1. Complete Valid Station (Mumbai, BKC, Tata Power Fast Charger)
OCM_FIXTURE_01_VALID_COMPLETE: dict[str, Any] = {
    "ID": 192840,
    "UUID": "E9A8C234-F123-4567-89AB-CDEF01234567",
    "DataProvider": {
        "ID": 1,
        "Title": "Open Charge Map Contributors",
        "WebsiteURL": "https://openchargemap.org",
    },
    "OperatorInfo": {
        "ID": 332,
        "Title": "Tata Power EZ Charge",
        "WebsiteURL": "https://www.tatapower.com/ev-charging",
    },
    "UsageType": {
        "ID": 1,
        "Title": "Public",
    },
    "UsageCost": "₹18.50 per kWh + GST",
    "AddressInfo": {
        "ID": 193180,
        "Title": "Tata Power - BKC Fast Charging Hub",
        "AddressLine1": "G Block, Bandra Kurla Complex",
        "AddressLine2": "Near MCA Club",
        "Town": "Mumbai",
        "StateOrProvince": "Maharashtra",
        "Postcode": "400051",
        "Country": {
            "ID": 106,
            "ISOCode": "IN",
            "Title": "India",
        },
        "Latitude": 19.0657,
        "Longitude": 72.8686,
        "ContactTelephone1": "+91-22-67171000",
        "RelatedURL": "https://www.tatapower.com",
    },
    "Connections": [
        {
            "ID": 312450,
            "ConnectionTypeID": 33,  # CCS (Type 2)
            "ConnectionType": {
                "ID": 33,
                "Title": "CCS (Type 2)",
                "FormalName": "IEC 62196-3 Configuration FF",
            },
            "Quantity": 1,
            "PowerKW": 60.0,
            "Voltage": 400.0,
            "Amps": 150.0,
            "CurrentType": {
                "ID": 30,
                "Title": "DC",
            },
            "StatusTypeID": 50,  # Operational
        }
    ],
    "NumberOfPoints": 1,
    "GeneralComments": "Open 24/7 public fast charging station.",
    "StatusTypeID": 50,  # Operational
    "StatusType": {
        "ID": 50,
        "Title": "Operational",
        "IsOperational": True,
    },
    "DateLastStatusUpdate": "2024-03-15T10:30:00Z",
    "DateCreated": "2023-01-10T08:00:00Z",
    "SubmissionStatusTypeID": 200,
}

# 2. Multiple Connectors (CCS2 + Type 2 + CHAdeMO)
OCM_FIXTURE_02_MULTIPLE_CONNECTORS: dict[str, Any] = {
    "ID": 192841,
    "UUID": "A1B2C3D4-E5F6-7890-ABCD-EF1234567890",
    "OperatorInfo": {
        "ID": 450,
        "Title": "Jio-bp pulse",
    },
    "AddressInfo": {
        "Title": "Jio-bp pulse Hub - Worli",
        "AddressLine1": "Dr Annie Besant Road, Worli",
        "Town": "Mumbai",
        "StateOrProvince": "Maharashtra",
        "Postcode": "400018",
        "Country": {"ISOCode": "IN", "Title": "India"},
        "Latitude": 19.0144,
        "Longitude": 72.8181,
    },
    "Connections": [
        {
            "ID": 401,
            "ConnectionTypeID": 33,  # CCS2
            "ConnectionType": {"Title": "CCS (Type 2)"},
            "Quantity": 2,
            "PowerKW": 120.0,
        },
        {
            "ID": 402,
            "ConnectionTypeID": 25,  # Type 2
            "ConnectionType": {"Title": "Type 2 (Socket Only)"},
            "Quantity": 1,
            "PowerKW": 22.0,
        },
        {
            "ID": 403,
            "ConnectionTypeID": 2,  # CHAdeMO
            "ConnectionType": {"Title": "CHAdeMO"},
            "Quantity": 1,
            "PowerKW": 50.0,
        },
    ],
    "StatusTypeID": 50,
}

# 3. Aggregated Connectors (Quantity > 1, no individual connection IDs)
OCM_FIXTURE_03_AGGREGATED_CONNECTORS: dict[str, Any] = {
    "ID": 192842,
    "UUID": "B2C3D4E5-F6A1-8901-BCDE-F12345678901",
    "AddressInfo": {
        "Title": "Fleet Depot Aggregated Chargers",
        "AddressLine1": "Marol, Andheri East",
        "Town": "Mumbai",
        "StateOrProvince": "Maharashtra",
        "Postcode": "400059",
        "Country": {"ISOCode": "IN", "Title": "India"},
        "Latitude": 19.1170,
        "Longitude": 72.8790,
    },
    "Connections": [
        {
            # Note: No ID provided for individual plugs
            "ConnectionTypeID": 33,  # CCS2
            "ConnectionType": {"Title": "CCS (Type 2)"},
            "Quantity": 4,  # 4 aggregated CCS2 plugs
            "PowerKW": 60.0,
        }
    ],
    "StatusTypeID": 50,
}

# 4. Missing Optional Fields (No phone, website, locality, opening hours)
OCM_FIXTURE_04_MISSING_OPTIONAL_FIELDS: dict[str, Any] = {
    "ID": 192843,
    "AddressInfo": {
        "Title": "Minimal Community Charger",
        "AddressLine1": "Near Station Road",
        "Town": "Mumbai",
        "StateOrProvince": "Maharashtra",
        "Country": {"ISOCode": "IN", "Title": "India"},
        "Latitude": 19.0500,
        "Longitude": 72.8500,
        # ContactTelephone1, RelatedURL, AddressLine2, Postcode are omitted
    },
    "Connections": [
        {
            "ConnectionTypeID": 25,
            "PowerKW": 7.4,
        }
    ],
}

# 5. Unknown / Custom Connector Type
OCM_FIXTURE_05_UNKNOWN_CONNECTOR_TYPE: dict[str, Any] = {
    "ID": 192844,
    "AddressInfo": {
        "Title": "Experimental Tech Lab Charger",
        "AddressLine1": "Powai",
        "Town": "Mumbai",
        "StateOrProvince": "Maharashtra",
        "Country": {"ISOCode": "IN", "Title": "India"},
        "Latitude": 19.1200,
        "Longitude": 72.9050,
    },
    "Connections": [
        {
            "ID": 501,
            "ConnectionTypeID": 9999,  # Non-standard ID
            "ConnectionType": {
                "ID": 9999,
                "Title": "Custom Magnetic Resonant Coupler",
            },
            "PowerKW": 11.0,
        }
    ],
}

# 6. Missing Power (PowerKW is null / omitted; should be None, NEVER 0 kW)
OCM_FIXTURE_06_MISSING_POWER: dict[str, Any] = {
    "ID": 192845,
    "AddressInfo": {
        "Title": "Hotel Valet Charger",
        "AddressLine1": "Juhu Tara Road",
        "Town": "Mumbai",
        "StateOrProvince": "Maharashtra",
        "Country": {"ISOCode": "IN", "Title": "India"},
        "Latitude": 19.0980,
        "Longitude": 72.8260,
    },
    "Connections": [
        {
            "ID": 601,
            "ConnectionTypeID": 25,  # Type 2
            "ConnectionType": {"Title": "Type 2"},
            # PowerKW omitted
        }
    ],
}

# 7. Valid Zero Latitude on Equator (lat=0.0, lng=32.5; valid non-zero longitude)
OCM_FIXTURE_07_VALID_EQUATOR: dict[str, Any] = {
    "ID": 192846,
    "AddressInfo": {
        "Title": "Equator Crossing Charging Stop",
        "AddressLine1": "Masaka Road, Kayabwe",
        "Town": "Kayabwe",
        "StateOrProvince": "Central",
        "Country": {"ISOCode": "UG", "Title": "Uganda"},
        "Latitude": 0.0,  # Valid zero latitude
        "Longitude": 32.0,  # Non-zero longitude
    },
    "Connections": [{"ConnectionTypeID": 33, "PowerKW": 50.0}],
}

# 8. Valid Zero Longitude on Prime Meridian (lat=51.4769, lng=0.0; valid non-zero latitude)
OCM_FIXTURE_08_VALID_PRIME_MERIDIAN: dict[str, Any] = {
    "ID": 192847,
    "AddressInfo": {
        "Title": "Royal Observatory EV Point",
        "AddressLine1": "Blackheath Ave",
        "Town": "London",
        "StateOrProvince": "Greater London",
        "Postcode": "SE10 8XJ",
        "Country": {"ISOCode": "GB", "Title": "United Kingdom"},
        "Latitude": 51.4769,  # Non-zero latitude
        "Longitude": 0.0,      # Valid zero longitude
    },
    "Connections": [{"ConnectionTypeID": 33, "PowerKW": 50.0}],
}

# 9. Null Island (lat=0.0, lng=0.0; MUST be rejected)
OCM_FIXTURE_09_NULL_ISLAND: dict[str, Any] = {
    "ID": 192848,
    "AddressInfo": {
        "Title": "Bogus Geolocation Station",
        "AddressLine1": "Gulf of Guinea",
        "Town": "Unknown",
        "Latitude": 0.0,
        "Longitude": 0.0,
    },
    "Connections": [{"ConnectionTypeID": 33, "PowerKW": 50.0}],
}

# 10. Non-India Station (UK location; valid coordinates, but outside India box)
OCM_FIXTURE_10_NON_INDIA: dict[str, Any] = {
    "ID": 192849,
    "AddressInfo": {
        "Title": "London Heathrow Terminal 5 Supercharger",
        "AddressLine1": "Western Perimeter Road",
        "Town": "London",
        "Postcode": "TW6 2GA",
        "Country": {"ISOCode": "GB", "Title": "United Kingdom"},
        "Latitude": 51.4700,
        "Longitude": -0.4543,
    },
    "Connections": [{"ConnectionTypeID": 33, "PowerKW": 150.0}],
}

# 11. Malformed Coordinate (Non-numeric string)
OCM_FIXTURE_11_MALFORMED_COORDS: dict[str, Any] = {
    "ID": 192850,
    "AddressInfo": {
        "Title": "Corrupt Coordinate Station",
        "AddressLine1": "Linking Road",
        "Town": "Mumbai",
        "Latitude": "corrupt_latitude_string",
        "Longitude": 72.83,
    },
}

# 12. Malformed Power (Negative or non-numeric power in source)
OCM_FIXTURE_12_MALFORMED_POWER: dict[str, Any] = {
    "ID": 192851,
    "AddressInfo": {
        "Title": "Faulty Power Meter Station",
        "AddressLine1": "SVT Road",
        "Town": "Mumbai",
        "Latitude": 19.07,
        "Longitude": 72.87,
    },
    "Connections": [
        {
            "ID": 1201,
            "ConnectionTypeID": 33,
            "PowerKW": -50.0,  # Negative power in source feed
        }
    ],
}

# 13. Availability Telemetry Represented (StatusTypeID 10 "Currently Available (Automated)")
OCM_FIXTURE_13_TELEMETRY_AVAILABLE: dict[str, Any] = {
    "ID": 192852,
    "AddressInfo": {
        "Title": "Live Telemetry Enabled Station",
        "AddressLine1": "Nariman Point",
        "Town": "Mumbai",
        "Latitude": 18.9256,
        "Longitude": 72.8242,
    },
    "Connections": [
        {
            "ID": 1301,
            "ConnectionTypeID": 33,
            "PowerKW": 60.0,
            "StatusTypeID": 10,  # Automated live status: Currently Available
        }
    ],
    "StatusTypeID": 10,  # Automated status: Available
    "StatusType": {
        "ID": 10,
        "Title": "Currently Available (Automated Status)",
        "IsOperational": True,
    },
    "DateLastStatusUpdate": "2024-03-20T14:15:00Z",
}

# 14. Missing Availability (StatusTypeID 50 "Operational" static status -> availability is unknown)
OCM_FIXTURE_14_STATIC_OPERATIONAL_NOT_AVAILABLE: dict[str, Any] = {
    "ID": 192853,
    "AddressInfo": {
        "Title": "Static Operational Hub",
        "AddressLine1": "Dadar West",
        "Town": "Mumbai",
        "Latitude": 19.0200,
        "Longitude": 72.8400,
    },
    "Connections": [{"ConnectionTypeID": 33, "PowerKW": 50.0}],
    "StatusTypeID": 50,  # Operational (Static metadata, NOT live availability)
    "StatusType": {"ID": 50, "Title": "Operational", "IsOperational": True},
    # DateLastStatusUpdate absent
}

# 15. Source-Specific Extra Fields (DataProvider, UUID, GeneralComments, NumberOfPoints, UsageCost)
OCM_FIXTURE_15_EXTRA_FIELDS: dict[str, Any] = {
    "ID": 192854,
    "UUID": "FEEDCAFE-1234-5678-9ABC-DEF012345678",
    "DataProvider": {
        "ID": 18,
        "Title": "National Charge Point Registry",
        "License": "Open Government Licence v2.0",
    },
    "NumberOfPoints": 8,
    "GeneralComments": "Located in underground parking level B2. Height limit 2.1m.",
    "UsageCost": "Free parking for first 2 hours, then ₹50/hr.",
    "SubmissionStatusTypeID": 200,
    "AddressInfo": {
        "Title": "Mall Underground Charging Plaza",
        "AddressLine1": "Goregaon East",
        "Town": "Mumbai",
        "Latitude": 19.1650,
        "Longitude": 72.8600,
    },
    "Connections": [{"ConnectionTypeID": 25, "PowerKW": 22.0}],
}

# 16. Duplicate Identical Payload (For testing SHA-256 hash determinism)
OCM_FIXTURE_16_DUPLICATE_A: dict[str, Any] = {
    "ID": 192855,
    "AddressInfo": {
        "Title": "Idempotent Hash Test Charger",
        "AddressLine1": "Chembur",
        "Town": "Mumbai",
        "Latitude": 19.0600,
        "Longitude": 72.8900,
    },
    "Connections": [{"ConnectionTypeID": 33, "PowerKW": 50.0}],
}

# 17. Unexpected / Malformed Record Structure (Empty dictionary)
OCM_FIXTURE_17_MALFORMED_RECORD: dict[str, Any] = {}

# 18. Missing Source Station ID (Neither ID nor UUID present)
OCM_FIXTURE_18_MISSING_STATION_ID: dict[str, Any] = {
    "AddressInfo": {
        "Title": "Station Without Any Provider ID",
        "AddressLine1": "Colaba Causeway",
        "Town": "Mumbai",
        "Latitude": 18.9100,
        "Longitude": 72.8200,
    },
    "Connections": [{"ConnectionTypeID": 33, "PowerKW": 50.0}],
}
