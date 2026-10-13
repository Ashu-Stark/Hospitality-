# Uttarakhand Tourism & Hospitality Portal (concept): build spec

**Status:** hackathon concept prototype. **Not an official government website.** No government emblem, seal,
logo, domain or department name may be used as branding. Every page shows a slim banner:
"Concept prototype for the AI-Tourism Hackathon 2026, not an official Government of Uttarakhand website. Data is sample/synthetic unless marked otherwise."

Working name: **"Uttarakhand Tourism & Hospitality Portal (concept)"**, short name **"UTHP"**. Part of the HOI project.

## 1. Who it is for

| Audience | Login | What they do |
|---|---|---|
| Tourist / citizen | none | Search everything, plan a trip (weather, roads, crowd level, festivals), verify a business, file and track a grievance, read the dictionary |
| Business (hotel, homestay, guide, travel agent, tour operator, taxi/transport, adventure operator, restaurant) | account | Apply for registration, renew, see status, submit monthly occupancy, get an API key so HOI-run hotels report automatically |
| District tourism officer | account (scoped to one district) | Review applications, handle grievances, publish road/weather advisories and events for the district, see district analytics |
| State admin | account | Everything above for all districts, manage officers, state analytics (rush, occupancy, market growth, workforce) |

## 2. Modules

1. **Unified search** across registry, destinations, dictionary, rules, festivals, advisories (MongoDB text indexes, one `/api/v1/search?q=` endpoint grouping results by type).
2. **Registry / directory (A–Z):** businesses with type, district, destination, registration number, status (active / expired / suspended / pending), verified badge, rating, capacity, languages, contact placeholder. Filter by type/district/destination/status; A–Z letter index. "Verify a business" by registration number.
3. **Destinations:** page per destination with district, altitude (approx.), best months, live weather, road connectivity, crowd level now + 14-day outlook, nearby registered stays/guides, festivals and advisories.
   - **Weather:** server-side call to Open-Meteo (`https://api.open-meteo.com/v1/forecast`, no key) with lat/lon; cache 30 min in MongoDB; fall back to a "live weather unavailable" state. Show current temp, 7-day min/max, precipitation probability, and a plain-language warning when heavy rain/snow is forecast.
   - **Road connectivity:** static route facts (from section 5, marked "approximate, verify") + live advisories posted by officers (open / caution / closed, segment, reason, posted_at, expires_at). Sample advisories are seeded and labelled sample.
   - **Crowd level ("rush"):** index 0–100 from occupancy of registered stays in that destination (submitted or HOI-ingested; synthetic history seeded), festival/yatra calendar, weekends and season. Bands: low < 40, moderate 40–64, high 65–84, very high ≥ 85. Show today, a 14-day outlook bar strip, and a month-by-month "usual crowd" chart. Always labelled "estimate".
4. **Festivals & events calendar:** month view and list; each with destination/district, usual month window, description, crowd impact. Lunar-calendar dates are "announced annually; check official notice".
5. **Dictionary (tourism & hospitality A–Z):** 80+ terms (hospitality ops, revenue metrics, tourism, regulation, trekking/safety, local terms). Each: term, Hindi term where natural, category, plain definition, example, related terms. Letter index + category filter + search.
6. **Rules, licences & schemes explainer:** plain-language cards (who needs it, what it covers, typical documents, where to apply), each flagged **"summary for orientation, verify with the issuing authority"**. No invented section numbers, fees, thresholds or act names.
7. **Helplines & advisories:** helplines list (section 5) + active advisories by district.
8. **Grievances:** tourist files (category, district, business reg. no. optional, description, optional contact kept private); gets ticket id + 6-digit tracking code; status: received → assigned → in progress → resolved / closed; SLA 7 days (ASSUMED); officer notes; rate-limited per IP.
9. **Business onboarding:** register account → application (type, district, destination, capacity, documents checklist ticks; no file upload in the prototype) → officer review (approve / request changes / reject, with reason) → registration number `UK-<TYPE>-<DISTRICT CODE>-<NNNNN>` → renewal yearly. Business dashboard: status, monthly occupancy submission form, API key (shown once, stored hashed) for automated ingest.
10. **Officials' analytics dashboard:**
    - KPIs: registered businesses, active rooms/beds, applications pending, grievances open / overdue, average occupancy last 30 days, crowd-level alerts.
    - **Rush:** destination × week heatmap (next 8 weeks + last 8), top-10 busiest destinations, alert list where outlook ≥ 85.
    - **Occupancy:** state and per-district trend (daily, 12 months), by business type.
    - **Market growth:** synthetic tourist arrivals and registrations by year (2019–2026) and district, YoY growth %, new registrations per month. Big "SYNTHETIC" label: never present as official statistics.
    - **Workforce (from HOI, aggregated only):** staff count, roles, share flagged for review, turnover; shown only when ≥ 5 businesses contribute in a group (k-anonymity), never per person, never per business.
    - **Grievances:** by category and district, SLA breach rate, median resolution days.
    - Every chart has a "view as table" toggle (accessibility).
