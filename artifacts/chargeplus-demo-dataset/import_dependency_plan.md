# Import Dependency Plan

## Excluded user-dependent files
- profiles.csv, favorites.csv, reviews.csv, user_reports.csv, alerts.csv (alerts requires user_id NOT NULL)

## Importable files and order
1. data_sources.csv -> data_sources
2. operators.csv -> operators
3. stations.csv -> stations (FK operator_id -> operators.id)
4. connectors.csv -> connectors (FK station_id -> stations.id)
5. station_source_link.csv -> station_source_link (FK station_id, source_id)
6. station_observations.csv -> station_observations (FK station_id, connector_id, source_id)
7. ingestion_runs.csv -> ingestion_runs (FK source_id nullable)
8. dim_* -> analytics dimensions (no FK except none)
9. fact_charging_session.csv -> fact_charging_session (FKs to dims)
10. fact_station_daily_agg.csv -> fact_station_daily_agg (FKs to dims)

## Notes
- No application user required.
- Exclude all records depending on user identity.
- Import order respects foreign keys.
EOF