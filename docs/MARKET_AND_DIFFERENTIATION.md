# Market, competitive landscape and differentiation

**Audience:** the team (and the basis for what we say to judges). **Researched:** 13 Oct 2026 by web search; every factual claim has a
source in [square brackets] that maps to the list at the end. **Nothing here is customer-validated yet:** HOI has no real hotel, no
interviews and no pilot. Vendor pages are marketing; secondary sources (blogs, Wikipedia, aggregators) are marked as such. Prices and
percentages are what a source says on the date shown, not quotes we obtained.

Legend: **E** = evidence from a source · **A** = our assumption, to validate · **UNVERIFIED** = we looked and could not confirm.

---

## 0. Answer to the judges (10 things we can say out loud)

1. **We studied the stack.** Hotels sell rooms through four layers: GDS (Amadeus, Sabre, Travelport) for travel agents and corporate
   bookers; OTAs (Booking.com, Agoda, MakeMyTrip/Goibibo, Airbnb) for consumers; channel managers that sync rates across them; and a PMS
   that runs reservations and billing. All four layers are about **selling the room**.
2. **GDS is irrelevant for a 10-room homestay.** Its buyers are travel agents and corporate travel desks, reached through a CRS/channel
   manager [S1]. A Mussoorie homestay's guests come from OTAs, Airbnb, word of mouth and walk-ins. We will not build or connect to a GDS.
3. **We do not compete with eZee, STAAH or Hotelogix; we sit next to them.** They own reservations and distribution. HOI owns what
   happens after the booking: who works which shift, who cleans room 4 now, what runs out next week, who is about to leave.
4. **Zostel and OYO solve brand and demand, not the staff on the ground.** Zostel is a franchise (franchisee-owned, franchisee-operated)
   brand [S11][S12]; OYO lists owner-run hotels and gives owners an app for bookings, pricing and payouts [S14]. Neither publicly offers
   rostering, live job dispatch with proof, or staff retention for the owner's own team (to the best of our search).
5. **Our differentiator:** HOI is the **people-and-operations layer for small hill properties**: forecast-driven fair rosters, live jobs
   with photo proof, seasonal staffing and local experiences, on a Hindi phone app, and it plugs into whatever PMS/OTA the owner already uses.
6. **Affordability is a design choice, not an afterthought:** a **homestay mode** (1 property, few staff, no ML screens), phone-first PWA
   that loads on a cheap Android, Hindi, and a free tier we propose to validate. We do not ask an owner to replace their PMS.
7. **Staffing is the problem with evidence behind it.** Industry bodies report a shortage of skilled hospitality workers and high
   entry-level attrition [S27][S28][S39]. We turn a roster gap into a **staffing request** on our hiring board, which agencies and
   government skilling institutes (Hunar Se Rozgar Tak must place trainees within 3 months [S22]) can answer.
8. **Incentives without surveillance.** Recognition points tied to completed, verified service (not to tracking people) are supported by
   field-experiment evidence [S29], while research also warns that money incentives can backfire [S30] and electronic monitoring raises
   stress without improving performance [S31]. Our safeguards: team-level goals, no leaderboard of the bottom, no location tracking.
9. **Community and local linkages come from the state's own direction.** Uttarakhand's revised homestay rules (reported May 2026) add a
   **community-based tourism unit** of 8 to 10 homestays [S19]; Sarmoli (Munsiari) and Village Ways (Binsar) show homestays + local
   guides + food/craft experiences working [S34][S35]. Our portal links homestays ↔ local experiences ↔ local workers.
10. **What we will prove next:** 8 to 10 interviews with homestay owners, small-hotel GMs and staff in Mussoorie/Rishikesh, then a
    two-week pilot on one property. Today everything is synthetic (TRL 4); we will not claim results we do not have.

---

## 1. Distribution technology, explained simply

### 1.1 The four layers

| Layer | What it does | Who uses it | Typical cost model (as sources state) | Relevance to a 10-room hill homestay |
|---|---|---|---|---|
| **GDS** (Global Distribution System): Amadeus, Sabre, Travelport | A network that shows hotel (and flight, car) availability and rates to **travel agents, corporate bookers and wholesalers**; hotels connect through a CRS or channel manager [S1]. Other old GDSs were absorbed into these three [S2]. | Chains, business and upscale hotels in corporate/leisure hubs [S1][S2] | Per-booking/transaction fees plus agent commission are commonly described; **we found no primary fee schedule (UNVERIFIED)**. Usually reached through a paid "GDS rep"/connectivity provider [S2]. | **Low.** Its buyers are not our guests. Only worth it for a property chasing corporate contracts. |
| **OTA** (online travel agency; the brief calls it IDS, internet distribution): Booking.com, Agoda, MakeMyTrip/Goibibo, Airbnb | Consumer marketplaces: listing, search, reviews, payments | Almost every small property | Commission per booking. **Airbnb (official):** host-only fee mostly 15.5% (typically 14–16%), split-fee 3% being phased out [S3]. **Booking.com:** ~12–15% in India per a 2017 article [S4] (dated, secondary; official partner page refused our fetch). **MakeMyTrip/Goibibo:** hotel associations alleged effective rates of 40–45% in 2019 [S5] (association claim, not a rate card). | **High.** This is where homestay guests come from. |
| **Channel manager** (e.g. STAAH, eZee Centrix) | Pushes rates and availability to many OTAs at once and pulls bookings back, so a room is not sold twice | Properties on more than 2–3 OTAs | Monthly subscription, **quote-based**; STAAH publishes no rate card (it was acquired by Access Group, Dec 2024) [S10] | **Medium.** Useful once a homestay is on several OTAs. |
| **PMS** (property management system), e.g. eZee Absolute (Yanolja Cloud), Hotelogix | Reservations, check-in/out, rates, guest bills, GST invoices, police Form C, often a booking engine and POS [S9] | Hotels; some homestays still use a register or WhatsApp (A) | Subscription by room count and modules. eZee: an aggregator lists **$23.86/month for a 5-room basic PMS**, more with booking engine/channel manager [S7] (aggregator, currency basis UNVERIFIED). Hotelogix: "subscription-based", price on request [S8]. | **Medium–high** for a small hotel; optional for a 2–4 room homestay. |

