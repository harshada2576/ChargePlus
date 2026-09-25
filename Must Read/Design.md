# Design.md — ChargePlus Frontend Design Contract
### ChargePlus — EV Charging Discovery & Intelligence
**Status: LOCKED — the frontend is considered complete and should not be visually redesigned during backend/data work.**

## 1. Product identity

Name: ChargePlus

Tagline:
**"Find the right charger, before you reach the queue."**

Design direction:
- clean EV-tech feel
- friendly to ordinary EV drivers
- no unnecessary technical language
- mobile-first
- practical, calm, trustworthy

## 2. Official palette

Use only this warm palette for the ChargePlus brand system:

| Token | Hex |
|---|---|
| Light Coral | `#F08080` |
| Sweet Salmon | `#F4978E` |
| Powder Blush | `#F8AD9D` |
| Peach Fuzz | `#FBC4AB` |
| Soft Apricot | `#FFDAB9` |

Do not introduce blue, cyan, neon or unrelated accent colors as brand colors.

Semantic status colors may be used only when required for clear usability/accessibility, and should remain visually consistent with the warm brand system.

## 3. Language

Supported:
- English
- Hindi
- Marathi

User-facing copy must use ordinary language.

Avoid:
- API
- database
- machine learning
- ETL
- confidence score
- warehouse
- model
- algorithm

Prefer:
- "Usually busy around 7 PM"
- "Updated 8 min ago"
- "We don't have enough information yet to estimate busy times."

## 4. Navigation

Mobile:
Home / Explore / Saved / Alerts / Profile

Desktop:
map/list exploration layout with supporting navigation.

## 5. Home

Landing page order:
1. Explain what ChargePlus does.
2. Explain the main benefits.
3. Introduce key functionality.
4. Provide clear entry into Explore.
5. Avoid requiring login just to understand/use the product.

## 6. Location

Do not request location immediately.

Ask only after:
**"Use my location"**

If no usable location is available:
- use Mumbai as the default discovery area
- make the fallback clear without blocking exploration

## 7. Explore/map

Desktop:
- map on left
- station list on right

Mobile:
- map-first experience
- bottom-sheet/list interaction

Map controls:
- zoom
- locate
- map/list interaction
- appropriate search/filter controls

Markers:
- availability-aware
- overlapping stations should automatically become understandable through zooming/cluster behavior rather than unreadable marker piles

## 8. Station card

Keep the primary map/list card simple.

Show where available:
- station name
- operator
- distance
- connector
- maximum power
- number of chargers
- price
- current/last known status
- last updated time

Do not put congestion, reliability, data provenance, or technical scoring on the basic map card.

## 9. Station detail

May contain:
- complete connector information
- hours
- pricing information where known
- status
- last updated time
- busy-time intelligence where supported
- recommendation context
- reports
- reviews
- favorite action
- navigation

Do not expose technical source metadata as a normal station-detail feature.

## 10. Search and filters

Search supports:
- station name
- operator
- location
- connector type
- relevant station text

Current filter scope:
- distance
- connector type
- charging speed/power
- operator
- current availability
- likely availability
- price
- open now
- number of connectors
- fast charging
- free charging
- reliability
- predicted queue/congestion when supported by evidence

Amenities are intentionally excluded.

## 11. Recommendations

Recommendations appear in search results.

Recommendation card should explain the practical reasons, e.g.:
- closer
- compatible connector
- more likely to be available
- usually less busy at this time
- lower price where known

Never expose internal scoring terminology.

## 12. Navigation

Use external navigation.

Provide a selector so the user can choose an available navigation app.

ChargePlus does not build its own routing engine.

## 13. Authentication

Public browsing first.

Ask for login only when required for:
- reports
- reviews
- favorites
- alerts
- profile/history

Auth:
- phone number or email
- OTP
- no passwords

## 14. Reports

Quick structured flow:
- Available
- Busy
- Broken
- queue category
- optional comment

Reports require login.

Do not require users to manually enter large amounts of information.

## 15. Reviews

Simple:
- star rating
- comment

Keep reviews conceptually separate from status observations.

## 16. Saved

Heart icon for saving stations.

Saved stations require login.

## 17. Alerts

Initial user alerts:
- availability
- congestion/busy-time

Do not claim a station is available in real time unless the underlying data supports that claim.

## 18. Loading / empty / error

All major screens must have:
- loading state
- empty state
- error state

Errors should be human:
"Something went wrong. Please try again."

Never expose stack traces, API errors, SQL errors or technical implementation details.

## 19. Accessibility

Practical high accessibility:
- readable typography
- strong contrast
- keyboard navigation
- visible focus states
- touch targets around 44–48px
- labels for icon-only controls
- status not communicated by color alone
- reduced-motion respect

## 20. Motion

Use subtle professional transitions only.

Avoid:
- excessive bouncing
- distracting map animations
- unnecessary loaders
- decorative motion that slows the product

## 21. Real-data readiness

The existing UI must be treated as the locked presentation layer.

Backend work should adapt data into the UI's existing shapes wherever possible.

Do not redesign screens simply because real data is being connected.

Unknown values must remain visibly unknown:
- "Price not available"
- "Status not recently updated"
- "We don't have enough information yet"

Never invent placeholder production values.

## 22. Future extensibility

The frontend must remain extensible for planned future capabilities such as:
- trip planning
- station comparison
- charging/history views where real data exists
- personalized preferences
- richer station insights
- notifications
- community trust features
- operator/admin experiences
- installable mobile web experience

These must extend the existing navigation and design system rather than require a core redesign.

Do not build speculative future features before their data and product requirements exist.
