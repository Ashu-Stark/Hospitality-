# Reference IA notes: a hostel / homestay / trips platform (zostel.com)

**Date looked:** 2026-10-13. **Structure only:** no text, branding, colours, fonts or photos were copied, and the
portal UI does not name this site anywhere.

## What we could and could not check

An automated look with Playwright and an installed Chrome (`https://www.zostel.com/` and `/destinations/`) got only a
"human verification" challenge page. A plain HTTP request for `robots.txt` got `405 Not Allowed`. We did **not** try to
get around the challenge. So **none of the structure below was confirmed on the live site today**. It is the
**common pattern of hostel / homestay / trips platforms like this one**, from general familiarity, and may be out of
date. A team member should check it in a normal browser before anyone quotes it.

## Pattern (approximate, to verify)

| Aspect | Typical pattern |
|---|---|
| Top navigation | Destinations; property lines (hostels, homestays, premium stays); trips / experiences; partner or "become a host" / franchise entry; sign in / app download |
| Home page order | Big photo hero with search (where, dates, guests) -> destination cards -> property lines -> trips / experiences -> partner call-to-action -> community / app -> footer |
| Card anatomy | Photo first; place name; region; short tagline; price-from or "from" chip; rating; one clear tap target |
| Filters / search | Destination search first; on listing pages chips or tabs by type; dates and guests in the booking step |
| Partner entry | A friendly page aimed at property owners: why join, what you get, steps to apply, a lead form or sign-up |
| Footer groups | About / company; partner with us; support / FAQ; policies; social links |

## How our portal maps to it

| Reference section (pattern) | Our section | Notes |
|---|---|---|
| Destinations | **Destinations** (`#/destinations`, map) | Photo cards: district, best months, today's crowd pill, temperature if cached, one-line "why go" |
| Hostels / homestays / property lines | **Stays** (`#/stays`) | Registered hotels and homestays from our registry; type, destination, rating, Verified; registration-number check sits here |
| Experiences | **Experiences** (`#/experiences`) | Community-hosted local experiences first, then curated themes and the festivals calendar |
| Trips | **Trips** (`#/plan`) | Sample itineraries and circuits with live per-stop crowd, weather and roads |
| Partner / become a host / franchise | **List your property** button (`#/host`) | One onboarding for every business type: who can join, four steps, documents checklist, then the existing register -> apply -> officer review flow |
| Careers (footer) | **Jobs** (top nav) | Kept as a top pillar: hiring board, staffing agencies, HOI staffing requests |
| Support / FAQ (footer) | **Help & complaints** (utility bar + footer) | Helplines, grievance filing and tracking, dictionary, rules |
| Sign in | Sign-in menu | Business, job seeker and officials sign-in; officials are also in the footer |
| Booking / payment | Not offered | Concept portal: "Request to join" only, no payments |

Top navigation decision: **Destinations · Stays · Experiences · Trips · Jobs** (5 items), plus a **List your property**
button. Help moved to the utility bar and footer because it is a support task, not a way of choosing where to go.