**Regulatory note (E):** In Oct 2022 the Competition Commission of India fined MakeMyTrip-Goibibo ₹223.48 crore and OYO ₹168.88 crore
and directed MMT-Go to drop price- and room-parity clauses with hotels [S6]. We did not check whether the order was later modified on
appeal (UNVERIFIED). Relevance: small owners have legitimately complained about OTA terms; HOI should never become another intermediary
taking a cut of room revenue.

### 1.2 What this means for HOI

- HOI does **not** sell rooms, set rates or hold bookings. We need only **occupancy actuals and arrivals/departures** from the PMS (or an
  owner typing "rooms sold today" in homestay mode) to forecast and roster.
- Integration order (roadmap): CSV/manual entry (today) → eZee/Hotelogix export import → a PMS API connector if a pilot hotel needs it.

---

## 2. Operating models of the players around small owners

| Model | What it does for a small owner | What it does **not** do (staff ops, retention, on-the-ground service) | Sources |
|---|---|---|---|
| **Zostel / Zo World** | Franchise brand: since ~2015 partners build and run hostels under the Zostel brand via an Entrepreneurship Development Program; Zostel selects partners tightly and provides operational oversight; CEO claims 100+ destinations, marketing <0.5% of revenue, est. ₹120 cr revenue (CEO estimate) [S11]. Wikipedia: franchisee-owned, franchisee-operated, commission **21–30%** on booking and F&B revenue, citing *Fortune India* [S12] (secondary; UNVERIFIED with Zostel). Zo World groups Zostel, Zo Trips, Zo Villas (homestays/vacation homes), Zo Houses [S12][S13]. | Partner terms for **Zostel Homes / Zo Villas** owners are not public (UNVERIFIED). We found nothing public about rostering, task dispatch or retention tools for the partner's own staff. Brand standards ≠ daily shift planning. | [S11][S12][S13] |
| **OYO (PRISM)** | Lists "Patron"-owned hotels and homes on its platform; owner app **Co-OYO** covers bookings, reviews, earnings, payouts, GST sales invoices, pricing suggestions, staff logins with permissions [S14]. Reported shift from minimum-guarantee contracts to revenue share around FY24 [S15] (secondary). | Owner disputes over commissions and terms were widely reported in 2019 [S16] (dated). The app is about **revenue and bookings**; we found no public evidence of forecast-driven rostering, photo-verified housekeeping jobs or retention support. | [S14][S15][S16] |
| **Uttarakhand homestay scheme (state)** | **Official UTDB sheet:** whole state except municipal-corporation areas; owner/leaseholder must live there with family; **1 to 6 rooms**; owner arranges food; registration mandatory [S17]. **Subsidy (Pauri district page, last updated Jan 2020):** hill areas 33% capital subsidy or ₹10 lakh (whichever is lower) + 50% interest subsidy up to ₹1.5 lakh/yr for 5 years; plains 25% or ₹7.5 lakh + up to ₹1 lakh/yr [S18]. Aggregators list higher, newer amounts (50% / ₹15 lakh) — **UNVERIFIED, conflicting**. **Revised rules (ETV Bharat, 20 May 2026, cabinet-approved per the report):** up to **8 rooms / 24 beds**; registration valid 5 years with self-renewal online; operation by owner **or an authorised operator/professional service provider**; new **community-based tourism unit** = 8–10 homestays in a village or cluster of 3–6 villages, legally registered as a society/cooperative/CBO; >5,000 registered homestays, ~1,500 subsidy beneficiaries since 2015 [S19]. Official notification not found (UNVERIFIED). | Money and legal status, not operations: no staff tools, no training on service quality beyond what partners like Airbnb's MoU add [S21]. | [S17][S18][S19][S21] |
| **Trekking Traction Centre homestay grant (state)** | Per aggregators: ₹60,000/room new build, ₹25,000/room repair, max 6 rooms, villages within 2 km of notified trek centres [S37] | Same gap. **Amounts UNVERIFIED** (no official page found). | [S37] |
| **GMVN / KMVN tourist rest houses** | State corporations that develop, maintain and market tourist rest houses (KMVN: "Nainital to Pindari, Darma and Adi Kailash"), run packaged tours, and (KMVN) support local entrepreneurs [S20]. GMVN official booking is listed by third parties at gmvnonline.com (not opened; UNVERIFIED). | They are **operators competing for the same guests**, not a service to private homestays. Their own staff-ops tooling is unknown. KMVN once decided to lease out loss-making rest houses on PPP (dated Tribune report, UNVERIFIED current status). | [S20] |
| **Airbnb × UTDB MoU (17 Jan 2024)** | Workshops for "model hosts" on hosting standards, listings, photos; gap review of pilot destinations shared with UTDB; district tourism officers mobilise hosts [S21] | Demand + listing quality. No staff, roster or retention tooling. Outcomes not published. | [S21] |

