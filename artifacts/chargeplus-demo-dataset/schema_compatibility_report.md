# Schema Compatibility Report

Total fields checked: 228

- EXACT_MATCH: 154
- SAFE_TRANSFORMATION_REQUIRED: 28
- TARGET_COLUMN_MISSING: 0
- TYPE_INCOMPATIBLE: 0
- CONSTRAINT_INCOMPATIBLE: 0
- EXCLUDED_USER_DATA: 46
- NOT_VERIFIABLE: 0

| CSV | Field | Table | Column | Type | Compatibility | Transformation |
|---|---|---|---|---|---|---|
| data_sources.csv | id | data_sources | id | uuid | EXACT_MATCH | None |
| data_sources.csv | name | data_sources | name | text | EXACT_MATCH | None |
| data_sources.csv | source_type | data_sources | source_type | text | EXACT_MATCH | None |
| data_sources.csv | base_url | data_sources | base_url | text | EXACT_MATCH | None |
| data_sources.csv | source_priority | data_sources | source_priority | integer | EXACT_MATCH | None |
| data_sources.csv | is_active | data_sources | is_active | boolean | EXACT_MATCH | None |
| data_sources.csv | created_at | data_sources | created_at | timestamp with time zone | EXACT_MATCH | None |
| operators.csv | id | operators | id | uuid | EXACT_MATCH | None |
| operators.csv | name | operators | name | text | EXACT_MATCH | None |
| operators.csv | slug | operators | slug | text | EXACT_MATCH | None |
| operators.csv | website_url | operators | website_url | text | EXACT_MATCH | None |
| operators.csv | support_phone | operators | support_phone | text | EXACT_MATCH | None |
| operators.csv | created_at | operators | created_at | timestamp with time zone | EXACT_MATCH | None |
| operators.csv | updated_at | operators | updated_at | timestamp with time zone | EXACT_MATCH | None |
| stations.csv | id | stations | id | uuid | EXACT_MATCH | None |
| stations.csv | slug | stations | slug | text | EXACT_MATCH | None |
| stations.csv | name | stations | name | text | EXACT_MATCH | None |
| stations.csv | operator_id | stations | operator_id | uuid | SAFE_TRANSFORMATION_REQUIRED | must exist in operators |
| stations.csv | address_line | stations | address_line | text | EXACT_MATCH | None |
| stations.csv | locality | stations | locality | text | EXACT_MATCH | None |
| stations.csv | city | stations | city | text | EXACT_MATCH | None |
| stations.csv | state | stations | state | text | EXACT_MATCH | None |
| stations.csv | postal_code | stations | postal_code | text | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL; regex check |
| stations.csv | country | stations | country | text | EXACT_MATCH | None |
| stations.csv | latitude | stations | latitude | double precision | EXACT_MATCH | None |
| stations.csv | longitude | stations | longitude | double precision | EXACT_MATCH | None |
| stations.csv | geom | stations | geom | USER-DEFINED | SAFE_TRANSFORMATION_REQUIRED | WKT POINT(lon lat) into geometry; validate SRID |
| stations.csv | opening_time | stations | opening_time | time without time zone | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL; time format HH:MM:SS |
| stations.csv | closing_time | stations | closing_time | time without time zone | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| stations.csv | is_24_hours | stations | is_24_hours | boolean | EXACT_MATCH | None |
| stations.csv | access_type | stations | access_type | text | EXACT_MATCH | None |
| stations.csv | is_public | stations | is_public | boolean | EXACT_MATCH | None |
| stations.csv | operational_status | stations | operational_status | text | EXACT_MATCH | None |
| stations.csv | phone | stations | phone | text | EXACT_MATCH | None |
| stations.csv | website_url | stations | website_url | text | EXACT_MATCH | None |
| stations.csv | last_verified_at | stations | last_verified_at | timestamp with time zone | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| stations.csv | created_at | stations | created_at | timestamp with time zone | EXACT_MATCH | None |
| stations.csv | updated_at | stations | updated_at | timestamp with time zone | EXACT_MATCH | None |
| connectors.csv | id | connectors | id | uuid | EXACT_MATCH | None |
| connectors.csv | station_id | connectors | station_id | uuid | EXACT_MATCH | None |
| connectors.csv | connector_type | connectors | connector_type | text | EXACT_MATCH | None |
| connectors.csv | charging_standard | connectors | charging_standard | text | EXACT_MATCH | None |
| connectors.csv | power_kw | connectors | power_kw | numeric | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| connectors.csv | quantity | connectors | quantity | integer | EXACT_MATCH | None |
| connectors.csv | pricing_type | connectors | pricing_type | text | EXACT_MATCH | None |
| connectors.csv | price_per_kwh | connectors | price_per_kwh | numeric | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL; numeric |
| connectors.csv | price_per_session | connectors | price_per_session | numeric | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| connectors.csv | currency | connectors | currency | text | EXACT_MATCH | None |
| connectors.csv | created_at | connectors | created_at | timestamp with time zone | EXACT_MATCH | None |
| connectors.csv | updated_at | connectors | updated_at | timestamp with time zone | EXACT_MATCH | None |
| connectors.csv | price_estimate_per_kwh | connectors | price_estimate_per_kwh | numeric | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL; 0-500 |
| connectors.csv | price_estimate_raw | connectors | price_estimate_raw | text | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL; <=500 chars |
| connectors.csv | price_estimate_source | connectors | price_estimate_source | text | SAFE_TRANSFORMATION_REQUIRED | empty or ocm_usage_cost |
| station_observations.csv | id | station_observations | id | uuid | EXACT_MATCH | None |
| station_observations.csv | station_id | station_observations | station_id | uuid | EXACT_MATCH | None |
| station_observations.csv | connector_id | station_observations | connector_id | uuid | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL; must belong to same station |
| station_observations.csv | source_id | station_observations | source_id | uuid | EXACT_MATCH | None |
| station_observations.csv | availability_status | station_observations | availability_status | text | EXACT_MATCH | None |
| station_observations.csv | queue_level | station_observations | queue_level | text | EXACT_MATCH | None |
| station_observations.csv | available_connectors | station_observations | available_connectors | integer | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| station_observations.csv | total_connectors | station_observations | total_connectors | integer | EXACT_MATCH | None |
| station_observations.csv | observed_at | station_observations | observed_at | timestamp with time zone | EXACT_MATCH | None |
| station_observations.csv | received_at | station_observations | received_at | timestamp with time zone | EXACT_MATCH | None |
| station_observations.csv | confidence_score | station_observations | confidence_score | numeric | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| station_observations.csv | source_payload_hash | station_observations | source_payload_hash | text | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| station_observations.csv | created_at | station_observations | created_at | timestamp with time zone | EXACT_MATCH | None |
| station_source_link.csv | id | station_source_link | id | uuid | EXACT_MATCH | None |
| station_source_link.csv | station_id | station_source_link | station_id | uuid | EXACT_MATCH | None |
| station_source_link.csv | source_id | station_source_link | source_id | uuid | EXACT_MATCH | None |
| station_source_link.csv | source_station_id | station_source_link | source_station_id | text | EXACT_MATCH | None |
| station_source_link.csv | source_url | station_source_link | source_url | text | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| station_source_link.csv | first_seen_at | station_source_link | first_seen_at | timestamp with time zone | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| station_source_link.csv | last_seen_at | station_source_link | last_seen_at | timestamp with time zone | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| station_source_link.csv | last_ingested_at | station_source_link | last_ingested_at | timestamp with time zone | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| station_source_link.csv | source_payload_hash | station_source_link | source_payload_hash | text | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| station_source_link.csv | is_active | station_source_link | is_active | boolean | EXACT_MATCH | None |
| station_source_link.csv | created_at | station_source_link | created_at | timestamp with time zone | EXACT_MATCH | None |
| station_source_link.csv | updated_at | station_source_link | updated_at | timestamp with time zone | EXACT_MATCH | None |
| ingestion_runs.csv | id | ingestion_runs | id | uuid | EXACT_MATCH | None |
| ingestion_runs.csv | source_id | ingestion_runs | source_id | uuid | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL; must exist in data_sources |
| ingestion_runs.csv | source_name | ingestion_runs | source_name | text | EXACT_MATCH | None |
| ingestion_runs.csv | scope | ingestion_runs | scope | text | EXACT_MATCH | None |
| ingestion_runs.csv | state | ingestion_runs | state | text | EXACT_MATCH | None |
| ingestion_runs.csv | started_at | ingestion_runs | started_at | timestamp with time zone | EXACT_MATCH | None |
| ingestion_runs.csv | completed_at | ingestion_runs | completed_at | timestamp with time zone | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| ingestion_runs.csv | duration_seconds | ingestion_runs | duration_seconds | numeric | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| ingestion_runs.csv | attempt_count | ingestion_runs | attempt_count | integer | EXACT_MATCH | None |
| ingestion_runs.csv | records_fetched | ingestion_runs | records_fetched | integer | EXACT_MATCH | None |
| ingestion_runs.csv | records_parsed | ingestion_runs | records_parsed | integer | EXACT_MATCH | None |
| ingestion_runs.csv | records_accepted | ingestion_runs | records_accepted | integer | EXACT_MATCH | None |
| ingestion_runs.csv | records_accepted_with_warnings | ingestion_runs | records_accepted_with_warnings | integer | EXACT_MATCH | None |
| ingestion_runs.csv | records_quarantined | ingestion_runs | records_quarantined | integer | EXACT_MATCH | None |
| ingestion_runs.csv | records_rejected | ingestion_runs | records_rejected | integer | EXACT_MATCH | None |
| ingestion_runs.csv | stations_persisted | ingestion_runs | stations_persisted | integer | EXACT_MATCH | None |
| ingestion_runs.csv | stations_updated | ingestion_runs | stations_updated | integer | EXACT_MATCH | None |
| ingestion_runs.csv | stations_unchanged | ingestion_runs | stations_unchanged | integer | EXACT_MATCH | None |
| ingestion_runs.csv | connectors_persisted | ingestion_runs | connectors_persisted | integer | EXACT_MATCH | None |
| ingestion_runs.csv | observations_persisted | ingestion_runs | observations_persisted | integer | EXACT_MATCH | None |
| ingestion_runs.csv | error_summary | ingestion_runs | error_summary | text | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| ingestion_runs.csv | metadata | ingestion_runs | metadata | jsonb | SAFE_TRANSFORMATION_REQUIRED | JSON string into jsonb |
| ingestion_runs.csv | created_at | ingestion_runs | created_at | timestamp with time zone | EXACT_MATCH | None |
| dim_date.csv | date_key | dim_date | date_key | integer | EXACT_MATCH | None |
| dim_date.csv | full_date | dim_date | full_date | date | EXACT_MATCH | None |
| dim_date.csv | day_of_week | dim_date | day_of_week | integer | EXACT_MATCH | None |
| dim_date.csv | day_name | dim_date | day_name | character varying | EXACT_MATCH | None |
| dim_date.csv | month | dim_date | month | integer | EXACT_MATCH | None |
| dim_date.csv | month_name | dim_date | month_name | character varying | EXACT_MATCH | None |
| dim_date.csv | quarter | dim_date | quarter | integer | EXACT_MATCH | None |
| dim_date.csv | year | dim_date | year | integer | EXACT_MATCH | None |
| dim_date.csv | is_weekend | dim_date | is_weekend | boolean | EXACT_MATCH | None |
| dim_date.csv | is_holiday | dim_date | is_holiday | boolean | EXACT_MATCH | None |
| dim_date.csv | season | dim_date | season | character varying | EXACT_MATCH | None |
| dim_location.csv | location_key | dim_location | location_key | integer | EXACT_MATCH | None |
| dim_location.csv | location_id | dim_location | location_id | character varying | EXACT_MATCH | None |
| dim_location.csv | city | dim_location | city | character varying | EXACT_MATCH | None |
| dim_location.csv | zone_name | dim_location | zone_name | character varying | EXACT_MATCH | None |
| dim_location.csv | area_type | dim_location | area_type | character varying | EXACT_MATCH | None |
| dim_location.csv | latitude | dim_location | latitude | numeric | EXACT_MATCH | None |
| dim_location.csv | longitude | dim_location | longitude | numeric | EXACT_MATCH | None |
| dim_location.csv | grid_substation_id | dim_location | grid_substation_id | character varying | EXACT_MATCH | None |
| dim_station.csv | station_key | dim_station | station_key | integer | EXACT_MATCH | None |
| dim_station.csv | station_id | dim_station | station_id | character varying | EXACT_MATCH | None |
| dim_station.csv | station_name | dim_station | station_name | character varying | EXACT_MATCH | None |
| dim_station.csv | operator | dim_station | operator | character varying | EXACT_MATCH | None |
| dim_station.csv | charger_type | dim_station | charger_type | character varying | EXACT_MATCH | None |
| dim_station.csv | num_ports | dim_station | num_ports | integer | EXACT_MATCH | None |
| dim_station.csv | max_power_kw | dim_station | max_power_kw | numeric | EXACT_MATCH | None |
| dim_station.csv | installation_date | dim_station | installation_date | date | EXACT_MATCH | None |
| dim_station.csv | effective_start_date | dim_station | effective_start_date | date | EXACT_MATCH | None |
| dim_station.csv | effective_end_date | dim_station | effective_end_date | date | SAFE_TRANSFORMATION_REQUIRED | empty -> NULL |
| dim_station.csv | is_current | dim_station | is_current | boolean | EXACT_MATCH | None |
| dim_tariff.csv | tariff_key | dim_tariff | tariff_key | integer | EXACT_MATCH | None |
| dim_tariff.csv | tariff_id | dim_tariff | tariff_id | character varying | EXACT_MATCH | None |
| dim_tariff.csv | tariff_name | dim_tariff | tariff_name | character varying | EXACT_MATCH | None |
| dim_tariff.csv | tier_type | dim_tariff | tier_type | character varying | EXACT_MATCH | None |
| dim_tariff.csv | rate_per_kwh | dim_tariff | rate_per_kwh | numeric | EXACT_MATCH | None |
| dim_time.csv | time_key | dim_time | time_key | integer | EXACT_MATCH | None |
| dim_time.csv | hour | dim_time | hour | integer | EXACT_MATCH | None |
| dim_time.csv | minute | dim_time | minute | integer | EXACT_MATCH | None |
| dim_time.csv | time_slot | dim_time | time_slot | character varying | EXACT_MATCH | None |
| dim_time.csv | is_peak_hours | dim_time | is_peak_hours | boolean | EXACT_MATCH | None |
| dim_vehicle.csv | vehicle_key | dim_vehicle | vehicle_key | integer | EXACT_MATCH | None |
| dim_vehicle.csv | vehicle_id | dim_vehicle | vehicle_id | character varying | EXACT_MATCH | None |
| dim_vehicle.csv | make | dim_vehicle | make | character varying | EXACT_MATCH | None |
| dim_vehicle.csv | model | dim_vehicle | model | character varying | EXACT_MATCH | None |
| dim_vehicle.csv | vehicle_type | dim_vehicle | vehicle_type | character varying | EXACT_MATCH | None |
| dim_vehicle.csv | battery_capacity_kwh | dim_vehicle | battery_capacity_kwh | numeric | EXACT_MATCH | None |
| dim_vehicle.csv | max_charge_rate_kw | dim_vehicle | max_charge_rate_kw | numeric | EXACT_MATCH | None |
| dim_weather.csv | weather_key | dim_weather | weather_key | integer | EXACT_MATCH | None |
| dim_weather.csv | weather_id | dim_weather | weather_id | character varying | EXACT_MATCH | None |
| dim_weather.csv | temperature_celsius | dim_weather | temperature_celsius | numeric | EXACT_MATCH | None |
| dim_weather.csv | humidity_pct | dim_weather | humidity_pct | integer | EXACT_MATCH | None |
| dim_weather.csv | rainfall_mm | dim_weather | rainfall_mm | numeric | EXACT_MATCH | None |
| dim_weather.csv | weather_condition | dim_weather | weather_condition | character varying | EXACT_MATCH | None |
| fact_charging_session.csv | session_key | fact_charging_session | session_key | bigint | EXACT_MATCH | None |
| fact_charging_session.csv | session_id | fact_charging_session | session_id | character varying | EXACT_MATCH | None |
| fact_charging_session.csv | station_key | fact_charging_session | station_key | integer | EXACT_MATCH | None |
| fact_charging_session.csv | location_key | fact_charging_session | location_key | integer | EXACT_MATCH | None |
| fact_charging_session.csv | vehicle_key | fact_charging_session | vehicle_key | integer | EXACT_MATCH | None |
| fact_charging_session.csv | date_key | fact_charging_session | date_key | integer | EXACT_MATCH | None |
| fact_charging_session.csv | time_key | fact_charging_session | time_key | integer | EXACT_MATCH | None |
| fact_charging_session.csv | weather_key | fact_charging_session | weather_key | integer | EXACT_MATCH | None |
| fact_charging_session.csv | tariff_key | fact_charging_session | tariff_key | integer | EXACT_MATCH | None |
| fact_charging_session.csv | start_timestamp | fact_charging_session | start_timestamp | timestamp without time zone | EXACT_MATCH | None |
| fact_charging_session.csv | end_timestamp | fact_charging_session | end_timestamp | timestamp without time zone | EXACT_MATCH | None |
| fact_charging_session.csv | duration_minutes | fact_charging_session | duration_minutes | numeric | EXACT_MATCH | None |
| fact_charging_session.csv | energy_consumed_kwh | fact_charging_session | energy_consumed_kwh | numeric | EXACT_MATCH | None |
| fact_charging_session.csv | peak_power_kw | fact_charging_session | peak_power_kw | numeric | EXACT_MATCH | None |
| fact_charging_session.csv | session_cost | fact_charging_session | session_cost | numeric | EXACT_MATCH | None |
| fact_charging_session.csv | queue_time_minutes | fact_charging_session | queue_time_minutes | integer | EXACT_MATCH | None |
| fact_charging_session.csv | idle_time_minutes | fact_charging_session | idle_time_minutes | integer | EXACT_MATCH | None |
| fact_charging_session.csv | created_at | fact_charging_session | created_at | timestamp with time zone | SAFE_TRANSFORMATION_REQUIRED | timestamptz |
| fact_station_daily_agg.csv | agg_id | fact_station_daily_agg | agg_id | bigint | EXACT_MATCH | None |
| fact_station_daily_agg.csv | station_key | fact_station_daily_agg | station_key | integer | EXACT_MATCH | None |
| fact_station_daily_agg.csv | date_key | fact_station_daily_agg | date_key | integer | EXACT_MATCH | None |
| fact_station_daily_agg.csv | location_key | fact_station_daily_agg | location_key | integer | EXACT_MATCH | None |
| fact_station_daily_agg.csv | total_sessions | fact_station_daily_agg | total_sessions | integer | EXACT_MATCH | None |
| fact_station_daily_agg.csv | total_energy_kwh | fact_station_daily_agg | total_energy_kwh | numeric | EXACT_MATCH | None |
| fact_station_daily_agg.csv | total_revenue | fact_station_daily_agg | total_revenue | numeric | EXACT_MATCH | None |
| fact_station_daily_agg.csv | avg_duration_minutes | fact_station_daily_agg | avg_duration_minutes | numeric | EXACT_MATCH | None |
| fact_station_daily_agg.csv | avg_queue_time_minutes | fact_station_daily_agg | avg_queue_time_minutes | numeric | EXACT_MATCH | None |
| fact_station_daily_agg.csv | utilization_rate_pct | fact_station_daily_agg | utilization_rate_pct | numeric | EXACT_MATCH | None |
| profiles.csv | id | None | None | None | EXCLUDED_USER_DATA | Excluded |
| profiles.csv | display_name | None | None | None | EXCLUDED_USER_DATA | Excluded |
| profiles.csv | role | None | None | None | EXCLUDED_USER_DATA | Excluded |
| profiles.csv | preferred_language | None | None | None | EXCLUDED_USER_DATA | Excluded |
| profiles.csv | home_city | None | None | None | EXCLUDED_USER_DATA | Excluded |
| profiles.csv | created_at | None | None | None | EXCLUDED_USER_DATA | Excluded |
| profiles.csv | updated_at | None | None | None | EXCLUDED_USER_DATA | Excluded |
| favorites.csv | user_id | None | None | None | EXCLUDED_USER_DATA | Excluded |
| favorites.csv | station_id | None | None | None | EXCLUDED_USER_DATA | Excluded |
| favorites.csv | created_at | None | None | None | EXCLUDED_USER_DATA | Excluded |
| reviews.csv | id | None | None | None | EXCLUDED_USER_DATA | Excluded |
| reviews.csv | user_id | None | None | None | EXCLUDED_USER_DATA | Excluded |
| reviews.csv | station_id | None | None | None | EXCLUDED_USER_DATA | Excluded |
| reviews.csv | rating | None | None | None | EXCLUDED_USER_DATA | Excluded |
| reviews.csv | comment | None | None | None | EXCLUDED_USER_DATA | Excluded |
| reviews.csv | is_flagged | None | None | None | EXCLUDED_USER_DATA | Excluded |
| reviews.csv | moderation_status | None | None | None | EXCLUDED_USER_DATA | Excluded |
| reviews.csv | moderated_by | None | None | None | EXCLUDED_USER_DATA | Excluded |
| reviews.csv | moderated_at | None | None | None | EXCLUDED_USER_DATA | Excluded |
| reviews.csv | moderation_reason | None | None | None | EXCLUDED_USER_DATA | Excluded |
| reviews.csv | created_at | None | None | None | EXCLUDED_USER_DATA | Excluded |
| reviews.csv | updated_at | None | None | None | EXCLUDED_USER_DATA | Excluded |
| user_reports.csv | id | None | None | None | EXCLUDED_USER_DATA | Excluded |
| user_reports.csv | user_id | None | None | None | EXCLUDED_USER_DATA | Excluded |
| user_reports.csv | station_id | None | None | None | EXCLUDED_USER_DATA | Excluded |
| user_reports.csv | connector_id | None | None | None | EXCLUDED_USER_DATA | Excluded |
| user_reports.csv | availability_status | None | None | None | EXCLUDED_USER_DATA | Excluded |
| user_reports.csv | queue_level | None | None | None | EXCLUDED_USER_DATA | Excluded |
| user_reports.csv | comment | None | None | None | EXCLUDED_USER_DATA | Excluded |
| user_reports.csv | observed_at | None | None | None | EXCLUDED_USER_DATA | Excluded |
| user_reports.csv | created_at | None | None | None | EXCLUDED_USER_DATA | Excluded |
| user_reports.csv | is_flagged | None | None | None | EXCLUDED_USER_DATA | Excluded |
| user_reports.csv | moderation_status | None | None | None | EXCLUDED_USER_DATA | Excluded |
| user_reports.csv | moderated_by | None | None | None | EXCLUDED_USER_DATA | Excluded |
| user_reports.csv | moderated_at | None | None | None | EXCLUDED_USER_DATA | Excluded |
| user_reports.csv | moderation_reason | None | None | None | EXCLUDED_USER_DATA | Excluded |
| alerts.csv | id | None | None | None | EXCLUDED_USER_DATA | Excluded |
| alerts.csv | user_id | None | None | None | EXCLUDED_USER_DATA | Excluded |
| alerts.csv | station_id | None | None | None | EXCLUDED_USER_DATA | Excluded |
| alerts.csv | alert_type | None | None | None | EXCLUDED_USER_DATA | Excluded |
| alerts.csv | params | None | None | None | EXCLUDED_USER_DATA | Excluded |
| alerts.csv | threshold_value | None | None | None | EXCLUDED_USER_DATA | Excluded |
| alerts.csv | is_enabled | None | None | None | EXCLUDED_USER_DATA | Excluded |
| alerts.csv | last_triggered_at | None | None | None | EXCLUDED_USER_DATA | Excluded |
| alerts.csv | created_at | None | None | None | EXCLUDED_USER_DATA | Excluded |
| alerts.csv | updated_at | None | None | None | EXCLUDED_USER_DATA | Excluded |
