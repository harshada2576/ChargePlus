"""
backend/ingestion/ingest_stations.py
ChargePlus — Phase 2 Real Data Ingestion (Mumbai Pilot)
Extracts and normalizes charging stations across Mumbai metropolitan areas.
"""

import json
import uuid
import os

MUMBAI_STATIONS_DATA = [
    {
        "name": "Tata Power EZ Charge — Bandra Kurla Complex",
        "operator": "Tata Power",
        "locality": "Bandra Kurla Complex",
        "address": "G Block, BKC, Bandra East, Mumbai",
        "latitude": 19.0662,
        "longitude": 72.8688,
        "postal_code": "400051",
        "is_24_hours": True,
        "connectors": [
            {"connector_type": "CCS2", "power_kw": 60.0, "quantity": 2, "price_per_kwh": 18.50},
            {"connector_type": "Type 2", "power_kw": 22.0, "quantity": 2, "price_per_kwh": 15.00}
        ]
    },
    {
        "name": "Jio-bp pulse EV Hub — Andheri East",
        "operator": "Jio-bp",
        "locality": "Andheri East",
        "address": "Sahar Road, Near Western Express Highway, Andheri East",
        "latitude": 19.1172,
        "longitude": 72.8532,
        "postal_code": "400069",
        "is_24_hours": True,
        "connectors": [
            {"connector_type": "CCS2", "power_kw": 120.0, "quantity": 4, "price_per_kwh": 21.00},
            {"connector_type": "Type 2", "power_kw": 22.0, "quantity": 2, "price_per_kwh": 16.00}
        ]
    },
    {
        "name": "Statiq Charging Hub — Lower Parel High Street Phoenix",
        "operator": "Statiq",
        "locality": "Lower Parel",
        "address": "Grand Galleria Parking, Senapati Bapat Marg, Lower Parel",
        "latitude": 18.9958,
        "longitude": 72.8252,
        "postal_code": "400013",
        "is_24_hours": False,
        "opening_time": "08:00:00",
        "closing_time": "23:00:00",
        "connectors": [
            {"connector_type": "CCS2", "power_kw": 60.0, "quantity": 2, "price_per_kwh": 19.00},
            {"connector_type": "CHAdeMO", "power_kw": 50.0, "quantity": 1, "price_per_kwh": 19.00}
        ]
    },
    {
        "name": "Ather Grid Fast Charger — Hiranandani Powai",
        "operator": "Ather Energy",
        "locality": "Powai",
        "address": "Galleria Shopping Mall, Hiranandani Gardens, Powai",
        "latitude": 19.1197,
        "longitude": 72.9056,
        "postal_code": "400076",
        "is_24_hours": True,
        "connectors": [
            {"connector_type": "Type 2", "power_kw": 22.0, "quantity": 3, "price_per_kwh": 14.50},
            {"connector_type": "Bharat AC001", "power_kw": 15.0, "quantity": 2, "price_per_kwh": 12.00}
        ]
    },
    {
        "name": "ChargeZone Fast Hub — Mumbai Airport T2",
        "operator": "ChargeZone",
        "locality": "Sahar",
        "address": "P4 Parking Level, Chhatrapati Shivaji Maharaj International Airport T2",
        "latitude": 19.0974,
        "longitude": 72.8744,
        "postal_code": "400099",
        "is_24_hours": True,
        "connectors": [
            {"connector_type": "CCS2", "power_kw": 120.0, "quantity": 4, "price_per_kwh": 22.50},
            {"connector_type": "CCS2", "power_kw": 60.0, "quantity": 2, "price_per_kwh": 19.50}
        ]
    },
    {
        "name": "Magenta ChargeGrid — Vashi Sector 17",
        "operator": "Magenta Mobility",
        "locality": "Navi Mumbai",
        "address": "Sector 17 Market Complex, Vashi, Navi Mumbai",
        "latitude": 19.0771,
        "longitude": 72.9986,
        "postal_code": "400703",
        "is_24_hours": True,
        "connectors": [
            {"connector_type": "CCS2", "power_kw": 50.0, "quantity": 2, "price_per_kwh": 17.00},
            {"connector_type": "Type 2", "power_kw": 11.0, "quantity": 2, "price_per_kwh": 13.00}
        ]
    },
    {
        "name": "Tata Power EZ — Oberoi Mall Goregaon",
        "operator": "Tata Power",
        "locality": "Goregaon East",
        "address": "Western Express Highway, Yashodham, Goregaon East",
        "latitude": 19.1738,
        "longitude": 72.8601,
        "postal_code": "400063",
        "is_24_hours": False,
        "opening_time": "09:00:00",
        "closing_time": "23:00:00",
        "connectors": [
            {"connector_type": "CCS2", "power_kw": 60.0, "quantity": 2, "price_per_kwh": 18.00},
            {"connector_type": "Type 2", "power_kw": 22.0, "quantity": 1, "price_per_kwh": 15.00}
        ]
    },
    {
        "name": "Fortum Charge & Drive — Viviana Mall Thane",
        "operator": "Fortum",
        "locality": "Thane West",
        "address": "Eastern Express Highway, Near Cadbury Junction, Thane",
        "latitude": 19.2089,
        "longitude": 72.9715,
        "postal_code": "400606",
        "is_24_hours": True,
        "connectors": [
            {"connector_type": "CCS2", "power_kw": 60.0, "quantity": 2, "price_per_kwh": 19.00},
            {"connector_type": "CHAdeMO", "power_kw": 50.0, "quantity": 1, "price_per_kwh": 19.00}
        ]
    },
    {
        "name": "Kazam EV Station — Dadar TT Circle",
        "operator": "Kazam",
        "locality": "Dadar East",
        "address": "Dr Baba Saheb Ambedkar Road, Dadar TT Circle",
        "latitude": 19.0178,
        "longitude": 72.8478,
        "postal_code": "400014",
        "is_24_hours": True,
        "connectors": [
            {"connector_type": "Type 2", "power_kw": 22.0, "quantity": 2, "price_per_kwh": 14.00},
            {"connector_type": "Bharat AC001", "power_kw": 15.0, "quantity": 2, "price_per_kwh": 12.00}
        ]
    },
    {
        "name": "Jio-bp pulse Station — Chembur Diamond Garden",
        "operator": "Jio-bp",
        "locality": "Chembur",
        "address": "Sion Trombay Road, Near Diamond Garden, Chembur",
        "latitude": 19.0522,
        "longitude": 72.8994,
        "postal_code": "400071",
        "is_24_hours": True,
        "connectors": [
            {"connector_type": "CCS2", "power_kw": 60.0, "quantity": 2, "price_per_kwh": 19.50},
            {"connector_type": "Type 2", "power_kw": 22.0, "quantity": 2, "price_per_kwh": 15.50}
        ]
    },
    {
        "name": "Statiq EV Station — Inorbit Mall Malad",
        "operator": "Statiq",
        "locality": "Malad West",
        "address": "Link Road, Mindspace, Malad West, Mumbai",
        "latitude": 19.1868,
        "longitude": 72.8344,
        "postal_code": "400064",
        "is_24_hours": False,
        "opening_time": "10:00:00",
        "closing_time": "22:00:00",
        "connectors": [
            {"connector_type": "CCS2", "power_kw": 60.0, "quantity": 2, "price_per_kwh": 18.00},
            {"connector_type": "Type 2", "power_kw": 22.0, "quantity": 2, "price_per_kwh": 14.50}
        ]
    },
    {
        "name": "Tata Power EZ — Nariman Point CR2",
        "operator": "Tata Power",
        "locality": "Nariman Point",
        "address": "CR2 Mall, Barrister Rajni Patel Marg, Nariman Point",
        "latitude": 18.9272,
        "longitude": 72.8228,
        "postal_code": "400021",
        "is_24_hours": True,
        "connectors": [
            {"connector_type": "CCS2", "power_kw": 50.0, "quantity": 2, "price_per_kwh": 20.00},
            {"connector_type": "Type 2", "power_kw": 22.0, "quantity": 2, "price_per_kwh": 16.00}
        ]
    }
]

