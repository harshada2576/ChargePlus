# Rules.md — ChargePlus Engineering & AI Guardrails
### ChargePlus
**Status: LOCKED — these rules apply to every coding session.**

## 0. Core rule

The project must be built as a real product, not as a collection of impressive-looking demos.

At every step ask:
1. Is this required by the agreed product?
2. Is the underlying data real or explicitly experimental?
3. Can we explain how it works?
4. Does it preserve the locked architecture?
5. Does it help both the academic requirements and a deployable product?

## 1. Stack rules

- Frontend: Next.js + TypeScript.
- Database/auth: Supabase.
- Spatial search: PostGIS.
- Data ingestion/ETL/analytics/ML: Python.
- FastAPI only where server-side logic actually needs it.
- Mapping: MapLibre + an appropriate production OSM-derived tile provider.
- No Google Maps dependency.
- No passwords.
- No unnecessary microservices.
- No Kafka/Spark/Kubernetes unless a later requirement genuinely justifies them.
- Do not create a backend proxy for every Supabase read/write.

## 2. Frontend rules

The frontend is already designed and should be treated as locked.

Do not:
- redesign the navigation
- replace the visual system
- change the core map/list interaction
- add random UI features
- introduce blue/neon/cyan branding
- expose technical language to drivers

Frontend changes now should primarily be:
- connecting real data
- fixing real-data edge cases
- accessibility/bug fixes
- necessary integration changes

## 3. Data integrity

Never fabricate:
- charging stations
- connector counts
- prices
- availability
- reviews
- user reports
- historical observations
- predictions

Demo fixtures may exist locally for development, but must be clearly separated from production data.

## 4. Provenance

For imported data preserve:
- source
- source record id
- retrieval timestamp
- observation timestamp where available
- validation result
- normalization state
- deduplication decision

A user should not need to see this technical metadata, but the system must retain it.

## 5. Status language

Never confuse:
- operational
- observed
- predicted

Examples:
- "Station is marked operational" is different from "charger is available now."
- "Reported busy 12 min ago" is different from "currently busy."
- "Usually busy around 7 PM" is different from a real-time occupancy reading.

If evidence is insufficient, say so.

## 6. Data maturity

Predictions require evidence.

```text
COLD → WARMING → READY
```

Do not show demand/congestion predictions while the data is still insufficient.

## 7. Database rules

- One physical station has many connectors.
- Use stable IDs.
- Use foreign keys.
- Add indexes based on actual query patterns.
- Use PostGIS for nearby search.
- RLS for user-owned records.
- Do not expose service-role credentials.
- Keep operational and analytics concerns logically separate even if they initially share one Supabase project.

## 8. Python rules

Python owns:
- ingestion
- normalization
- validation
- deduplication
- scheduled data processing
- analytics
- ML
- recommendation logic where server-side computation is required

Prefer small modules.

Keep functions understandable.

Every public function should have a one-line docstring.

Do not create giant files when responsibilities can be separated naturally.

## 9. Validation

External data must pass:
- required-field checks
- coordinate validity
- connector normalization
- price-format validation
- duplicate checks
- timestamp/freshness checks
- station identity checks

Bad records should be quarantined/logged rather than silently becoming canonical data.

## 10. Deduplication

Do not blindly insert every source record as a new station.

Use multiple signals:
- geographic distance
- station name similarity
- address
- operator
- connector characteristics

Keep source records even when they map to an existing canonical station.

## 11. ML rules

Do not start with an advanced model.

First:
1. establish a simple baseline
2. measure data volume/quality
3. build features
4. train a simple justified model
5. compare it with the baseline
6. evaluate honestly

Never report arbitrary accuracy percentages.

Use appropriate metrics such as MAE/RMSE and only use MAPE where meaningful.

If the model does not outperform a baseline, document that result rather than hiding it.

## 12. Recommendation rules

Recommendation must be explainable.

First remove stations that are incompatible with the user's needs.

Then consider:
- distance
- connector compatibility
- power
- observed availability
- historical busy pattern
- predicted busy pattern where supported
- price
- reliability
- freshness/confidence

Never call a recommendation "best" based on an unexplained score.

## 13. User-generated content

Reports and reviews are valuable but not automatically truth.

Use:
- timestamps
- abuse controls
- duplicate/spam protection where practical
- separation between reviews and operational status reports

Do not let one report silently overwrite the canonical station record.

## 14. Authentication

Auth is:
- phone or email
- OTP
- no password

Do not store OTPs yourself if Supabase Auth handles the flow.

Public station discovery must work without login.

## 15. Security

- RLS
- secret management
- input validation
- rate limiting on abuse-prone endpoints/actions
- safe error messages
- no sensitive logs
- no service-role key in client code

## 16. Dependencies

If a new major dependency is proposed:
- explain why it is needed
- check whether existing tools can solve the requirement
- prefer the simpler option
- do not add infrastructure for hypothetical future scale

## 17. Testing

Every meaningful layer should have tests.

Minimum categories:
- schema/model tests
- ingestion parsing tests
- validation tests
- deduplication tests
- database/RLS tests where practical
- recommendation tests
- ML evaluation tests
- frontend integration tests for critical flows

## 18. Academic integrity

The product should satisfy:
- data warehouse concepts
- ETL/ELT
- dimensional modeling
- fact/dimension design
- OLAP queries
- data quality
- data mining/ML
- evaluation

But academic features must be implemented using the real product's data and workflows whenever possible.

Do not create a fake unrelated warehouse just to tick a syllabus box.

## 19. Conceptual verification rule

Before declaring a feature complete, verify both:

**Implementation**
- code exists
- code runs
- tests pass

**Concept**
- data meaning is correct
- assumptions are documented
- uncertainty is represented
- feature matches PRD
- feature does not contradict architecture

Passing tests does not automatically mean the product concept is correct.

## 20. AI collaboration rule

If an AI coding tool proposes something that contradicts this folder:
STOP.

Do not silently accept:
- a different stack
- different core entities
- fake data
- password auth
- Google Maps dependency
- technical language in the user UI
- advanced infrastructure without justification
- predictions without sufficient data
- a redesigned frontend merely because backend integration is harder

## 21. Definition of done

A feature is done only when:
- implementation works
- real data path is understood
- errors are handled
- relevant tests exist
- user-facing behavior is honest
- documentation/Memory is updated
- no locked decision was silently changed
