# CHARGEPLUS — MASTER FRONTEND IMPLEMENTATION PROMPT

## 1. ROLE

Build the complete production-quality frontend for **ChargePlus**, a public-facing EV charging discovery and assistance website focused initially on **Mumbai, India**.

This is not a college-demo-looking website.

It must look and behave like a real consumer product that could be publicly launched and used by real EV drivers.

The frontend must be:

* mobile-first
* responsive
* clean
* friendly
* simple for ordinary users
* accessible
* fast
* trustworthy
* visually polished
* easy to understand without technical knowledge
* ready to connect to real backend/database services
* prepared for English, Hindi and Marathi

Do not make the interface look like an engineering dashboard.

Do not expose technical implementation concepts to normal users.

---

# 2. PRODUCT PURPOSE

ChargePlus helps EV drivers:

1. Find nearby charging stations.
2. Search charging stations by area or station name.
3. See available charging information.
4. Compare stations.
5. Understand charging speed, connector type, price and distance.
6. See whether a station is currently reported available, busy or unavailable.
7. Understand when stations are usually busy.
8. Get useful recommendations.
9. Navigate to a selected station using the user's preferred navigation application.
10. Save favorite stations.
11. Report the current condition of a station.
12. Leave reviews.
13. Receive alerts about saved stations.

The central product promise is:

> **Find the right charger, before you reach the queue.**

---

# 3. IMPORTANT LANGUAGE RULE

The website is designed for ordinary EV drivers.

NEVER expose engineering/data-science terminology in normal user-facing screens.

Avoid user-facing terms such as:

* API
* database
* data pipeline
* data source
* model
* machine learning
* prediction model
* confidence score
* probability
* ETL
* warehouse
* algorithm
* congestion score
* forecast model
* telemetry
* connector occupancy probability
* backend
* API error
* HTTP error
* database error

Instead use natural language.

Examples:

Instead of:

> Predicted congestion: 0.78

say:

> **Usually busy around 7 PM**

Instead of:

> Prediction unavailable because insufficient training data

say:

> **We don't have enough information yet to estimate busy times.**

Instead of:

> Data confidence: 0.82

say:

> **Updated recently**

Instead of:

> API request failed

say:

> **Something went wrong. Please try again.**

The sophisticated processing behind ChargePlus may be extensive, but the user experience must remain simple.

---

# 4. LANGUAGES

Support:

* English
* Hindi
* Marathi

English is the default.

Language selector:

```text
English ▾
```

Options:

```text
English
हिन्दी
मराठी
```

The language selection must affect the complete interface, including:

* navigation
* buttons
* headings
* filters
* forms
* station labels
* authentication
* reports
* reviews
* alerts
* errors
* empty states
* help text
* confirmation messages

Do not use awkward literal translations.

Keep station names, operator names and addresses in their natural names where appropriate.

Design the interface so translated text can become longer without breaking layouts.

Never hard-code user-facing text directly throughout components.

Use a central translation structure.

---

# 5. VISUAL IDENTITY

## Overall style

Use a:

**Clean EV-tech + warm, friendly consumer-product style.**

The product should feel modern and polished but not futuristic or aggressive.

Do NOT use:

* blue
* neon
* cyan
* glowing borders
* cyberpunk effects
* excessive gradients
* excessive glassmorphism
* dark futuristic interfaces
* excessive shadows
* overly technical dashboard styling

---

# 6. COLOR SYSTEM

Use the following warm palette as the brand foundation.

```text
Light Coral   #F08080
Sweet Salmon  #F4978E
Powder Blush  #F8AD9D
Peach Fuzz    #FBC4AB
Soft Apricot  #FFDAB9
```

Also use neutral colors for readability:

```text
White
Near-black / dark charcoal
Dark gray
Medium gray
Light gray
Very light neutral background
```

The warm colors should not be used everywhere.

Recommended usage:

### Light Coral #F08080

Primary action:

* main CTA
* selected controls
* important interactive elements
* active navigation when appropriate

### Sweet Salmon #F4978E

Secondary emphasis.

### Powder Blush #F8AD9D

Soft highlighted areas.

### Peach Fuzz #FBC4AB

Cards and gentle emphasis.

### Soft Apricot #FFDAB9

Large soft background sections.

Keep large content areas primarily white/light neutral.

