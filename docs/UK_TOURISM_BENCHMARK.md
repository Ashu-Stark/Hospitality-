# Benchmark: uttarakhandtourism.gov.in (tourism side) vs our portal

**Audience:** the team. **Method:** rendered the official site in Chrome on 13 Oct 2026 (home, a destination page (Auli), an
experience page (Into the wild), the itineraries page) and recorded its menus, page sections and page lengths.
We copy **structure and useful features only**: no logos, photos, text, colours or branding (our portal is a concept and must
not look like the official site).

## 1. What the official site has

**Top menu (exact labels):** HOME · CHARDHAM REGISTRATION · BOOK HOMESTAY · EXPLORE (destinations A–Z: Almora, Abbott Mount,
Auli, … View All) · EXPERIENCE (Into the wild, Leisure, Spirituality, Festivals & Fairs, Yoga & Wellness, Char Dham,
Panch Kedar, Explore Adventures, Museums, Community Museum) · PLAN (Tourist Guide, Trekking, Itineraries, Tourism Circuit) ·
TRADE (Travel Trade Registration, Invest In Uttarakhand, Homestay/B&B Registration, Tourist Guide Registration) · GALLERY
(Photo, Video) · POLICY & SCHEMES · SEARCH. English/हिन्दी and A-/A/A+ in the top bar.

**Home, in order (≈7,350 px tall):** campaign hero carousel ("Trek of the year") · "contact your District Tourism Officer"
strip · "Latest Updates" ticker (registration links) · Latest Gallery Highlights carousel · **Explore Uttarakhand: 5 themes**
(Wildlife, Adventure, Wellness, Spirituality, Leisure) · What's Trending (tabs per theme) · **Explore the Unexplored:
interactive map by Circuit / District with category icons** (wildlife, cultural heritage, winter sports …) · blog stories ·
social · a footer with ~45 links (RTI, tenders, policies, PDFs).

**Destination page (Auli, ≈7,070 px):** highlights bullets · What to Know · Attractions (each with a paragraph) · What To Do ·
Weather · Get Direction · How to Reach · Where to Stay · Nearby Destinations.

**Experience page:** one intro paragraph + a grid of places. **Itineraries page:** a list of named tours/treks
("Do Dham Yatra", "Mussoorie weekend trip", "Tour No. 4 Rishikesh–Yamunotri–Gangotri–Kedarnath–Badrinath–Rishikesh", …).

**E-services are spread across separate sites:** Char Dham registration, homestay booking, homestay registration, travel trade
registration, tourist guide registration and investment each live on a different domain with its own sign-in.

## 2. What works there (adopt)

1. **Experience-led discovery.** Visitors think "spiritual trip", "wildlife", "adventure", not district names. Five to six themes is the right number.
2. **Plan section** with circuits and ready itineraries.
3. **Destination page sections** match real questions: what is it, what to see, what to do, weather, how to reach, where to stay, what is nearby.
4. **Map browsing** by circuit and district.
5. **District tourism officer contact** on every page that matters.
6. Bilingual + text-size controls (we already have them).

## 3. What does not work (avoid; our differentiation)

1. **Very long pages** (7,000+ px home and destination pages) and a 45-link footer: the same problem our user flagged.
2. **Static information:** no live crowd level, no live road status, weather as text. Nothing tells a visitor "should I go this week?".
3. **Fragmented services:** five registration/booking sites with separate logins; documents as PDFs.
4. **No verification for tourists** (is this homestay/guide registered?) and **no grievance tracking** on the tourism site.
5. **No feedback loop to the state:** no occupancy or crowd data flowing back from hotels.

## 4. Changes to our portal

| Area | Change |
|---|---|
| Navigation | Explore · **Experiences** · **Plan** · Verify a business · Help (+ Dictionary inside Help/Plan), Sign in ▾. Max 5 items, phone bottom bar unchanged. |
| Home | Keep it short. Add one row "Explore by experience" (6 themed tiles, no photos: our own SVG illustrations) under the task cards. Keep crowd strip, alerts, coming up. Add "District tourism office" quick contact via Help. |
| Experiences | New section: Spiritual & Char Dham · Adventure & Treks · Wildlife & Nature · Yoga & Wellness · Hill towns & Leisure · Culture, Fairs & Museums. Each page: one-paragraph intro (our own words), destinations with live crowd + weather, related festivals, related dictionary terms. |
| Plan | New section: **Itineraries** (sample multi-stop trips built only from our curated destinations, each stop showing live crowd + weather + road status; "suggested days" is a planning suggestion, labelled sample; no invented distances/times), **Circuits** (Char Dham, Kumaon hills, Corbett & foothills, Garhwal hill stations), **Map view** (schematic dot map from lat/lon with circuit/district/theme filters: no invented state outline), How to reach (curated route facts), Official services (external links to official Char Dham registration and homestay booking, marked "official site, opens in new tab"). |
| Destination page | Tabs aligned to visitor questions: Overview (highlights + what to know) · Weather · Getting there (+ "Get directions" link with coordinates) · Crowd · Stay & guides · **Nearby** (computed by distance from coordinates) · Festivals · Help. At-a-glance tiles stay first. |
| Services | One account for all registrations (homestay, hotel, guide, travel agent, tour operator, transport, adventure): our unified business hub, presented as "one window" versus separate sites. |
| Footer | Stays slim; no link dump. |
