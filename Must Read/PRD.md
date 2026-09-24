# PRD.md — ChargePlus Product Requirements
### ChargePlus
**Status: LOCKED — this defines the product we are building.**

## 1. One-liner

ChargePlus is a public, mobile-first EV charging discovery platform that helps drivers find compatible chargers, understand station status and busy patterns, and choose a practical charging stop before reaching a queue.

## 2. Problem

EV drivers can struggle with:
- limited charging coverage
- long queues
- fragmented station information
- uncertain availability
- unclear connector/power compatibility
- stale or inconsistent station details

ChargePlus brings practical charging information into one place while clearly communicating when information is not current or certain.

## 3. Initial geography

Pilot:
**Mumbai, Maharashtra, India**

Architecture:
India-ready.

## 4. Target users

Primary:
All EV drivers.

Secondary/future:
- station operators
- internal/admin users
- analytics users

## 5. Product principles

1. Public discovery should be frictionless.
2. Login should appear only when an account is needed.
3. Information should be useful without pretending it is more current than it is.
4. Real user reports should improve station knowledge.
5. Predictions should only appear when enough evidence exists.
6. Recommendations should be explainable.
7. Mobile is the primary interaction model.
8. Academic analytics/ML work should strengthen the actual product.

## 6. In scope

### Discovery
- map
- station list
- search
- filters
- station details
- connector information
- pricing where available
- operating hours where available
- status/freshness

### Accounts
- phone/email OTP
- profile
- favorites
- reports
- reviews
- alerts

### Community
- Available / Busy / Broken reports
- queue category
- optional comments
- star ratings
- review comments

### Intelligence
- recommendation in search
- busy-time patterns
- congestion prediction when enough data exists
- availability-related alerts when supported
- reliability indicators when supported

### Data platform
- automated ingestion
- normalization
- validation
- deduplication
- provenance
- warehouse
- OLAP
- data quality
- ML experimentation/evaluation

### Admin
- station/data coverage
- ingestion status
- data quality
- reports/reviews moderation
- analytics/forecast health
- system health

## 7. Out of scope for initial product

- payment processing
- charging-session booking
- OCPP integration
- owning charger hardware
- native iOS/Android apps
- custom turn-by-turn navigation engine
- station photos
- amenities as a filter category
- guaranteed real-time availability without a trustworthy live source
- nationwide coverage before the Mumbai pilot is reliable
- speculative AI features without supporting data

## 8. Authentication requirements

- phone number OR email
- OTP
- no password
- public exploration without account
- protected actions require authentication

Important deployment constraint:
Phone/SMS OTP may introduce provider/platform costs in production. Do not silently replace the agreed auth model just to preserve a zero-cost target.

## 9. Station model

A station is a physical place.

Connectors are child entities.

Example:

```text
Station A
 ├── CCS2 120 kW × 2
 └── Type 2 22 kW × 1
```

## 10. Recommendation

Recommendation flow:

```text
User needs
   ↓
Compatible stations
   ↓
Remove clearly unsuitable options
   ↓
Consider distance / power / price / status /
busy pattern / reliability / freshness
   ↓
Explain recommendation
```

The system must not invent a reason when data for that reason is missing.

## 11. Alerts

Initial:
- station likely available
- station likely/concretely busy according to available evidence

Alerts must be tied to meaningful user conditions, not spam.

## 12. Data warehouse requirements

Must demonstrate:
- dimensional modeling
- fact tables
- dimensions
- ETL/ELT
- historical storage
- data quality
- OLAP queries
- useful analytical questions

Example analytical questions:
- Which stations are busiest by hour?
- Which operators have the most station coverage?
- Which connector types are most common?
- How does demand differ by weekday/weekend?
- Which stations show repeated high queue reports?
- How has station reliability changed over time?

## 13. Data mining / ML requirements

Primary intelligence problem:
future station demand/busy-state estimation.

Required process:
- baseline
- feature engineering
- model
- evaluation
- comparison
- documented limitations

Do not claim success if the data does not support it.

## 14. Success criteria

### Product
- public Mumbai station discovery works
- map/list/search/filter work
- station details work
- navigation handoff works
- auth works
- reports/reviews/favorites work
- alerts work when configured

### Data
- automated ingestion works
- invalid records are rejected/quarantined
- duplicate stations are controlled
- provenance is retained
- data freshness is represented

### Academic
- warehouse is queryable
- OLAP queries answer real product questions
- ML pipeline is reproducible
- evaluation is measurable

### Production
- deployable publicly
- no secrets exposed
- RLS enforced
- errors handled
- no fake production data
- basic observability exists

## 15. Product definition of done

ChargePlus is not "done" because the UI looks complete.

It is done when:
**real data → validated station knowledge → useful product experience → user feedback → historical analytics → justified intelligence**

works as one coherent system.