---

# 7. STATUS COLORS

Availability needs to remain understandable.

Use:

```text
Available → green
Busy → orange/warm amber
Broken/unavailable → red
Unknown → neutral gray
```

Do not rely on color alone.

Always combine status with text/iconography.

Example:

```text
● Available
● Busy
● Broken
● Availability unavailable
```

---

# 8. TYPOGRAPHY

Choose a modern, highly readable sans-serif font that works well across:

* English
* Hindi
* Marathi

Prefer a font family with strong Devanagari support.

Typography must prioritize readability over stylistic appearance.

Suggested hierarchy:

```text
Hero heading
Page heading
Section heading
Card heading
Body text
Supporting text
Small metadata
```

Do not use extremely thin fonts.

Do not use excessively large text everywhere.

---

# 9. BRAND LOGO

Use:

```text
ChargePlus
```

as the primary wordmark.

Keep the logo simple.

Do not create an overly complicated icon.

The logo should work in:

* desktop header
* mobile header
* authentication
* footer
* loading screen if needed

---

# 10. GLOBAL DESIGN SYSTEM

Create reusable design tokens for:

* colors
* typography
* spacing
* border radius
* shadows
* transitions
* breakpoints
* icon sizing
* button sizes
* input sizes
* card spacing

Use a consistent spacing scale.

Do not manually invent random margins throughout the application.

---

# 11. RESPONSIVE DESIGN

Design mobile first.

Support at minimum:

```text
Small mobile
Large mobile
Tablet
Laptop
Desktop
Large desktop
```

Do not simply stretch the mobile layout onto desktop.

Desktop should have intentionally designed layouts.

Mobile should be comfortable for one-handed use.

---

# 12. MINIMUM INTERACTION SIZE

Interactive controls must be comfortably tappable.

Target approximately:

```text
44–48px minimum touch area
```

This applies to:

* buttons
* icons
* map controls
* navigation
* checkboxes
* filter choices
* favorite buttons
* close buttons

---

# 13. GLOBAL HEADER

## Desktop

```text
┌────────────────────────────────────────────────────┐
│ ChargePlus                                         │
│                                                    │
│ Explore   Find a Charger   Saved   Alerts          │
│                                      English ▾      │
│                                      Account        │
└────────────────────────────────────────────────────┘
```

Keep the header clean.

## Mobile

```text
┌───────────────────────────────────┐
│ ChargePlus             English ▾  │
└───────────────────────────────────┘
```

Do not overcrowd the mobile header.

---

# 14. MOBILE BOTTOM NAVIGATION

Use:

```text
Home
Explore
Saved
Alerts
Profile
```

with icons and labels.

The active section should be clearly indicated.

Do not use icons without labels.

---

# 15. HOMEPAGE

The homepage must NOT immediately dump the user into a technical map.

Its purpose is to explain ChargePlus first.

## Hero

Use the main message:

> **Find the right charger, before you reach the queue.**

Supporting message:

> Find EV charging stations, compare your options and know what to expect before you arrive.

Primary CTA:

> **Find a charger**

Secondary action:

> **Explore stations**

The visual design should communicate EV charging and location without becoming visually cluttered.

---

# 16. HOMEPAGE FUNCTIONALITY SECTIONS

Introduce the main features through simple cards/sections.

### Find a charger

> Find charging stations near you or search any area.

### Check availability

> See which stations are currently reported available or busy.

### Compare stations

> Compare distance, charging speed, connector type and price.

### Save your stations

> Keep the stations you use most in one place.

### Get alerts

> Know when conditions change at your saved stations.

---

# 17. HOMEPAGE CTA

Primary:

```text
Find a charger
```

Clicking this opens the Explore/search experience.

Do not require login.

---

# 18. LOCATION PERMISSION

Never force location permission immediately.

The user explicitly chose:

> Location should be requested only when they choose to use their location.

Use:

```text
Use my location
```

When clicked:

* request browser location permission
* show loading state
* center map if permission succeeds
* show friendly explanation if permission is denied

If denied:

> We couldn't access your location. You can search for an area instead.

Do not break the entire site.

---

# 19. DEFAULT LOCATION

If location is unavailable:

Use **Mumbai** as the initial pilot area.

If user location is available:

Use the user's location.

---

# 20. EXPLORE PAGE