**Take-away:** every model above helps a small owner **get guests or money**. None we found helps the owner **run 3–25 people through a
peak season**: who works when, who does which job now, how to cover a shortage, and how to keep good staff. That is HOI's space.

---

## 3. Where HOI fits

### 3.1 Layer diagram

```
  DEMAND / DISTRIBUTION            (we connect to, never replace)
  ┌──────────────────────────────────────────────────────────────┐
  │ GDS (Amadeus/Sabre/Travelport) — not for homestays            │
  │ OTAs: Booking.com · Agoda · MakeMyTrip/Goibibo · Airbnb       │
  │ Brands/aggregators: Zostel · OYO   ·  State: UTDB homestay    │
  └───────────────┬──────────────────────────────────────────────┘
                  │ rates/availability ⇅ bookings
  ┌───────────────▼──────────────────────────────────────────────┐
  │ CHANNEL MANAGER + PMS: eZee · STAAH · Hotelogix · register    │
  │ (reservations, bills, GST invoice, Form C)                   │
  └───────────────┬──────────────────────────────────────────────┘
                  │ occupancy actuals, arrivals/departures (import or typed)
  ┌───────────────▼──────────────────────────────────────────────┐
  │ HOI — OPERATIONS & PEOPLE LAYER                               │
  │ forecast → fair roster → shortage → staffing request          │
  │ live jobs + photo proof · rooms board · stores + GST POs      │
  │ retention support (closed loop) · recognition points          │
  └───────┬──────────────────────────────┬───────────────────────┘
          │ jobs, shifts (Hindi PWA)     │ hiring board, agencies, skilling institutes
  ┌───────▼───────────────┐     ┌────────▼──────────────────────────┐
  │ STAFF ON THE GROUND   │     │ PORTAL: local workforce + local    │
  │ + GUEST ON PREMISES   │◀───▶│ experiences (guides, food, craft)  │
  │ (room QR concierge)   │     │ + verify-a-business for tourists   │
  └───────────────────────┘     └────────────────────────────────────┘
```

### 3.2 Differentiator statement

**One sentence:** HOI is the phone-first, Hindi operations-and-people layer for small hill hotels and homestays: it turns the occupancy
forecast into a fair roster, covers the gaps from local agencies and trained workers, and gets every guest request done with proof,
alongside the PMS and OTAs the owner already uses.

- **Roster → shortage → staffing request in one flow.** Distribution tools stop at the booking; HR tools stop at the record. HOI connects
  forecast, roster, live jobs and the local hiring board. (We found no small-hotel tool in India publicly doing this; that is a search
  result, not proof of absence.)
- **Built for 3–25 staff in a seasonal hill economy:** homestay mode, Char Dham/festival seasonality, seasonal contract dates, GST POs,
  Hindi voice, cheap Android phones.
- **People-first by design:** retention support instead of punishment, recognition instead of surveillance, no sensitive personal data,
  workers never see risk scores.

### 3.3 What we must NOT claim

- That HOI is a PMS, channel manager, booking engine, GDS connector or OTA. It is none of these.
- Any real-world improvement (occupancy, attrition, guest ratings, cost). All numbers come from a **synthetic** hotel; the closed-loop
  effect is simulated and small.
- That the portal is an official Government of Uttarakhand site, or that UTDB/GMVN/KMVN partner with us.
- That Zostel/OYO "have no operations tools" (we say "we found no public evidence of"), or quote their commission figures as fact.
- That recognition points "increase performance by X%": the cited evidence is a field experiment on a data-entry task [S29], not hotels.
- That "AI predicts who will quit". We say "flagged for review, to offer support".
- That subsidy amounts are current: two official/near-official sources disagree (Section 2).

---

## 4. Affordability and practicality for small hotels and homestays

### 4.1 Costs and constraints small owners face

