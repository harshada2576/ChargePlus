# Demo Import Exclusions

## Excluded files
- profiles.csv: synthetic user profiles (user identity)
- favorites.csv: user-owned saved stations
- reviews.csv: user-generated reviews
- user_reports.csv: user-submitted reports
- alerts.csv: requires non-null user_id (user-owned alerts)

## Reason
No synthetic users or user-owned data may be imported. We will create a real test account later.

## Downstream impact
- Reviews section will remain empty until real users review.
- Favorites/alerts require real user session.
- User reports not imported.
EOF