This is the primary product experience.

Desktop:

```text
┌───────────────────────┬────────────────────────────┐
│                       │ Search                     │
│                       │                            │
│                       │ [Search charging stations]│
│                       │                            │
│        MAP            │ Filters                    │
│                       │                            │
│   ●       ●           │ Station Card               │
│       ●               │                            │
│  ●          ●         │ Station Card               │
│                       │                            │
└───────────────────────┴────────────────────────────┘
```

Map on the left.

Station list on the right.

Mobile:

```text
┌──────────────────────────────┐
│ [ Search charging stations ] │
│                              │
│             MAP              │
│                              │
│       ●          ●           │
│                              │
│   ●              ●           │
│                              │
│ [Filters]     [Near me]      │
└──────────────────────────────┘
```

Station cards can appear as a bottom sheet or scrollable panel after interaction.

---

# 21. MAP

Use a clean map.

Do not visually overload it.

Station markers should be easy to identify.

Availability-aware markers:

```text
Available
Busy
Broken
Unknown
```

When several stations overlap, use clustering.

Do not automatically zoom into a location unless the user action clearly requires it.

---

# 22. MAP CONTROLS

Include:

* zoom in
* zoom out
* current location
* map/list switch
* search this area
* filters

Controls should not cover important map information.

On mobile, place controls where they are easy to reach.

---

# 23. MAP MARKER INTERACTION

When a user taps a station marker, show a compact station preview.

Example:

```text
┌────────────────────────────┐
│ Station Name            ♡  │
│ Operator                   │
│                            │
│ 1.8 km away                │
│ CCS2 • 120 kW              │
│ 4 chargers                 │
│ ₹18/kWh                    │
│                            │
│ ● Available                │
│ Updated 8 min ago          │
│                            │
│ [View station]             │
└────────────────────────────┘
```

Do not put advanced information on this preview.

---

# 24. SEARCH

Search must support:

* station name
* operator
* area
* locality
* address
* nearby places
* charging stations around a searched location

Use search suggestions while typing.

Example:

```text
Search charging stations

[ Andheri ]

Andheri East
Andheri West
Charging stations near Andheri
```

Search should feel forgiving and fast.

---

# 25. SEARCH LOADING

While searching:

* keep the interface visible
* show a small loading indicator
* do not blank the entire screen

---

# 26. SEARCH EMPTY STATE

Example:

> **No charging stations found**

> Try another area or change your filters.

CTA:

```text
Change filters
```

---

# 27. FILTERS

All of the following must be supported:

* distance
* connector type
* charging speed/power
* operator
* current availability
* likely availability
* price
* open now
* number of chargers
* fast charging
* free charging
* usually available
* usually busy

Do not use the term “predicted congestion” in the normal interface.

Use user-friendly language such as:

```text
Usually less busy
Usually busy
```

---

# 28. FILTER EXPERIENCE

Mobile:

Use a bottom sheet.

Desktop:

Use a side panel/popover.

Allow multiple filters at once.

Include:

```text
Clear all
Apply filters
```

Filter state must remain visible through chips or a clear filter indicator.

---

# 29. FILTER CHIPS

Example:

```text
CCS2 ×
Within 5 km ×
Available ×
Fast charging ×
```

The user should be able to remove individual filters quickly.

---

# 30. STATION CARD

Keep station cards simple.

Required information:

```text
Station Name
Operator

Distance

Connector type
Maximum charging power
Number of chargers

Price

Current status
Last update
```

Example:

```text
┌──────────────────────────────┐
│ Station Name              ♡  │
│ Operator                     │
│                              │
│ 1.8 km away                  │
│                              │
│ CCS2 • 120 kW                │
│ 4 chargers                   │
│                              │
│ ₹18/kWh                      │
│                              │
│ ● Available                  │
│ Updated 8 min ago            │
│                              │
│ [View station]               │
└──────────────────────────────┘
```

Do NOT show:

* technical confidence
* internal data sources
* model information
* congestion score
* complicated statistics

on the standard station card.

---

# 31. STATION STATUS LANGUAGE

If information is recent:

```text
● Available
Updated 8 min ago
```

If information is older:

Use appropriate wording such as:

```text
Availability updated earlier
```

If unavailable:

```text
Availability unavailable
```

