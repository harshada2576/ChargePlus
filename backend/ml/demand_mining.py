"""
backend/ml/demand_mining.py
ChargePlus — Phase 5 Data Mining & Machine Learning Suite
Includes:
1. Unsupervised Mining: K-Means Clustering for EV Demand Hotspots
2. Supervised Mining: Random Forest Regressor for Station Congestion/Queue Prediction
3. Model Evaluation against Naive Baseline (MAE, RMSE, R2 Score)
"""

import json
import os
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, root_mean_squared_error, r2_score

def run_data_mining():
    print("=" * 60)
    print(" CHARGEPLUS — DATA MINING & ML EXPERIMENTAL RUN")
    print("=" * 60)

    with open("data/canonical_stations.json") as f:
        stations = json.load(f)
    with open("data/observations.json") as f:
        observations = json.load(f)

    df_stations = pd.DataFrame(stations)
    df_obs = pd.DataFrame(observations)

    # -------------------------------------------------------------
    # 1. Unsupervised Mining: K-Means Spatial Demand Clustering
    # -------------------------------------------------------------
    print("\n[TASK 1] Unsupervised Mining: K-Means Demand Clustering")
    
    # Calculate demand score per station
    demand_by_station = df_obs.groupby("station_id")["available_connectors"].apply(
        lambda s: (1 - s.mean() / 4.0) * 100
    ).to_dict()
    
    cluster_features = []
    for s in stations:
        cluster_features.append({
            "station_id": s["id"],
            "name": s["name"],
            "lat": s["latitude"],
            "lng": s["longitude"],
            "total_plugs": sum(c["quantity"] for c in s["connectors"]),
            "demand_score": demand_by_station.get(s["id"], 50.0)
        })
    df_cluster = pd.DataFrame(cluster_features)
    
    # Fit 3 Clusters: (1) High-Density Metro Corridors, (2) Suburban Commercial Hubs, (3) Peripheral/Thane-Vashi
    kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
    df_cluster["cluster_id"] = kmeans.fit_predict(df_cluster[["lat", "lng", "demand_score"]])
    
    cluster_summary = df_cluster.groupby("cluster_id").agg(
        station_count=("name", "count"),
        avg_demand_score=("demand_score", "mean"),
        avg_lat=("lat", "mean"),
        avg_lng=("lng", "mean")
    ).reset_index()
    print("Cluster Analysis Results:")
    for _, row in cluster_summary.iterrows():
        print(f"  • Cluster {int(row['cluster_id'])}: {int(row['station_count'])} Stations | Avg Demand Index: {row['avg_demand_score']:.1f}%")

    # -------------------------------------------------------------
    # 2. Supervised Mining: Machine Learning Congestion Forecasting
    # -------------------------------------------------------------
    print("\n[TASK 2] Supervised Mining: Random Forest Congestion Prediction")
    
    # Target: Occupancy Ratio (0.0 = completely free, 1.0 = completely full)
    df_obs["occupancy_ratio"] = (df_obs["total_connectors"] - df_obs["available_connectors"]) / df_obs["total_connectors"]
    
    # Feature Engineering
    # Map high demand hubs
    hub_ids = {s["id"] for s in stations if any(k in s["name"] for k in ["Bandra", "Airport", "Lower Parel"])}
    df_obs["is_commercial_hub"] = df_obs["station_id"].isin(hub_ids).astype(int)
    
    X = df_obs[["hour", "day_of_week", "is_weekend", "total_connectors", "is_commercial_hub"]]
    y = df_obs["occupancy_ratio"]
    
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    # Baseline Model: Naive Historical Mean by Hour
    baseline_lookup = df_obs.groupby("hour")["occupancy_ratio"].mean().to_dict()
    y_pred_baseline = X_test["hour"].map(baseline_lookup)
    
    # Random Forest Regressor
    model = RandomForestRegressor(n_estimators=100, max_depth=8, random_state=42)
    model.fit(X_train, y_train)
    y_pred_rf = model.predict(X_test)
    
    # Evaluation Metrics
    mae_base = mean_absolute_error(y_test, y_pred_baseline)
    rmse_base = root_mean_squared_error(y_test, y_pred_baseline)
    
    mae_rf = mean_absolute_error(y_test, y_pred_rf)
    rmse_rf = root_mean_squared_error(y_test, y_pred_rf)
    r2_rf = r2_score(y_test, y_pred_rf)
    
    print("\n--- MODEL EVALUATION & COMPARISON ---")
    print(f"  • Baseline (Hourly Mean) : MAE = {mae_base:.4f} | RMSE = {rmse_base:.4f}")
    print(f"  • Random Forest Model    : MAE = {mae_rf:.4f} | RMSE = {rmse_rf:.4f} | R² = {r2_rf:.4f}")
    print(f"  • Model Improvement      : {((mae_base - mae_rf) / mae_base * 100):.1f}% reduction in error")
    
    # Feature Importances
    importances = dict(zip(X.columns, model.feature_importances_))
    print("\nFeature Importances:")
    for feat, imp in sorted(importances.items(), key=lambda x: x[1], reverse=True):
        print(f"  • {feat:<20}: {imp*100:.1f}%")
        
    os.makedirs("data/ml", exist_ok=True)
    with open("data/ml/mining_summary.json", "w") as f:
        json.dump({
            "clusters": cluster_summary.to_dict(orient="records"),
            "metrics": {
                "baseline_mae": round(mae_base, 4),
                "rf_mae": round(mae_rf, 4),
                "rf_rmse": round(rmse_rf, 4),
                "r2_score": round(r2_rf, 4),
                "improvement_pct": round(((mae_base - mae_rf) / mae_base * 100), 2)
            },
            "feature_importance": {k: round(v, 4) for k, v in importances.items()}
        }, f, indent=2)
    print("\n[SUCCESS] Mining results saved to data/ml/mining_summary.json")

if __name__ == "__main__":
    run_data_mining()