| Cost / constraint | What we know | Type |
|---|---|---|
| OTA commission on every booking | Airbnb host-only fee mostly 15.5% [S3]; Booking.com ~12–15% (2017, secondary) [S4]; MMT disputes [S5][S6] | E |
| Software subscriptions | PMS from ~$24/month for 5 rooms (aggregator listing) [S7]; channel manager and booking engine extra [S7]; most vendors price on request [S8][S10] | E (indicative) |
| Seasonal staffing | Industry reports a skilled-staff shortage and high entry-level attrition [S27][S28][S39]; hotels hesitate to use gig staff because of training and service-quality worries [S25] | E (national, not Uttarakhand-specific) |
| Small scale | Homestays are capped at 6 rooms (8 under the reported 2026 revision) and must be owner-occupied [S17][S19] | E |
| Patchy mobile data in hill areas, shared/low-end Android phones, Hindi-first staff | Plausible, **not measured by us** | A |
| Owners will not pay for a second "big" system on top of a PMS | Plausible | A |

### 4.2 Product choices (what we build and why)

| Choice | Status | Why |
|---|---|---|
| **Homestay mode**: one property, owner is admin, ≤ ~8 staff; hides ML pages (attrition ranking makes no sense for 3 people); keeps rooms board, jobs with photo proof, simple roster, stores, guest QR, experiences | Building this round | A homestay with 3 staff needs "who cleans which room, what to buy", not dashboards |
| **Phone-first PWA**, no app-store install; app shell cached offline by a service worker (API calls still need network) | Built (`/worker/sw.js`) | Works on any phone browser |
| **Offline job queue** (accept/done saved and synced later) | Roadmap | Only the shell is offline today; do not claim offline jobs |
| **Hindi + English, voice input** | Built (staff app); Hindi wording needs native-speaker review | Frontline staff language |
| **Manual occupancy entry** instead of requiring a PMS | Built (CSV/manual) | Homestays often have no PMS (A) |
| **No per-booking fee, ever** | Principle | We are not an intermediary on room revenue |

### 4.3 Pricing — **proposal to validate, not a fact**

| Tier | Who | Proposed price | Reasoning |
|---|---|---|---|
| Homestay (free) | Registered homestay, 1 property, up to ~8 rooms and ~5 staff | ₹0 | Adoption first; registered homestays are the state's priority segment [S19]; costs us little (one small tenant). Portal listing + hiring board free. |
| Small hotel | 1 property, up to ~40 rooms | ~₹999–1,999 / property / month (test both) | Should cost **less than or similar to a small-property PMS** [S7], because we are an add-on. Value test: does covering one peak-week staffing gap or avoiding one stock-out pay for a month? |
| Group | 2+ properties, ML forecast, closed loop, integrations | quote | Same as industry practice [S8] |
| Cluster (community unit) | 8–10 homestays under one society/cooperative [S19] | one shared subscription (proposal) | Shared staff pool and shared experiences; matches the new legal unit |

Validate with willingness-to-pay questions (Section 8) before showing any price to a customer.

---

## 5. Staffing agencies and skill matching

### 5.1 How seasonal hospitality staffing works (what sources say)

- **Shortage and churn (E, national):** FHRAI's Nov 2024 HR summit launched a report estimating a need for 100,000–150,000 additional
  skilled workers a year [S27]; 2025 job-portal data show high entry-level attrition [S28]; HVS (2022) cites long hours, physical work
  and low pay as reasons people avoid the sector [S39].
- **Contract, part-time and gig staff (E):** HVS (13 Nov 2022) notes contract and part-time staff have always been part of hotels;
  suggests housekeeping, F&B service, stewarding and cleaning as gig-suitable roles; slow adoption is due to fear of service quality and
  constant re-training [S25].
- **Indian hospitality staffing platforms exist:** e.g. Shiftz (founded 2023; claims Taj, Ginger, Sarovar as clients, verified
  workers) [S26]; MEND (gig/permanent, "passport" credential) is listed in our earlier competitor scan. These are self-reported.
- **Uttarakhand-specific data (headcount, wages, migration of seasonal workers): not found (UNVERIFIED).** This is a top interview topic.

### 5.2 Skilling programmes (official sources only)

| Programme | Facts | How HOI links |
|---|---|---|
| **Hunar Se Rozgar Tak (HSRT)**, Ministry of Tourism, under Capacity Building for Service Providers | Guidelines (amended 1 Jul 2019): NSQF courses incl. Multi Cuisine Cook, F&B Service Steward, **Room Attendant**, **Front Office Associate**; fresh entrants ≥ 200 hours; **six-day Skill Testing & Certification** for people already working (Food Production, Bakery, F&B Service, Housekeeping Utility); **placement of ≥ 70% of certified trainees within 3 months** is a mandatory outcome, at least minimum wage [S22]. Recent trained/placed figures were reported in a Mar 2026 PIB release (FY24: 24,153 trained / 4,584 placed; FY25: 89,801 / 25,158 provisional) — seen only via search; the PDF would not open for us (**treat as UNVERIFIED**) [S23]. | Institutes need placements; HOI hotels need trained staff. Institute account on the hiring board → post certified batches; hotels' staffing requests reach them. Whether an IHM/FCI in Uttarakhand runs HSRT batches now: **UNVERIFIED**. |
| **Tourism & Hospitality Skill Council (THSC) qualifications** | NQR lists THSC housekeeping qualifications, e.g. Housekeeping Assistant (NSQF 3), Guest Service Associate – Housekeeping (NSQF 4), approved 31 Jan 2024 [S24] | Use QP names as the **skill tags** on hiring-board profiles, so "Room Attendant (NSQF 4)" means the same thing to every hotel. |