Never imply real-time certainty when it does not exist.

---

# 32. STATION DETAIL PAGE

Structure:

```text
Back

Station Name                         ♡

Operator

★★★★☆ 4.3
128 reviews

[ Navigate ]

────────────────────────

Charging now

● Available

2 of 4 chargers available

Updated 8 min ago

────────────────────────

Chargers

CCS2
120 kW
2 available

Type 2
22 kW
1 available

────────────────────────

Price

₹18 / kWh

────────────────────────

Opening hours

Open 24 hours

────────────────────────

Usually busy

7 PM – 9 PM

────────────────────────

What drivers are saying

Review cards

[See all reviews]

────────────────────────

[ Report current status ]
```

---

# 33. STATION DETAIL — DO NOT SHOW DATA SOURCES

Do not show a “Data Sources” section to ordinary users.

Source/provenance information belongs behind the scenes.

The user only needs useful information and when appropriate:

> Updated 8 min ago.

---

# 34. CONNECTOR INFORMATION

Present connectors clearly.

Example:

```text
CCS2

120 kW
2 of 4 available
```

Another:

```text
Type 2

22 kW
1 available
```

Do not make connector information look like a technical specification sheet.

---

# 35. PRICING

Display clearly:

```text
₹18 / kWh
```

If pricing is unavailable:

```text
Price unavailable
```

Never invent a price.

---

# 36. OPENING HOURS

Show:

```text
Open now
Open 24 hours
Closes at 10 PM
Closed
```

Use natural language.

---

# 37. USUALLY BUSY SECTION

Where enough information exists, show simple useful guidance.

Example:

```text
Usually busy

7 PM – 9 PM

It may be easier to charge earlier in the day.
```

Do not show mathematical predictions.

If there is insufficient information:

```text
We don't have enough information yet
to estimate busy times.
```

---

# 38. RECOMMENDATIONS

Recommendations should appear within search results.

Do not create a separate intimidating “AI” area.

Example:

```text
Recommended for you

Station Name

✓ Matches your connector
✓ 2 chargers currently available
✓ 4.2 km away
✓ Usually less busy at this time

[View station]
```

The recommendation should explain itself in plain language.

Do not show:

```text
AI score: 87%
```

or:

```text
Recommendation probability: 0.87
```

---

# 39. RECOMMENDATION PLACEMENT

Recommendations should appear in relevant search-result contexts.

They should not dominate every screen.

If there is no meaningful recommendation, simply show normal results.

Never force a recommendation when there isn't enough information.

---

# 40. NAVIGATION

When user taps:

```text
Navigate
```

show:

```text
Navigate with

Google Maps
Apple Maps
Other map app

[Cancel]
```

Allow the user to choose their preferred navigation application.

Do not create an in-house navigation experience.

---

# 41. AUTHENTICATION

Browsing does not require an account.

Require an account only when necessary.

Actions requiring account:

* save station
* report station
* review station
* create alerts
* access personal information

---

# 42. LOGIN

Support:

* phone number
* email

No passwords.

Screen:

```text
Welcome to ChargePlus

Continue with phone number

[ +91 __________ ]

or

Continue with email

[ your@email.com ]

[ Continue ]

No password required.
We'll send you a verification code.
```

---

# 43. ACCOUNT CREATION

```text
Create your ChargePlus account

Phone number or email

[ Continue ]

We'll send you a verification code.
```

Do not create a password field.

---

# 44. OTP SCREEN

```text
Enter verification code

[ _ ][ _ ][ _ ][ _ ][ _ ][ _ ]

Didn't receive it?

Resend code

Change phone/email
```

Show appropriate loading/error states.

If OTP expires:

> This code has expired. Please request a new one.

---

# 45. REPORT FLOW

Login required.

Open a bottom sheet or modal.

```text
Report current status

What's happening?

[ 🟢 Available ]
[ 🟠 Busy ]
[ 🔴 Broken ]

Queue

[ None ]
[ Short ]
[ Medium ]
[ Long ]

Anything else? (optional)

[________________________]

[ Submit report ]
```

Keep it fast.

A driver should be able to submit a report in seconds.

---

# 46. REPORT SUCCESS

```text
Thanks!

Your update helps other EV drivers
know what to expect.

[Done]
```

---

# 47. REPORT FAILURE