11. **HOI integration:** `POST /api/v1/ingest/occupancy` with `X-API-Key` (business key): `{date, rooms_available, rooms_occupied, staff_count?, staff_flagged?}`. Idempotent per (business, date). This is how HOI-run hotels feed the state view.

## 3. Technical design

- Folder `portal/`, package `hoi_portal`, FastAPI app `hoi_portal.main:app`, port **8200**. MongoDB per docs/MONGODB.md (database `hoi_portal`).
- Layers like `platform_api`: `config.py`, `mongo.py`, `security.py` (PBKDF2 + JWT, same approach), `deps.py`, `schemas.py`, `services/`, `routers/`, `seed/` (synthetic + curated reference data), `static/` (the web app).
- Same production guard as platform_api (`HOI_ENV=production`: strong `PORTAL_JWT_SECRET`, admin password, no demo login, explicit CORS, real `MONGODB_URI`).
- Rate limits on login, register, grievance filing, tracking lookups, ingest.
- Security headers + strict CSP (`script-src 'self'`; fonts from Google Fonts allowed; `connect-src 'self'`; no inline scripts/styles set via attributes; set styles through the DOM).
- Frontend: static HTML + vanilla JS (no build), hash router, served by FastAPI at `/`. Hand-written accessible SVG charts (line, bar, heatmap, strip) with table fallback. Responsive 360 px → desktop. English/Hindi toggle for navigation and key labels (Hindi to be reviewed by native speakers).
- Design language: the same as the rest of HOI (Train.png): see `platform_api/hoi_platform/static/shared/base.css` and `website/index.html`: Inter Tight, pill navigation with black active pill, blue gradient CTA, outline status cards, soft off-white background, WCAG AA colours (muted #6b6a65, blue text on tint #1557c0), visible 3 px focus ring, reduced-motion support. Follow GIGW-style practices: skip link, sitemap page, "last updated" on content pages, accessibility statement, keyboard navigation.
- Seed: deterministic (fixed seed). Synthetic businesses must have obviously synthetic names (e.g. "Sample Homestay 014, Munsiyari"), never names that could be real businesses. Synthetic history: daily occupancy per business for 2 years; arrivals by district per year 2019–2026; 300+ businesses across all 13 districts; 40 grievances; 20 applications in various states; sample advisories.
- Demo accounts (dev only, one-click like HOI): state admin, district officer (Rudraprayag), business owner.

## 4. Tests (pytest, mongomock, offline)

Search, registry filters + verify by reg no., destination detail (weather mocked), crowd index bands, grievance file → track → officer resolve, scoping (district officer cannot see another district), application → approve → reg no. issued, ingest with API key (idempotent, wrong key 401), k-anonymity on workforce, rate limit, security headers, production config guard.

## 5. Curated reference facts (use as given; all marked "approximate, verify")

**Districts (13):** Almora, Bageshwar, Chamoli, Champawat, Dehradun, Haridwar, Nainital, Pauri Garhwal, Pithoragarh, Rudraprayag, Tehri Garhwal, Udham Singh Nagar, Uttarkashi. Divisions: Garhwal (Chamoli, Dehradun, Haridwar, Pauri Garhwal, Rudraprayag, Tehri Garhwal, Uttarkashi), Kumaon (the other six).

**Destinations (approximate lat, lon; district):**
Kedarnath 30.735, 79.067 (Rudraprayag) · Badrinath 30.744, 79.493 (Chamoli) · Gangotri 30.994, 78.940 (Uttarkashi) · Yamunotri 31.014, 78.460 (Uttarkashi) · Rishikesh 30.087, 78.268 (Dehradun) · Haridwar 29.945, 78.164 (Haridwar) · Mussoorie 30.459, 78.064 (Dehradun) · Dehradun 30.316, 78.032 (Dehradun) · Nainital 29.380, 79.463 (Nainital) · Jim Corbett / Ramnagar 29.394, 79.126 (Nainital) · Auli 30.528, 79.566 (Chamoli) · Valley of Flowers 30.728, 79.605 (Chamoli) · Chopta 30.486, 79.211 (Rudraprayag) · Almora 29.597, 79.659 (Almora) · Kausani 29.840, 79.600 (Bageshwar) · Munsiyari 30.067, 80.238 (Pithoragarh) · Lansdowne 29.840, 78.680 (Pauri Garhwal) · Dhanaulti 30.430, 78.240 (Tehri Garhwal) · New Tehri / Tehri Lake 30.380, 78.430 (Tehri Garhwal) · Lohaghat 29.405, 80.090 (Champawat) · Bageshwar 29.838, 79.771 (Bageshwar) · Pithoragarh 29.583, 80.218 (Pithoragarh) · Kashipur 29.210, 78.960 (Udham Singh Nagar) · Pauri 30.150, 78.780 (Pauri Garhwal).

**Seasonality hints (general, verify):** Char Dham shrines usually open around late April–May and close around October–November (dates announced each year); monsoon July–September brings landslide risk on hill roads; snow at higher places (Auli, Chopta, Munsiyari) in winter; Corbett core zones close in the monsoon (verify current zone dates); Valley of Flowers is usually open roughly June–October.

**Festivals (usual timing; lunar dates vary, announced annually):** Uttarayani fair, Bageshwar (January, Makar Sankranti) · Phool Dei (March, Chaitra) · International Yoga Festival, Rishikesh (March) · Char Dham yatra opening (April–May) · Ganga Dussehra, Haridwar/Rishikesh (May–June) · Harela (July) · Kanwar Yatra, Haridwar (July–August, Shravan) · Nanda Devi fair, Almora/Nainital (August–September) · Dussehra and Diwali (October–November) · Char Dham closing (October–November) · Christmas–New Year rush in Mussoorie/Nainital (December–January) · winter snow season at Auli (December–February).

**Road connectivity facts (approximate, verify):** Rishikesh–Badrinath corridor via NH-7; Rishikesh–Gangotri via NH-34; Kedarnath is reached by road to Gaurikund then a trek of roughly 16–18 km (or helicopter services from the valley); Yamunotri is reached by road to Janki Chatti then a trek of about 5–6 km; Valley of Flowers via Govindghat and Ghangaria (trek); nearest major airport for Garhwal is Jolly Grant (Dehradun) and for Kumaon is Pantnagar; major railheads Dehradun, Haridwar, Rishikesh (Yog Nagari Rishikesh), Kathgodam, Ramnagar, Tanakpur. No distances or travel times beyond these.

**Helplines:** 112 (all-India emergency) · 108 (ambulance) · 1363 / 1800-11-1363 (Ministry of Tourism tourist helpline) · 1077 (district disaster control room, verify per district) · state tourism and police tourist-help numbers: placeholders "to be filled by the department", never invented.

**Rules & licences cards (orientation only, verify):** state tourism trade registration (check with the state tourism department/board) · homestay registration under the state homestay scheme (name and terms to verify) · FSSAI registration/licence for food service · GST registration (threshold depends on turnover/state; ask a GST practitioner) · fire safety NOC for larger premises · pollution control board consent where applicable · trade licence from the local body · Form C reporting of foreign guests to FRRO · guide licensing/training (verify) · adventure activity (rafting, trekking, paragliding) permits and safety rules (verify with the district/forest department) · inner-line permits for certain border areas (from district administration) · forest/protected-area entry permits (national parks, sanctuaries).