### 5.3 Integration design (this round + roadmap)

| Step | What happens | Status |
|---|---|---|
| 1. Roster shortage | The CP-SAT roster already reports exact short shifts when a week is infeasible | Built |
| 2. Staffing request | One click turns those short shifts into a request: role, skill tag, dates, district, language, pay range | Building this round |
| 3. Agency accounts | Registered staffing agencies (and later skilling institutes) get a hiring-board account; they see requests in their district and propose workers | Building this round |
| 4. Skill matching | Existing hiring-board match: skills/experience, district, availability, language only; weights are ASSUMED (`hiring.yaml`); no gender, age, religion, caste, photo | Built (portal) |
| 5. Onboard into roster | Accepted worker gets a temporary staff ID, appears in the roster and the staff app for the contract dates | Roadmap |
| 6. Two-way rating after the stint | Hotel and worker rate each other on punctuality/clarity of work; shown only as aggregate | Roadmap (fairness review first) |

Open legal question for a qualified person: contract labour and gig-worker obligations (wages, social security) when agencies supply
staff. We do not give legal advice in the product.

---

## 6. Incentives for frontline staff

### 6.1 What evidence says

| Finding | Source | Implication |
|---|---|---|
| Unannounced **recognition** raised later performance in a field experiment with 300+ workers; the largest gain came when only the best performers were recognised, driven mainly by non-recipients | Bradler, Dur, Neckermann & Non, *Management Science* 62(11), 2016 [S29] | Public thank-you can work, but the setting was a 3-hour data-entry job, not hotels: we must test it |
| Money incentives can change how people see a task and **crowd out** intrinsic motivation; short-term gains can fade | Gneezy, Meier & Rey-Biel, *JEP* 25(4), 2011 [S30] | Keep cash small, team-based and framed as thanks, not piece-rate |
| **Electronic performance monitoring** showed no performance benefit and was associated with higher stress (meta-analysis, 94 samples, N = 23,461); more transparent, less invasive monitoring went with better attitudes | Ravid et al., *Personnel Psychology*, 2022 [S31] | No location tracking, no idle-time scoring, transparent rules |
| Mandatory service charges were held unlawful (Delhi HC, 2025, upholding CCPA 2022 guidelines); service charge must be voluntary [S33] | [S33] | Do not design incentives funded by a compulsory guest charge; voluntary guest tips must reach staff transparently |

### 6.2 HOI recognition points (building this round)

- **Earned by:** jobs completed with photo proof inside the target time; guest 4–5 star feedback on a request; covering an extra shift
  the roster asked for; finishing a skill certification. Owners can add a "thank you" with a note.
- **Redeemed for (owner decides):** a small monthly bonus, a preferred day off, a meal, a training seat. Proposal, to validate.
- **Shown as:** each worker sees only their own points and a **team** total; "top 3 this month" thank-you (in line with [S29]) but
  **never a bottom list**.

### 6.3 Risks and safeguards

| Risk | Safeguard |
|---|---|
| **Gaming** (rushing jobs, fake "done") | Points only after server-time-stamped live-camera proof; random QA inspection; cap points per day |
| **Unfairness** (some roles/shifts get fewer point-earning jobs) | Points normalised per role and per shift hours; night/kitchen staff earn via shift cover and certification |
| **Favouritism** (owner "thank you" points) | Owner bonuses logged in the audit trail and capped per month |
| **Surveillance creep** | No GPS, no idle time, no keystroke-style metrics; points never feed the attrition model or any adverse decision |
| **Crowding out** [S30] | Small values, team goals, framed as recognition; review after the pilot whether it helps or hurts |
| **Guest-rating bias** | Guest stars count only at request level, never as the only path to points |

---

## 7. Community-driven experiences and local linkages

### 7.1 Examples (India / Uttarakhand)

| Initiative | What it is | Source |
|---|---|---|
| **Sarmoli, Munsiari (Pithoragarh)** | Maati Sangathan women's collective (1994); Himalayan Ark homestay programme since 2004, run by women; ~20 host families and as many families working as guides; village walks, birding, treks, weaving/knitting, food trails; pre-pandemic families earned up to ₹3.75 lakh/yr from hosting (interviewee figures) | Mongabay-India, 21 Jun 2021 [S34] |
| **Village Ways, Binsar–Jageshwar (Almora)** | Social enterprise since 2002–04; community-owned guesthouses in villages (Risal, Gonap, Satri, Dalar, Kathdhara); staff and cooks are local villagers; multi-day village-to-village walks | Operator's own site [S35] (self-reported) |
| **Best Tourism Villages 2024 (Ministry of Tourism)** | Jakhol (adventure), Supi (agri-tourism), Harsil and Gunji (Vibrant Villages) from Uttarakhand among 36 winners; 991 villages entered | Outlook Traveller [S36] (official PIB copy on tourism.gov.in would not open for us) |
| **Community-based tourism unit (state, 2026 revision)** | 8–10 homestays as one registered society/cooperative/CBO; UTDB to invite applications; group grant proposed, guidelines pending | ETV Bharat [S19] |
| **Airbnb × UTDB "model hosts"** | Host training in less-visited destinations | Airbnb newsroom [S21] |