```text
We couldn't submit your update.

Please try again.

[Try again]
```

Do not expose technical error details.

---

# 48. REVIEWS

Login required.

```text
How was this charging station?

☆ ☆ ☆ ☆ ☆

Tell other drivers about your experience.

[________________________]

[Post review]
```

Allow:

* 1–5 stars
* written comment

Keep the experience simple.

---

# 49. REVIEW CARD

Example:

```text
★★★★☆

Great charging station. Easy to access
and charging was quick.

2 days ago
```

Do not display unnecessary technical information.

---

# 50. SAVED STATIONS

Use heart icons.

Station cards can be saved directly from:

* map preview
* station card
* station detail

---

# 51. SAVED PAGE

```text
Saved stations

Station A
3.2 km
● Available

Station B
6.4 km
● Busy
```

Empty state:

```text
No saved stations yet

Save stations you use often
and find them quickly next time.

[Explore stations]
```

---

# 52. ALERTS

Initial alert types:

1. Station becomes available.
2. Station becomes less busy / conditions improve.

Example:

```text
Your alerts

Station becomes available

Station A

Notify me when charging becomes available
ON

────────────────

Usually busy

Station B

Tell me when it becomes a better time
to charge
ON
```

Do not expose technical threshold terminology by default.

---

# 53. PROFILE

```text
Profile

Name

Phone / Email

Language
English ▾

Saved stations

Your reports

Your reviews

Alerts

Help

Log out
```

---

# 54. HOME PAGE / MOBILE NAVIGATION RELATIONSHIP

Do not duplicate too many functions.

Homepage introduces the product.

Explore is where the actual station discovery happens.

Bottom navigation should make the main functions immediately reachable.

---

# 55. PAGE STRUCTURE

Use this logical structure:

```text
/
 /explore
 /station/[id]
 /search
 /favorites
 /alerts
 /reports
 /reviews
 /profile
 /login
 /verify
 /admin
```

Some experiences may be displayed as sheets/modals where that produces a better mobile experience.

The exact implementation should prioritize user flow over rigid URL/page behavior.

---

# 56. ADMIN

Admin is not part of the normal driver experience.

Keep it visually separate.

Admin may eventually include:

* station management
* report moderation
* review moderation
* information quality
* ingestion health
* forecast/model status
* system health

Do not expose admin terminology to ordinary users.

---

# 57. LOADING STATES

Every asynchronous screen must have a designed loading state.

Required:

* homepage loading where applicable
* station search loading
* station card loading
* station detail loading
* reviews loading
* saved stations loading
* alerts loading
* profile loading
* authentication loading
* report submission loading
* review submission loading
* recommendation loading

Use skeletons rather than blank white areas wherever appropriate.

---

# 58. EMPTY STATES

Design explicit empty states for:

* no nearby stations
* no search results
* no saved stations
* no alerts
* no reviews
* no reports
* unavailable station information
* insufficient information for busy-time guidance
* unavailable location

Every empty state should tell the user:

1. what happened
2. what they can do next

---

# 59. ERROR STATES

Friendly error messages only.

Examples:

### General

> Something went wrong.

> Please try again.

### Location

> We couldn't access your location.

> You can search for an area instead.

### Station information

> We couldn't load this station.

> Please try again.

### Login

> We couldn't sign you in.

> Please try again.

### Network

> You're having trouble connecting.

> Check your connection and try again.

---

# 60. ACCESSIBILITY

Build accessibility into every component.

Requirements:

* keyboard navigation
* visible focus states
* readable contrast
* semantic HTML
* screen-reader labels
* accessible forms
* accessible modals
* accessible bottom sheets
* accessible map controls
* accessible icon buttons
* status cannot rely only on color
* proper heading hierarchy
* appropriate form labels
* error messages associated with fields

Do not use tiny text for important information.

---

# 61. FOCUS STATES

Every keyboard-accessible control must have an obvious focus state.

Do not remove browser focus without replacing it with a strong visible state.

---

# 62. BUTTON SYSTEM

Create reusable variants:

### Primary

Warm coral.

Example:

```text
[ Find a charger ]
```

### Secondary

Light/outlined.

```text
[ Explore stations ]
```

### Destructive

Used sparingly for actions such as removing/clearing something where necessary.

### Icon button

For:

