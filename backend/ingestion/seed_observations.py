"""
backend/ingestion/seed_observations.py
Generates 30 days of hourly realistic operational observations across Mumbai stations.
Follows diurnal demand curve (morning peak 8-10 AM, evening peak 6-9 PM).
"""

import json
import uuid
import random
from datetime import datetime, timedelta, timezone

def generate_observations():
    with open("data/canonical_stations.json") as f:
        stations = json.load(f)
        
    start_date = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    days = 30
    observations = []
    
    random.seed(42)
    
    for day in range(days):
        current_day = start_date + timedelta(days=day)
        is_weekend = current_day.weekday() >= 5
        
        for hour in range(24):
            obs_time = current_day + timedelta(hours=hour)
            
            # Base probability of high demand
            if 8 <= hour <= 10 or 18 <= hour <= 21:
                demand_bias = 0.75 if not is_weekend else 0.60
            elif 12 <= hour <= 16:
                demand_bias = 0.45
            else:
                demand_bias = 0.15
                
            for s in stations:
                for c in s["connectors"]:
                    total_plugs = c["quantity"]
                    
                    # High power chargers get higher utilization in business districts
                    is_hub = "Bandra" in s["name"] or "Airport" in s["name"] or "Lower Parel" in s["name"]
                    p_busy = min(0.95, demand_bias * (1.3 if is_hub else 1.0))
                    
                    # Occasional equipment fault (2% chance)
                    is_fault = random.random() < 0.02
                    
                    if is_fault:
                        status = "broken"
                        available = 0
                        queue = "none"
                    else:
                        busy_count = sum(1 for _ in range(total_plugs) if random.random() < p_busy)
                        available = total_plugs - busy_count
                        if available == 0:
                            status = "busy"
                            queue = random.choice(["short", "medium", "long"])
                        else:
                            status = "available"
                            queue = "none"
                            
                    obs_id = str(uuid.uuid4())
                    observations.append({
                        "id": obs_id,
                        "station_id": s["id"],
                        "connector_id": c["id"],
                        "observed_at": obs_time.isoformat(),
                        "availability_status": status,
                        "queue_level": queue,
                        "available_connectors": available,
                        "total_connectors": total_plugs,
                        "hour": hour,
                        "day_of_week": current_day.weekday(),
                        "is_weekend": is_weekend
                    })
                    
    with open("data/observations.json", "w") as f:
        json.dump(observations, f)
        
    print(f"Generated {len(observations)} observation records (30 days x 24 hrs across {len(stations)} stations)")
    return observations

if __name__ == "__main__":
    generate_observations()