### 7.2 How the portal + HOI link homestays ↔ experiences ↔ workforce

1. **Local experiences listings (building this round):** a registered guide, cook, artisan or village collective lists an experience
   (village walk, pahadi cooking, weaving demo, birding) on the portal with district, language, duration and price set by them.
2. **Guest side:** the homestay's room QR concierge shows "experiences near you" from the portal; a booking request goes to the provider
   (HOI takes no cut in the prototype; any future fee is a proposal to validate).
3. **Workforce side:** the same local people are on the hiring board (with consent), so a homestay short of a cook in peak week can find
   the village cook who also runs a food experience.
4. **Cluster mode (roadmap):** a community-based tourism unit of 8–10 homestays [S19] shares one staff pool, one roster view and one
   experiences calendar; guests can be routed to the next homestay in the cluster when one is full. Fair rotation rules are decided by
   the collective, not by us.
5. **Officials' view (portal):** aggregated, anonymous counts (experiences listed, requests, staffing gaps per district) to show where
   skilling or promotion is needed. Never per person.

---

## 8. Prioritised roadmap and customer validation

### 8.1 Features scored

Need: **E** = some external evidence, **A** = assumption. Advantage: H/M/L versus what owners can already get. Effort: S/M/L for our team.

| Feature | Need | Advantage | Effort | Status |
|---|---|---|---|---|
| Forecast → fair CP-SAT roster with exact short shifts | A (rostering pain for small hotels unvalidated; shortage E [S27]) | H | done | **Built** |
| Live job dispatch with live-camera photo proof | A | M (photo tickets exist in ALICE/Actabl) | done | **Built** |
| Guest room QR concierge (Hindi/English, voice) | A | M (eZee has a guest portal) | done | **Built** |
| Attrition support + closed loop | E for churn [S28]; A for usefulness at small scale | H for hotels; **L for homestays** (hide there) | done | **Built** |
| Stores with forecast-aware reorder and GST POs | A | M | done | **Built** |
| Hindi staff PWA, offline shell | A | M | done | **Built** |
| Portal hiring board with skill matching | E (shortage) | M–H | done | **Built** |
| **Homestay mode** | E (5,000+ registered homestays [S19]); A (they want it) | H (nothing small-and-ops-focused found) | S–M | **This round** |
| **Roster shortage → staffing request** | E (shortage [S27][S39]) | H | M | **This round** |
| **Agency accounts on the hiring board** | E (agencies/platforms exist [S26]) | M | S | **This round** |
| **Worker recognition points** | E (recognition evidence [S29]); A (in hotels) | M | S–M | **This round** |
| **Local experiences listings** | E (community tourism examples, state CBT unit [S19][S34]) | H (links stay + experience + workforce) | M | **This round** |
| Skill tags from THSC qualification names; HSRT institute accounts | E [S22][S24] | M | S | Roadmap |
| PMS import (eZee/Hotelogix export) | A | M (removes double entry) | M | Roadmap |
| Offline job queue | A (connectivity) | M | M | Roadmap |
| WhatsApp/SMS job alerts | A | M | M (cost, templates) | Roadmap |
| Cluster mode for community-based tourism units | E (new legal unit [S19]) | H | L | Roadmap |
| Own booking engine / channel manager / GDS | — | L (crowded, [S7][S10]) | L | **Will not build** |

### 8.2 Customer-validation plan (nothing is validated yet)

**Who (8–10 interviews, 2 weeks, Mussoorie + Rishikesh):** 4 registered homestay owners, 3 small-hotel GMs/owners (10–40 rooms),
3 frontline staff (housekeeping, kitchen, front desk; interviewed separately from their employer, with consent). Find them through the
District Tourism Office list of registered homestays, the GEU hospitality faculty, and walk-ins. Bonus: 1 staffing agency, 1 IHM/FCI
placement officer.

**Eight questions (owners/GMs; adapt for staff):**
1. Walk me through last peak week: what went wrong with staff, rooms or supplies?
2. How do you decide who works which day? Where is that written (paper, WhatsApp, PMS)?
3. When someone doesn't turn up or quits mid-season, what do you do and how long does it take to replace them?
4. Where do your seasonal workers come from (village, agency, contacts)? What does it cost you?
5. What software do you pay for today (PMS, channel manager, OTAs), and how much per month?
6. How do you thank or reward good staff now? What has backfired?
7. Do guests ask you for local experiences (guides, food, crafts)? Who do you send them to?
8. If a phone app fixed [their top problem], what would you pay per month, and what would make you stop using it?

**Success metrics (decide go/no-go before the interviews):**