* favorite
* close
* map controls
* navigation controls

Every icon button must have an accessible label.

---

# 63. CARD SYSTEM

Cards should use:

* moderate corner radius
* subtle border
* minimal shadow
* generous internal spacing

Avoid huge floating shadows.

Avoid excessive rounded “pill” styling.

Use rounded pills primarily for:

* filter chips
* status badges
* compact controls

---

# 64. BOTTOM SHEETS

Use bottom sheets for mobile:

* filters
* station previews where appropriate
* report form
* navigation choice
* login prompts where appropriate

Bottom sheets must:

* have a visible handle
* support close
* support swipe/dismiss where appropriate
* trap focus when necessary
* prevent background interaction while modal
* work with keyboard on desktop if reused

---

# 65. MODALS

Use modals only for short focused tasks.

Do not put huge amounts of content into a modal.

---

# 66. ANIMATIONS

Use subtle professional animations.

Examples:

* station card appearance
* bottom-sheet opening
* filter opening
* favorite interaction
* button feedback
* page transitions
* loading transitions

Avoid:

* bouncing UI
* excessive parallax
* glowing effects
* constant movement
* distracting animations

Respect reduced-motion preferences.

---

# 67. MAP UX

When the user pans the map:

Provide a useful:

```text
Search this area
```

action rather than constantly changing the results unexpectedly.

When a marker is selected:

* highlight marker
* show station preview
* allow opening detail

When a station card is selected:

* center/highlight the corresponding marker when appropriate

Keep map/list synchronization smooth.

---

# 68. STATION LIST SORTING

Allow sensible sorting such as:

* nearest
* available now
* charging speed
* price
* recommended

Do not use complicated sorting terminology.

---

# 69. DATA FRESHNESS

The interface must never pretend that old information is current.

Examples:

Recent:

> Updated 8 min ago

Older:

> Updated earlier

Unavailable:

> Availability unavailable

The exact wording can adapt based on the age of the information.

---

# 70. UNKNOWN DATA

If information doesn't exist:

Do NOT display:

```text
N/A
null
undefined
0
false
```

Instead use natural language:

```text
Price unavailable
Availability unavailable
Hours unavailable
```

Do not invent values.

---

# 71. RECOMMENDATION DATA

Only show recommendations when meaningful information exists.

If not:

Show normal stations.

Do not manufacture intelligence simply to make the interface appear “AI-powered.”

---

# 72. DATA PRESENTATION PRINCIPLE

Every displayed piece of information should answer:

> **Does this help the driver make a decision?**

If not, don't put it on the screen.

---

# 73. RESPONSIVE BREAKPOINT BEHAVIOR

## Mobile

* single-column content
* map-first Explore
* bottom sheets
* bottom navigation
* large touch targets
* compact header

## Tablet

* more content visible
* flexible map/list
* larger station cards

## Desktop

* map + station list side-by-side
* persistent header
* filter panel
* larger station detail layouts

## Large desktop

Do not stretch content endlessly.

Use a sensible maximum content width.

---

# 74. FOOTER

Desktop footer can contain:

```text
ChargePlus

Find charging stations
About
Help
Contact
Privacy
Terms

Language
English | हिन्दी | मराठी
```

Keep it simple.

---

# 75. TRUST

ChargePlus must communicate useful information without overpromising.

Avoid statements like:

> Guaranteed charger availability.

Instead:

> Currently reported available.

Avoid:

> Guaranteed low queue.

Instead:

> Usually less busy around this time.

This is essential because charging information can change.

---

# 76. NO LOGIN WALL

A new visitor must be able to immediately:

* understand ChargePlus
* search
* explore
* view stations
* use filters
* see station details
* choose navigation

without creating an account.

---

# 77. ACCOUNT PROMPTS

When a logged-out user clicks:

```text
Save
Report
Review
Alert
```

show a friendly login prompt.

Example:

> Create a free ChargePlus account to save this station.

Buttons:

```text
Continue
Not now
```

Do not aggressively interrupt the user.

---

# 78. FAVORITE INTERACTION

When saving:

```text
♡ → ♥
```

Provide subtle feedback.

Example:

> Station saved.

When removing:

> Removed from saved stations.

---

# 79. REVIEW VALIDATION

Prevent:

* empty review
* invalid rating
* extremely malformed input