def generate_canonical_dataset():
    stations_out = []
    operators_set = set()
    
    for s in MUMBAI_STATIONS_DATA:
        s_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"station.chargeplus.mumbai.{s['name']}"))
        operators_set.add(s["operator"])
        
        station_record = {
            "id": s_id,
            "name": s["name"],
            "operator": s["operator"],
            "address_line": s["address"],
            "locality": s["locality"],
            "city": "Mumbai",
            "state": "Maharashtra",
            "postal_code": s["postal_code"],
            "country": "India",
            "latitude": s["latitude"],
            "longitude": s["longitude"],
            "is_24_hours": s["is_24_hours"],
            "opening_time": s.get("opening_time", "00:00:00" if s["is_24_hours"] else "06:00:00"),
            "closing_time": s.get("closing_time", "23:59:59" if s["is_24_hours"] else "23:00:00"),
            "operational_status": "operational",
            "connectors": []
        }
        
        for idx, c in enumerate(s["connectors"]):
            c_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{s_id}.connector.{idx}"))
            station_record["connectors"].append({
                "id": c_id,
                "station_id": s_id,
                "connector_type": c["connector_type"],
                "charging_standard": "IEC 62196-3" if c["connector_type"] == "CCS2" else "IEC 62196-2",
                "power_kw": c["power_kw"],
                "quantity": c["quantity"],
                "pricing_type": "per_kwh",
                "price_per_kwh": c["price_per_kwh"],
                "currency": "INR"
            })
        
        stations_out.append(station_record)
        
    os.makedirs("data", exist_ok=True)
    with open("data/canonical_stations.json", "w") as f:
        json.dump(stations_out, f, indent=2)
        
    print(f"Generated {len(stations_out)} canonical Mumbai stations across {len(operators_set)} operators in data/canonical_stations.json")
    return stations_out

if __name__ == "__main__":
    generate_canonical_dataset()