| Metric | Threshold to continue |
|---|---|
| Staffing/rostering named as a top-3 problem | ≥ 6 of 10 interviewees |
| Owners who currently plan staff on paper/WhatsApp (confirms gap) | ≥ 5 of 7 owners |
| Willing to run a free 2-week pilot on one property | ≥ 2 owners |
| Stated willingness to pay ≥ ₹999/month (small hotels) | ≥ 2 of 3 GMs |
| Staff who say recognition points would feel fair, not like surveillance | ≥ 2 of 3 staff |
| Pilot (later): time to fill a short shift; % jobs closed with proof; staff app weekly active use | baseline vs week 2, report honestly even if no change |

Record answers in a shared sheet; quote people only with consent; no names in the repo (DPDP Act).

---

## Sources (accessed 13 Oct 2026)

| # | Source | Type |
|---|---|---|
| S1 | J. Gough, "What is a Global Distribution System (GDS) in the hospitality industry?", Hospitality Net, 12 Sep 2025 — https://www.hospitalitynet.org/explainer/4128878/what-is-a-global-distribution-system-gds-in-the-hospitality-industry | Industry (vendor-authored) |
| S2 | HotelREZ, "Travelport, Amadeus, or Sabre: Which GDS is right for independent hotels?" — https://hotelrez.com/travelport-amadeus-or-sabre-which-gds-is-right-for-independent-hotels/ | Vendor |
| S3 | Airbnb Help Center, host service fees — https://www.airbnb.com/help/article/1857 | Official |
| S4 | Business Insider India (2017), Booking.com agency model — https://www.businessinsider.in/This-is-why-Booking-coms-agency-model-has-an-edge-over-other-OTAs/articleshow/59102504.cms | News (dated) |
| S5 | Skift, 24 Jan 2019, MakeMyTrip hotel commission protests — https://skift.com/2019/01/24/makemytrip-steams-ahead-despite-growing-hotel-commission-protests/ | News |
| S6 | MediaNama, Oct 2022, CCI order on MMT-Go and OYO — https://www.medianama.com/2022/10/223-cci-mmt-goibibo-oyo-order/ ; Business Today — https://www.businesstoday.in/amp/latest/corporate/story/cci-imposes-rs-39236-cr-fine-on-makemytrip-goibibo-oyo-for-anti-competitive-conduct-350347-2022-10-19 | News on regulator order |
| S7 | Capterra India, eZee Absolute pricing — https://www.capterra.in/software/135751/ezee-absolute | Aggregator |
| S8 | Hotelogix pricing page — https://www.hotelogix.com/pricing/ | Vendor |
| S9 | Our `docs/COMPETITORS.md` (eZee India page, checked 13 Oct 2026) | Internal |
| S10 | Hotel Tech Report, STAAH — https://hoteltechreport.com/company/staah-channel-manager | Review site |
| S11 | Storyboard18, 1 Mar 2026, interview with Zostel CEO — https://www.storyboard18.com/brand-makers/we-spoke-to-zostels-ceo-on-scale-profitability-and-the-future-of-indias-travel-economy-90927.htm | News (CEO claims) |
| S12 | Wikipedia, "Zostel" (cites Fortune India for commission) — https://en.wikipedia.org/wiki/Zostel | Secondary |
| S13 | Skift, 4 Feb 2026, Zo World CEO on IPO plans — https://skift.com/2026/02/04/indian-hostel-chain-zo-world-ceo-on-ipo-plans-and-expansion/ | News (paywalled, partial) |
| S14 | Co-OYO, Apple App Store listing — https://apps.apple.com/us/app/-/id1424149517 | Vendor listing |
| S15 | Sacra, OYO — https://sacra.com/c/oyo-rooms | Secondary research |
| S16 | The News Minute (2019), hotel owners vs OYO — https://www.thenewsminute.com/article/why-many-hotel-owners-across-india-are-agitated-oyos-business-model-106154 | News (dated) |
| S17 | UTDB, homestay eligibility criteria (PDF) — https://hsapi.uttarakhandtourism.gov.in/pdfs/generated_pdf_6700e56869596.pdf | Official |
| S18 | Pauri Garhwal district, Tourism Department (last updated 7 Jan 2020) — https://pauri.nic.in/tourism-department/ | Official (dated) |
| S19 | ETV Bharat, 20 May 2026, "Uttarakhand Homestay Scheme Revised" — https://www.etvbharat.com/en/state/uttarakhand-homestay-scheme-revised-community-tourism-promoted-for-the-first-time-enn26052005510 | News (official notification not found) |
| S20 | KMVN, About us — https://www.kmvn.in/about-us | Official |
| S21 | Airbnb Newsroom, 17 Jan 2024, MoU with UTDB — https://news.airbnb.com/en-in/airbnb-signs-an-mou-with-uttarakhand-tourism-development-board/ | Company press release |
| S22 | Ministry of Tourism, Amended HSRT guidelines (1 Jul 2019), hosted by Odisha Tourism — https://dot.odisha.gov.in/sites/default/files/2022-06/AMENDED_HSRT_GUIDELINES_01-07-19_converted.pdf | Official |
| S23 | Ministry of Tourism, "Schemes for promotion of tourism" (PIB, Mar 2026) — https://tourism.gov.in/sites/default/files/2026-03/SCHEMES%20FOR%20PROMOTION%20OF%20TOURISM.pdf | Official, **not opened by us** (403/404); figures from search summary |
| S24 | National Qualifications Register, THSC housekeeping qualification files — https://www.nqr.gov.in/qualification/file/QFile_%20Housekeeping%20Assistant%20ENGLISH.pdf ; https://www.nqr.gov.in/qualification/file/QFile_Guest%20Service%20Associate%20%28Housekeeping%29%20ENG.pdf | Official |
| S25 | HVS, 13 Nov 2022, "Can Gig Workers Help the Indian Hotel Industry Fill its Talent Gap?" — https://www.hvs.com/Print/HVS-Monday-Musings-Can-Gig-Workers-Help-the-Indian-Hotel-Industry-Fill-its-Talent-Gap?id=9496 | Industry |
| S26 | Outlook Business, Shiftz hospitality staffing — https://www.outlookbusiness.com/corporate/former-itc-director-nakul-anand-invests-in-hospitality-staffing-platform-shiftz | News (company claims) |
| S27 | BW Hotelier, FHRAI HR Summit (Nov 2024) — https://bwhotelier.com/article/fhrai-successfully-concludes-hr-summit-on-education-and-career-in-hospitality-539316 | Trade news |
| S28 | Deccan Chronicle (2025), hospitality attrition — https://deccanchronicle.com/business/hospitality-sees-high-attrition-levels-amidst-hiring-1899652 | News |
| S29 | Bradler, Dur, Neckermann & Non (2016), "Employee Recognition and Performance: A Field Experiment", *Management Science* 62(11):3085–3099, doi:10.1287/mnsc.2015.2291 — https://cris.maastrichtuniversity.nl/en/publications/employee-recognition-and-performance-a-field-experiment/ | Peer-reviewed |
| S30 | Gneezy, Meier & Rey-Biel (2011), "When and Why Incentives (Don't) Work to Modify Behavior", *JEP* 25(4):191–210, doi:10.1257/jep.25.4.191 — https://ideas.repec.org/a/aea/jecper/v25y2011i4p191-210.html | Peer-reviewed |
| S31 | Ravid et al. (2022), meta-analysis of electronic performance monitoring, *Personnel Psychology*, doi:10.1111/peps.12514 — https://www.microsoft.com/en-us/research/publication/a-meta-analysis-of-the-effects-of-digital-surveillance-of-workers-a-psychology-focused-approach/ | Peer-reviewed |
| S33 | Business Standard, Mar 2025, Delhi HC on mandatory service charges — https://www.business-standard.com/india-news/delhi-hc-bans-mandatory-service-charges-calls-it-unfair-trade-practice-125032800820_1.html | News on court ruling |
| S34 | A. Singh, Mongabay-India, 21 Jun 2021, "How Sarmoli became a poster child of ecotourism in Uttarakhand" — https://india.mongabay.com/2021/06/how-sarmoli-became-a-poster-child-of-ecotourism-in-uttarakhand/ | News |
| S35 | Village Ways, about the area — https://villageways.com/about-the-area-binsar-and-saryu/ | Operator (self-reported) |
| S36 | Outlook Traveller, Best Tourism Villages 2024 (Uttarakhand) — https://www.outlooktraveller.com/whats-new/these-4-uttarakhand-villages-just-got-selected-for-best-tourism-village-awards ; official PIB copy: https://tourism.gov.in/sites/default/files/2024-09/PIB2059419.pdf (not opened) | News / official |
| S37 | Youth Power scheme listing, Trekking Traction Centre Home-stay Grant — https://youthpower.in/scheme/ttchsuk | Aggregator (UNVERIFIED) |
| S39 | HVS (Feb 2022), "Indian Hospitality Sector Skill Shortage to Hinder Recovery and Growth" — https://www.hvs.com/Print/HVS-Monday-Musings-Indian-Hospitality-Sector-Skill-Shortage-to-Hinder-Recovery-and-Growth?id=9274 | Industry |

(S32 and S38 intentionally unused: we could not obtain a primary link.)

### Could not verify (do before quoting)

- Booking.com and Agoda current India commission (official partner pages blocked our fetch); GDS fee schedules.
- eZee, STAAH, Hotelogix current INR prices (quote-based; aggregator figures only).
- Zostel commission (21–30%) and Zostel Homes / Zo Villas owner terms; OYO current partner terms in India.
- Current DDU homestay subsidy amounts (33%/₹10 lakh on a 2020 district page vs 50%/₹15 lakh on aggregators); the official notification
  of the May 2026 revision (8 rooms / 24 beds, community-based tourism unit); Trekking Traction Centre grant amounts.
- HSRT FY24–FY26 trained/placed figures (PIB PDF did not open); whether Uttarakhand IHMs/FCIs run HSRT batches now.
- GMVN/KMVN rest-house counts; any Uttarakhand-specific data on seasonal hospitality workers (none found).
- Whether the 2022 CCI order was modified on appeal; whether the 2025 Delhi HC service-charge ruling was appealed.