Show clear inline validation.

---

# 80. REPORT VALIDATION

Require:

* station
* current status

Queue is optional if appropriate.

Comment is optional.

Keep validation minimal because reports should be quick.

---

# 81. FORM DESIGN

Forms must have:

* visible labels
* helpful placeholders
* clear error states
* clear submit state
* disabled state while submitting
* success confirmation

Do not rely only on placeholder text as a label.

---

# 82. PERFORMANCE

The frontend must feel fast.

Use:

* lazy loading where useful
* image optimization
* code splitting
* sensible map loading
* efficient station queries
* pagination/infinite scrolling where appropriate
* caching for relatively stable information
* skeleton loading

Do not load thousands of stations unnecessarily.

---

# 83. MAP PERFORMANCE

Do not render every station as a separate heavy component when zoomed far out.

Use clustering.

Load appropriate station detail as the user gets closer.

---

# 84. REAL DATA READY

The frontend must not depend on fake hard-coded station data.

During development, temporary sample data may be used behind a clear development layer.

The architecture must allow replacement with real data without rewriting the UI.

---

# 85. FRONTEND DATA STRUCTURE

Create clean shared types for concepts such as:

```text
Station
Operator
Connector
StationStatus
Review
UserReport
Favorite
Alert
Recommendation
```

Do not duplicate the same object structure across components.

---

# 86. API/REMOTE DATA HANDLING

Separate:

* screen components
* reusable UI components
* data loading
* user actions
* formatting
* translations

The UI should not contain large amounts of data-fetching logic.

Use reusable loading/error handling patterns.

---

# 87. USER-FACING DATE/TIME

Display friendly relative times when useful:

```text
Updated just now
Updated 8 min ago
Updated 1 hour ago
Updated yesterday
```

Do not expose raw timestamps to ordinary users unless appropriate.

---

# 88. DISTANCE

Use driver-friendly formatting:

```text
800 m
1.2 km
4.8 km
```

Do not display unnecessary decimal precision.

---

# 89. PRICE

Use Indian formatting:

```text
₹18/kWh
₹1,250/session
```

depending on the available pricing information.

Never invent missing prices.

---

# 90. NUMBER OF CHARGERS

Use natural language:

```text
4 chargers
2 available
```

rather than internal terminology.

---

# 91. STATION STATUS HIERARCHY

Prioritize:

1. Station name
2. Distance
3. charging compatibility
4. charging speed
5. current availability
6. price
7. additional useful information

Do not let secondary information overpower the station identity.

---

# 92. HOME PAGE VISUAL HIERARCHY

The user should understand within seconds:

```text
What is ChargePlus?
        ↓
What can I do?
        ↓
Find a charger
```

Do not make the homepage look like an admin dashboard.

---

# 93. DESKTOP EXPLORE

The preferred desktop layout is:

```text
┌────────────────────────────────────────────────────┐
│ Header                                              │
├───────────────────────┬────────────────────────────┤
│                       │ Search                     │
│                       │                            │
│                       │ Filters                    │
│         MAP           │                            │
│                       │ Recommended station       │
│                       │                            │
│                       │ Station                    │
│                       │ Station                    │
│                       │ Station                    │
└───────────────────────┴────────────────────────────┘
```

The list should remain scrollable independently where appropriate.

---

# 94. MOBILE EXPLORE

Preferred:

```text
Header
Search
Map
Map controls
Filter button
Station bottom sheet
Bottom navigation
```

When the user selects a station, the card should expand naturally.

---

# 95. STATION PAGE MOBILE

Use:

```text
Back
Station name + favorite

Rating

Navigate

Charging now

Chargers

Price

Hours

Usually busy

Reviews

Report
```

Avoid huge blocks of text.

---

# 96. AUTHENTICATION MOBILE

Authentication should be extremely simple.

Large input.

Large continue button.

Clear OTP experience.

Minimal distractions.

---

# 97. LANGUAGE-SAFE DESIGN

Hindi and Marathi text can have different lengths.

Therefore:

* don't hard-code fixed-width text containers unnecessarily
* allow buttons to grow
* allow navigation labels to wrap or adapt
* don't position text based on exact English width
* test every major screen in all three languages

---

# 98. DARK MODE

Do not prioritize dark mode for the first version.

The brand direction is a clean, light experience.

If dark mode is later introduced, it must preserve the warm brand identity and avoid blue/neon/cyan.

---

# 99. SECURITY / PRIVACY UX

Never display:

* user IDs
* internal IDs
* database IDs
* technical tokens
* internal error messages
* private user information

Do not expose another user's private information.

---

# 100. FINAL UX PRINCIPLE

Every screen should pass this test:

> **Could an ordinary EV driver understand this without knowing anything about ChargePlus's technology?**

If not, simplify it.

---

# 101. FINAL PRODUCT JOURNEY

The complete experience should be:

```text
Landing page
     ↓
Understand ChargePlus
     ↓
Find a charger
     ↓
Search / location
     ↓
Map + stations
     ↓
Filter
     ↓
Compare
     ↓
View station
     ↓
See current information
     ↓
See useful busy-time guidance
     ↓
Choose station
     ↓
Navigate
```

Optional account journey:

```text
Save
 ↓
Login / create account
 ↓
Saved station
 ↓
Alerts
```

Community journey:

```text
View station
 ↓
Login
 ↓
Report status
or
Leave review
```

---

# 102. DEFINITION OF DONE

The frontend is NOT considered complete until all of the following work:

### Public experience

* [ ] Landing page
* [ ] Product explanation
* [ ] Find charger CTA
* [ ] Explore page
* [ ] Map
* [ ] Station markers
* [ ] Marker clustering
* [ ] Search
* [ ] Search suggestions
* [ ] Filters
* [ ] Station cards
* [ ] Station details
* [ ] Navigation selection

### Account

* [ ] Phone login
* [ ] Email login
* [ ] OTP verification
* [ ] Account creation
* [ ] Profile
* [ ] Logout

### Community

* [ ] Report status
* [ ] Report success
* [ ] Report failure
* [ ] Star rating
* [ ] Written review
* [ ] Review list

### Personal features

* [ ] Saved stations
* [ ] Alerts
* [ ] Favorite interactions

### Languages

* [ ] English
* [ ] Hindi
* [ ] Marathi

### UX states

* [ ] Loading
* [ ] Empty
* [ ] Error
* [ ] Success
* [ ] Disabled
* [ ] Submitting
* [ ] Offline/network failure
* [ ] Unknown information

### Responsive

* [ ] Mobile
* [ ] Tablet
* [ ] Desktop
* [ ] Large desktop

### Accessibility

* [ ] Keyboard
* [ ] Focus states
* [ ] Screen-reader labels
* [ ] Color-independent status
* [ ] Touch-friendly controls
* [ ] Form accessibility

### Quality

* [ ] No technical jargon in normal user-facing UI
* [ ] No fake station information in production
* [ ] No invented availability
* [ ] No invented prices
* [ ] No misleading predictions
* [ ] No blue/neon/cyan visual styling
* [ ] Warm ChargePlus palette used consistently
* [ ] English/Hindi/Marathi layouts tested
* [ ] Mobile-first behavior tested
* [ ] Error states tested
* [ ] Loading states tested
* [ ] Empty states tested
* [ ] Navigation flows tested
* [ ] Authentication flows tested
* [ ] Report/review flows tested
* [ ] Favorite/alert flows tested

---

# 103. MOST IMPORTANT INSTRUCTION

Do not build this as a collection of pretty screens.

Build it as **one coherent product**.

The user should always understand:

* where they are
* what they can do
* what information means
* what happens when they tap something
* how to go back
* how to recover from an error
* whether information is current
* what action they should take next

Prioritize clarity over decoration.

Prioritize usefulness over technical complexity.

Prioritize trust over impressive-looking claims.

Prioritize mobile usability.

Prioritize real-world EV-driver behavior.

The final result should feel like:

> **ChargePlus — a simple, friendly place to find the right charger before 
you reach the queue.**

The ChargePlus frontend must be extensible for all currently planned future product capabilities, including trip planning, station comparison, charging/history views where real data exists, personalized preferences, richer station insights, notifications, community trust features, operator/admin experiences, and an installable mobile web experience. These capabilities must be accommodated through the existing navigation, component, layout, and design system without requiring a visual redesign of the core product. Future features must extend the existing experience rather than replace it. Do not build speculative features merely for future-proofing; only implement functionality when its underlying data and product requirements exist.
