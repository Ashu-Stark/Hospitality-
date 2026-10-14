# HOI: Hospitality Operations Intelligence. Full project context

**For:** anyone who needs the whole picture: the team, mentors, judges' Q&A preparation, and future contributors.
**State as of:** 14 Oct 2026 (AI-Tourism Hackathon 2026, TBI-GEU, Team Innov8).
**Honesty rule used in this document:** "built" means it exists in code and runs on the live deployment. "Tested" says on what data.
"Assumed" or "to validate" means it is our belief, not yet proven with a real hotel. All hotel, staff and business data in the demo
is made up (synthetic) and labelled "(demo)".

---

## Contents

1. [What HOI is, in one minute](#1-what-hoi-is-in-one-minute)
2. [The problem and why we chose it](#2-the-problem-and-why-we-chose-it)
3. [Who it is for: customer vs users](#3-who-it-is-for-customer-vs-users)
4. [Design principles (the thinking behind every screen)](#4-design-principles-the-thinking-behind-every-screen)
5. [System architecture](#5-system-architecture)
6. [The five apps, feature by feature](#6-the-five-apps-feature-by-feature)
7. [The engines behind the apps](#7-the-engines-behind-the-apps)
8. [AI and ML: what the models do and how good they are](#8-ai-and-ml-what-the-models-do-and-how-good-they-are)
9. [The state data layer (government integration)](#9-the-state-data-layer-government-integration)
10. [Privacy, security and trust](#10-privacy-security-and-trust)
11. [Key decisions and trade-offs](#11-key-decisions-and-trade-offs)
12. [Quality: tests and live QA](#12-quality-tests-and-live-qa)
13. [Deployment, accounts and how to demo](#13-deployment-accounts-and-how-to-demo)
14. [Pitch, deck and video](#14-pitch-deck-and-video)
15. [Known limits and what's next](#15-known-limits-and-whats-next)
16. [Where things are in the repo](#16-where-things-are-in-the-repo)

---

## 1. What HOI is, in one minute

HOI is one system with **five simple apps** that helps small hotels and homestays in Uttarakhand **see the rush coming, run every day
smoothly and keep good staff**:

| App | Who uses it | One-line job |
|---|---|---|
| **Hotel portal** | Owner / GM, department heads, HR, storekeeper | "Is today OK?" Forecast, shift plan, jobs, rooms, stock, people, work log |
| **Staff app** (phone, web link) | Housekeeping, front office, kitchen, maintenance, security | One job, one button, Hindi voice, photo proof where needed |
| **Guest page** (room QR) | Guests | Ask for anything by tap or voice; nearby places on the map |
| **Uttarakhand Travel Guide** | Tourists, businesses, job seekers, agencies, district and state officials | Destinations, crowds, roads, verified stays, local experiences, jobs, officials' analytics |
| **HOI console** | The HOI team | Add hotels, plans, insights, activity log |

They share one loop: **Predict → Plan → Act → Prove → Care.** The rush forecast drives the shift plan, the shift plan decides who
gets each job, jobs are proven with photos and times, and the results flag who may need a conversation. That feeds the next plan.

Tagline: **Smarter hotels. Happier teams.** Positioning: **Booking tools sell the room. HOI runs the stay.**

---

## 2. The problem and why we chose it

**Problem in one line:** small hotels can't see the rush coming, so peaks are short-staffed, good people burn out and leave, and
guests wait.

Evidence (sources are on the deck slides and in `docs/MARKET_AND_DIFFERENTIATION.md`):

- **Worker shortage:** India's hospitality sector was projected to be short of about 1.1 million workers in 2025 (HVS, Ministry of Tourism study).
- **Quit rate:** accommodation and food workers quit about 1.8× as often as all industries (US BLS JOLTS, used as a proxy).
- **Char Dham crowds:** a record 51 lakh pilgrims in 2025, about 65% of them by 24 June (All India Radio, The Week). The rush comes early and hard.
- **Homestays:** Uttarakhand has 5,000+ registered homestays, mostly family-run (state figures reported by ETV Bharat, May 2026).

**Our hypothesis (to validate):** small properties plan staff by memory, paper or WhatsApp, track guest requests by phone calls,
and notice someone is leaving only when they've left.

**Why this problem:** it is real, local and seasonal, so prediction has visible value. It touches people (staff, guests) more than
bookings, which booking software ignores. And it connects naturally to the state's tourism goals: crowds, verified stays and jobs.

---

## 3. Who it is for: customer vs users

| | Who | Can they buy it for themselves? |
|---|---|---|
| **Customer (pays)** | Hotel and homestay owners. Later: homestay clusters and the state tourism department (to validate). | **Yes.** An owner buys it for their own property. |
| **Users (free)** | Managers, department heads, frontline staff, guests, tourists, district and state officials, job seekers, staffing agencies | **No.** So it must be free for them, work on any phone through a link, speak Hindi, and need no training. |

**Everyone involved, and what they need:**
- **Owner or GM:** is today OK; no peak surprises; keep good staff.
- **Department heads:** their own team's jobs and people.
- **Frontline staff:** clear jobs, fair shifts, recognition.
- **Guests:** help without calling.
- **Tourists:** where to go, how busy it is, safe stays.
- **Officials:** registrations, complaints, crowd warnings.
- **Job seekers and agencies:** seasonal work that fits.
- **The HOI team:** run many hotels safely.

---

## 4. Design principles (the thinking behind every screen)

These came from repeated user feedback during the build ("too complex", "terms not understandable", "layout shift too much").

1. **Answer first.** Every page opens with one plain sentence that answers its question (e.g. "Mostly fine. Look at: guest requests, low supplies."), then 3–5 big numbers, each with one button. Technical detail lives behind "Details".
2. **Everyday words.** No MAPE, ROC-AUC, CP-SAT, SLA or "dispatch" on screens. Say "Rooms likely full tomorrow: 21 of 24".
3. **One job, one button.** The staff app shows the current job with one big next step (Accept → Start → Done) and short rows for the rest.
4. **Voice and Hindi first.** Staff and guests can speak in Hindi, English or Hinglish. The assistant uses feminine first-person Hindi forms (a soft female Indian voice was a user requirement).
5. **No layout shift.** Space is reserved for every image and loading placeholder; measured CLS < 0.05 at 390 px and 1440 px.
6. **Images lead.** Licensed Wikimedia Commons photos (credited on a Photo credits page), photo-led cards.
7. **Honest by default.** Demo data is labelled; estimates say so in small print; claims we can't back are not shown.
8. **Works on any phone.** Web links (PWA for staff), no app store, a "Waking up the server…" message instead of a frozen screen on free hosting.

---

## 5. System architecture

### 5.1 Monorepo map (`C:\Users\ashut\Downloads\INNOV8`)

| Folder | What it is | Tech | Database (MongoDB Atlas) |
|---|---|---|---|
| `ml/` | Synthetic data generator, models, evaluation, real-data validation | Python, LightGBM, scikit-learn, XGBoost (GPU), TimesFM trial | none (files in `ml/data`, `ml/artifacts`) |
| `backend/` | **Ops/ML API** ("hoi-ops"): forecast, attrition, CP-SAT roster, tasks, closed loop, retention plan, voice onboarding | FastAPI, OR-Tools CP-SAT, APScheduler | `hoi_ops` |
| `platform_api/` | **Platform API**: accounts, tenants, jobs (dispatch), rooms, photos, inventory and GST, concierge, voice, recognition, staffing, work log; serves the staff app and guest page | FastAPI, vanilla JS PWA | `hoi_platform` |
| `portal/` | **Uttarakhand Travel Guide** (tourism and hospitality portal) | FastAPI + vanilla-JS SPA, strict CSP | `hoi_portal` |
| `dashboard/` | **Hotel portal** (`ADMIN_PORTAL=hotel`) and **HOI console** (`ADMIN_PORTAL=super`) | Streamlit 1.65 | none (calls the APIs) |
| `website/site/` | Static marketing site | HTML/CSS | none |
| `scripts/` | Scenario simulator, demo model run, wake script, Mongo tools | Python | |
| `docs/` | All documentation, pitch, deck, scripts | Markdown, PPTX | |

Tests run offline on **mongomock**; one root venv (`.venv`, Python 3.12).

### 5.2 How the pieces talk

- **Staff app and guest page → Platform API** (JWT for staff; a per-room guest token for guests).
- **Hotel portal and console → Platform API** (accounts, jobs, rooms, stock, people) **and → Ops API** (forecast, roster, attrition, tasks), with the ops key header `X-HOI-Key`.
- **Platform API → Travel guide** (with the hotel's portal API key `X-API-Key`):
  - staffing requests: `POST /api/v1/ingest/staffing-request`;
  - candidate matches: `GET /api/v1/ingest/candidate-matches`;
  - occupancy feed: `POST /api/v1/ingest/occupancy`.
- **Travel guide → external data:**
  - Open-Meteo (weather);
  - BestTime (place busyness, cached 7 days);
  - LocationIQ (places and geocoding);
  - TomTom (live traffic incidents, optional);
  - its own traffic prediction model.
- **AI providers:**
  - Groq LLM (`openai/gpt-oss-20b`) and Groq Whisper (speech-to-text), with backup keys; failover happens only on 401/403/5xx, never on 429 rate limits;
  - optional local faster-whisper;
  - browser speech synthesis picks a soft female hi-IN or en-IN voice;
  - Sarvam TTS optional.

### 5.3 Deployment

| Service | Host | URL |
|---|---|---|
| Ops/ML API | Render (Singapore, free) | https://hoi-ops.onrender.com |
| Platform API + staff app + guest page | Render | https://hoi-platform-api.onrender.com (staff app at `/worker/`) |
| Hotel portal | Render | https://hoi-dashboard.onrender.com |
| HOI console | Render | https://hoi-platform-admin.onrender.com |
| Travel guide | Vercel | https://hoi-portal.vercel.app |
| Marketing site | Vercel | https://hoi-website.vercel.app |

- **Code layout:** the monorepo is `Ashu-Stark/Hospitality-`. Each service also has its own repo (`hoi-ops`, `hoi-platform`, `hoi-dashboard`, `hoi-portal`, `hoi-website`), synced from the monorepo, and the hosts auto-deploy on push.
- **Secrets:** they live in the root `.env` (gitignored) and in each host's environment settings, and are never committed.
- **Free-tier sleep:** Render's free services sleep after about 15 minutes idle, so run `python scripts/wake_demo.py` before any demo.

---

## 6. The five apps, feature by feature

### 6.1 Hotel portal (owner, managers): `dashboard/`

Navigation has five sections: **Today · People · Rooms & guests · Stock · Settings**, plus an English/हिंदी switch.

| Page | What it does | Why |
|---|---|---|
| **Today** | Answer line + 5 tiles (rooms with guests, rooms to clean, staff on shift vs needed, guest requests waiting, supplies low), each with one button; "Also needs you" in plain sentences with waiting time; red alert when a team has waiting jobs but nobody on shift | The owner should know in 5 seconds whether today is OK |
| **Jobs** | Send a job; live list (refreshes every 2 s); "Nobody took it" → send again or pick someone; practice clock ("use this day and shift") that expires at shift end | See and steer work in real time |
| **Tasks** | Follow-up tasks from the closed loop: late / not seen / being done / done | Make sure check-ins and fixes happen |
| **Week numbers** | Busiest day ("Saturday, about 21 of 24 rooms"), simple bars, shift slots short, overtime; details behind an expander | Plan ahead in plain words |
| **Shift plan** | CP-SAT roster from the forecast, keeping rest rules and fairness; "biggest gaps" cards with Request staff; published only when a manager makes the plan | Fair shifts in minutes, not Saturday nights |
| **Extra staff** | Ask staffing agencies on the travel guide for extra hands (department, skill, dates, count; no personal data); "Sent" / "Still not sent: reason" feedback | Fill peak gaps fast |
| **May leave soon?** | Groups: check in this week / keep an eye on / doing fine; reasons in plain words; "Plan check-ins"; pay reasons visible only to owner and HR; department heads see only their team | Talk before good people leave |
| **Employee detail** | Reasons as cards, talking points, "We talked" log | A prompt to talk, never a verdict |
| **Leaving-risk actions** | Low/moderate: talking points; high: "Look on the job portal" (anonymised matches) or "Post the job" in one click | Line up cover before a gap |
| **Try a change** | What-if simulator (e.g. fewer late shifts) | See the effect before acting |
| **Support plan** | Closed-loop interventions and outcomes | Close the loop |
| **Thank-you points** | Recognition from jobs done well and proven | Positive reinforcement |
| **Work log** | Jobs done, average minutes, jobs with photo proof, longest wait; per-person table; each job as a sentence with before/after photos; CSV export | Time tracking and proof of work |
| **Staff on shift** | Who is working now and how busy | Live view |
| **Rooms & guests** | Room board: occupied → checkout → cleaning → inspection → ready; guest QR links; late checkouts | The room cycle |
| **Guest requests** | Everything guests asked for, with status | Nothing gets lost |
| **Stock** | Low items, requests from staff (plain titles), give from the right store, purchase orders, GST invoices | Never run out |
| **Hotel profile** | What the guest assistant knows (Wi-Fi, meals, checkout time, nearby) | One source of truth for guests |
| **Settings** | Photos staff must take (per job type); portal API key; plan; invites | Each hotel sets its rules |
| **Setup by voice** | Owner answers guided questions (Hindi/English, voice or typed); draft saved only after Confirm; legal values need explicit acknowledgement | Onboarding without forms |
| **Homestay mode** | A simpler version for 1–8 rooms (Today, rooms, guest requests, staff, stock) | Fit for a family-run homestay |

### 6.2 HOI console: `dashboard/` with `ADMIN_PORTAL=super`
- **Home:** an answer line and recent activity.
- **Hotels:** add a hotel, choose plan modules, and "Open in hotel portal" (audited impersonation with a banner and Exit).
- **Insights:** across hotels; empty tiles are hidden.
- **Activity log:** plain words, searchable.

### 6.3 Staff app: `platform_api/hoi_platform/static/worker/`
- **Sign in** with staff ID and PIN. The demo button appears only when demo login is on.
- **Header:** ID, department and an "On shift / Off shift" chip from the live roster. The Today card agrees with it.
- **Jobs:**
  - A **new job** arrives with a time bar → Accept or "Can't now". If not accepted in time (30 s at hotels, 15 min at homestays), it moves to the next person.
  - The **current job** has one big next step: Start → Done.
  - **Photo proof** is needed only for cleaning, repair, pest, damage and lost-and-found (each hotel can change this). Other jobs are one tap. "Add photo" is always available as a small button.
  - **Off shift:** "You're off shift now… Your next shift: Wed · Morning."
- **Speak (voice assistant):**
  - Hindi, English and Hinglish: "Room 204 ka geyser kaam nahi kar raha" becomes a maintenance task.
  - Commands: "what's next", accept, start, done, my shift, report a problem, and **supplies** ("I need 2 bottles of water for room 205").
  - Every action goes through a confirm card.
- **Supplies:** request items; the storekeeper sees the queue.
- **Me:** "My work today" (finished jobs, minutes, photo), thank-you points, language, voice choice, and a privacy note ("your manager cannot see anything on your phone").
- **Reliability:** works offline-first as a PWA, shows times in IST, shows "Waking up the server…" with one safe retry.

### 6.4 Guest page (room QR): `platform_api/hoi_platform/static/guest/`
- **Opening:** the hotel's photo and welcome, then "Ask us · Ready to help" and six big buttons: Towels, Room cleaning, Wi-Fi, Food, Places nearby, Problem in room.
- **Requests:** tap or speak, Confirm ("हाँ, भेज दो"), then live status (received → on the way → done).
- **Problems:** an issue taxonomy covers rats, AC, hot water, leaks, locks, noise, Wi-Fi, safety and medical help. Urgent ones get a short window and urgent routing. "Rat in the room" in Hindi works; it was a fixed bug.
- **Places nearby:**
  - fetched from the travel guide for the hotel's district, so any Uttarakhand hotel works with no setup;
  - "hidden places" questions return quieter spots, or an honest "none found";
  - cards with Open in Maps.
- **Voice:** a Stop speaking button and a Voice on/off switch, plus the voice choice in the speaker menu.
- **Stay:** express checkout and late checkout (the later one cancels the other), feedback, Hotel info, My requests.
- **AI guard:** the assistant answers facts from the hotel profile, and the LLM's numbers are checked against it. Breakfast times must match the profile's breakfast line.

### 6.5 Uttarakhand Travel Guide: `portal/`
**Public:**
- **Home:**
  - photo hero "Your hills, one tap away", with tabs (Places · Stays · Experiences · Trips · Jobs) and a search bar;
  - 8 quick actions;
  - tall destination cards (Kedarnath, Rishikesh, Nainital, Mussoorie, Auli);
  - the Char Dham banner and local-host cards;
  - a "List your property, free" band and a full footer.
- **Destinations (24):**
  - a filter panel and a month strip showing the usual busy level;
  - each destination page has weather (Open-Meteo), "how busy today" (crowd model + BestTime), roads (traffic prediction + live incidents), busy seasons, a Plan your visit card, stays, nearby, festivals and help.
- **Stays:** registered hotels and homestays; check a registration number; find a business.
- **Experiences:** 42 local experiences (home meals, village walks, crafts…) run by verified hosts; "Ask to join" (no payment; only the host sees contact details).
- **Trips, festivals, travel words** (dictionary), **help and complaints**, **helplines**, **photo credits**. Hindi toggle; text size.
- **Jobs:**
  - job seekers;
  - staffing agencies (8, with 17 block offers);
  - urgent requests from hotels.

**Business side (signed in):**
- applications and registration (UK-HTL-… numbers);
- API keys;
- occupancy data;
- the host experiences dashboard and join requests;
- hiring;
- the agency dashboard (offers, notifications, respond).

**Officials (state admin, district officer):**
- a side menu: Numbers (analytics), Applications, Complaints, Road alerts, Events, Businesses, Officers, Audit log;
- analytics tabs: overview, how busy, how full, visitors, complaints, hotel staff, jobs and workers;
- a "Demo numbers" chip.

**APIs for hotels:**
- `POST /ingest/occupancy`, `POST /ingest/staffing-request` (idempotent by `external_id`) and `GET /ingest/candidate-matches` (anonymised codes, skills, availability; never names or contacts);
- all with the business API key.

### 6.6 Marketing site: `website/site/`
A static site that explains HOI.

---

## 7. The engines behind the apps

### 7.1 Live shift context (who is on shift)
- Who is on shift comes from the **published roster plus the IST clock** (`platform_api/hoi_platform/services/shifts.py`).
- **Shift windows (assumed):** morning 06–15, evening 14–23, night 22–07. In the overlaps, both teams count as on shift. After midnight, the night shift belongs to the previous date.
- **Demo roster:** it is set in a 2029 synthetic week, so today maps to the same weekday of that week.
- **Practice override:** for demos it lasts until the end of the current shift; "Back to the live shift plan" clears it.
- **Why:** before this, the on-shift list was a stale snapshot. Jobs found nobody, and staff showed "Off shift" all day.

### 7.2 Dispatch (automatic job assignment)
- Every new job (guest request, checkout cleaning, owner job, voice report) is **offered automatically** to the best person who is on shift and in the right department (`services/dispatch.py`).
- **Ranking:** fewer open jobs, fair share of jobs done this shift, nearest floor, and "go easy" on people flagged as tired or at risk.
- **Offers:** an offer has a time window. On timeout or decline it moves to the next person. If nobody takes it, the job is "Nobody took it" and the owner sends it again or picks someone.
- **Safety:** optimistic concurrency stops two people grabbing the same job. Duplicate open jobs for the same room and issue within 10 minutes return the first one, and jobs for rooms that don't exist are refused.
- **Proof and time stamps:** every job records created, accepted, started and done times, and photos per the photo-proof rules. These feed the Work log.

### 7.3 Room cycle
Checkout (desk or the guest's express checkout) → a **cleaning job is created automatically** → before/after photos → inspection → pass: **Ready**; fail: a re-clean job.

### 7.4 Roster (Ops API)
A **CP-SAT** solver (OR-Tools) builds the week from the forecast: coverage per department and shift, rest-hour rules, weekly off, fairness, and relief for flagged staff. Rosters are cached in MongoDB so Render's sleep doesn't lose them.

### 7.5 Closed loop and retention
Attrition scoring → bands (low / watch / high) → tasks and talking points → "We talked" logged as an intervention → rescore → relief in the next roster. For high risk: anonymised candidate matches from the travel guide, or the job posted in one click.

### 7.6 Concierge (guest assistant)
Rule-based intents and an issue taxonomy (`guest_issues.yaml`) first, the LLM only when allowed, and a fact guard against the hotel profile. Places come from the travel guide (cached 24 h). Replies are feminine-voice Hindi or English.

### 7.7 Voice
- **Speech-to-text:** Groq Whisper, with Hindi number normalisation.
- **Intents:** rule-based first, LLM fallback.
- **Speech:** the browser's own voices (soft female hi-IN / en-IN) or Sarvam.
- **Safety:** every voice action needs a confirm tap.

### 7.8 Inventory
Items per store, staff requests, issuing from the location with stock, purchase orders and GST invoices, and low-stock alerts.

### 7.9 Recognition
Thank-you points from proven, well-done jobs, shown only to the person (positive only). There's an optional leaderboard per hotel.

---

## 8. AI and ML: what the models do and how good they are

| Model | What it predicts | Real-data result | Demo-hotel (synthetic) result |
|---|---|---|---|
| **Occupancy forecast** (LightGBM / XGBoost-GPU, booking-aware features) | Rooms full 1–30 days ahead | Public **Hotel Booking Demand** dataset (2 Portuguese hotels, test Mar–Aug 2017): 1 day ahead off by **1.9 rooms vs 10.9** for "same day last week" (**−83%**; about 1% average error); 7 days: 5.3 vs 10.9 (**−51%**); 30 days: 7.2 vs 18.5 (**−61%**) | 1 day: 6.7% error vs 13.7% baseline; 80% range contained the truth 85% of the time |
| **Attrition (who may leave)** (logistic regression / LightGBM) | Chance of leaving soon, with reasons | IBM HR (fictional): ROC-AUC **0.83** vs 0.65 checklist; Babushkin (described as real, 1,129 people): **0.66** vs 0.55 | 0.69 vs 0.54; about 1 in 7 flagged actually left, so it's used as a prompt to talk |
| **Workload** | How busy each team will be | none | Error 0.053 vs 0.073 (−27%) |
| **Pulse (mood)** | Staff mood signal | none | 0.250 vs 0.257 (hardly better; not used in the pitch) |

- **Fairness and privacy in training:** age, gender, marital status, the boss's gender and personality scores were removed from the real datasets. The synthetic generator's hidden traits (`ml/data/internal/`) are never used for training.
- **GPU:** models were trained on an RTX 4050. TimesFM 2.5 fine-tuning was tried and didn't beat the booking-aware model.
- **Details:** `docs/REAL_DATA_RESULTS.md`, `ml/artifacts/*/metrics.json`, `ml/CLAUDE.md`.
- **Honest limit:** nothing has been tested on a real Uttarakhand hotel yet.

---

## 9. The state data layer (government integration)

The travel guide doubles as **one anonymised dataset for Uttarakhand tourism** that the state can use, and it can plug into the
government tourism portal. That integration is a proposal to discuss with the department.

- **Live today:**
  - crowd forecast per destination;
  - hotel capacity and occupancy (a daily feed from hotels that opt in);
  - registrations and approvals;
  - complaints and response times;
  - seasonal jobs and staffing demand;
  - road alerts.
- **Next (not built):**
  - **money flow**: tourism revenue by district from hotels that opt in;
  - open anonymised data for planners and researchers.
- **Privacy:** businesses opt in, and small groups are hidden (k-anonymity), so no single business can be identified.

---

## 10. Privacy, security and trust

- **No personal attributes, anywhere:** staff are **IDs and roles only**. No names, age, gender, religion, caste, health or family status, and none are used as features.
- **Pay reasons** (e.g. "paid less than others") are visible only to owner and HR. Department heads see only their department.
- **Synthetic data** is labelled everywhere. Demo names carry "(demo)".
- **Authentication:**
  - platform: JWT with refresh tokens; roles: owner, HR, department head, storekeeper, worker, platform admin;
  - travel guide: its own accounts plus a business API key;
  - **ops API: shared key `X-HOI-Key`** (fixed after live QA found it open).
- **Login safety:**
  - rate limits;
  - lockout after failed logins;
  - constant-time comparisons;
  - "burn time" for unknown users.
- **Free AI tiers:** no real names, salaries or staff data are sent to free AI services. Voice onboarding's LLM and cloud speech run only with a config flag and the owner's consent.
- **Secrets:** only in `.env` (gitignored) and the hosts' settings.
- **Demo passwords:** all demo accounts use `123456` (demo only). Change them, and rotate keys shared in chat, before real use.
- **Strict CSP** on the travel guide and guest pages (no inline scripts or styles).

---

## 11. Key decisions and trade-offs

| Decision | Why | Trade-off |
|---|---|---|
| Web apps (PWA), not native | Any phone, no app store, instant updates | No push notifications in the background on some phones |
| Streamlit for the owner portal | Fast to build data-heavy pages | Full reloads on click; a JS rebuild is a later step |
| MongoDB Atlas for everything | One store, flexible documents, free tier | No cross-document transactions (handled with conditional updates) |
| CP-SAT for rosters | Hard rules (rest hours) must never break | Needs good inputs; shift windows are assumed |
| Rules first, LLM second | Predictable, cheap, works with no keys | Less flexible phrasing; LLM output is fact-checked |
| Photos only where proof matters | Towel runs don't need a camera | Hotels must set rules (sensible defaults provided) |
| Offer window 30 s (hotel), 15 min (homestay) | Speed in hotels; family teams can't answer in 30 s | Assumed values |
| Attrition as "talk to them" | Model accuracy is modest; avoid blame | Less automation by design |
| Separate repos per service | Each host deploys only its part | A sync step from the monorepo |
| No booking commission, no pricing in the pitch | Trust; we are not a middleman | Pricing still to validate with owners |

---

## 12. Quality: tests and live QA

**Automated tests (all passing, 14 Oct 2026):**

| Suite | Tests |
|---|---|
| Platform API | 318 |
| Ops/ML backend | 175 |
| Travel guide | 108 |
| Scenario simulator (24-room hotel day, roster stress) | 9 |
| Dashboard smoke (hotel / console) | 84 / 20 |
| Dashboard unit | 6 |
| **Total** | **720** |

ML has its own tests in `ml/tests/`.

**Live QA (14 Oct, real deployments):**
- **Hotel side:** 242 checks: 221 pass, 19 fail, 2 skipped or info only. All 19 failures were fixed and deployed the same day. The ops key was verified live: no key → 401, key → 200, and the dashboard still works.
- **Working end to end live:**
  - checkout → cleaning → photos → inspection → ready;
  - owner job → on-shift staff in **4.4 s**;
  - guest towels, Hindi rat report, places with maps, Stop speaking, feedback, express/late checkout;
  - console; pay privacy; 191 role checks; Work log.
- **Travel guide:** a separate test pass ran in parallel. Its early failures were mostly test steps that needed updating after the redesign.

**Usability:** a 5-person test kit is ready (`docs/USABILITY_TEST.md`). It has not been run with real people yet.

---

## 13. Deployment, accounts and how to demo

1. **Wake the servers.** Run `python scripts/wake_demo.py` 2–3 minutes before the demo. Free hosting sleeps.
2. **Accounts:** all are in `credentials.local.md` (gitignored), and every password is `123456`.
   - **Hotel portal:**
     - `himsagar.owner`, `himsagar.hr`, `himsagar.housekeeping`, `himsagar.frontoffice`, `himsagar.store`;
     - `deodar.owner` (homestay).
   - **Staff app:** staff ID as the username for HS03–HS07, HS09–HS20 and DN03 (homestay).
     - HS01, HS02 and HS08 sign in with their manager accounts: `himsagar.owner` (HS01), `himsagar.housekeeping` (HS02) and `himsagar.frontoffice` (HS08).
   - **HOI console:** `hoi.admin`.
   - **Travel guide:**
     - `demo.admin` (state), `demo.officer.rudraprayag`;
     - `demo.business`, `demo.agency`, `demo.seeker`;
     - `himsagar.ridge` (the demo hotel, registered as UK-HTL-DDN-00030).
3. **Demo flow (2 minutes):**
   1. Owner Today.
   2. Guest page (room QR) → Towels → Confirm.
   3. Staff phone (on-shift housekeeper) → Accept → Done.
   4. Rooms → Checkout → cleaning job.
   5. Week numbers → Shift plan.
   6. May leave soon? → talking points → matches on the travel guide.
   7. Travel guide home → Kedarnath.
4. **If staff show "Off shift":** use Jobs → Details → "Practice: use this day and shift".

---

## 14. Pitch, deck and video

| File | What |
|---|---|
| `docs/PITCH_SCRIPT.md` | 3-minute pitch with slide and demo cues, 60 s version, framework (customer vs user, why/what/whom, stakeholders, moat, outcomes, long-term), hard-question answers |
| `docs/HOI_Final_Pitch.pptx` | 11-slide minimal deck (black style), no pricing |
| `videos/HOI_Final_Pitch_with_video.pptx` | Same deck with the film embedded (not in git; large) |
| `videos/HOI_demo_2min.mp4` + `.srt` | 2:04 product film "One Saturday", recorded on the live apps, voice-over and captions (not in git) |
| `docs/VIDEO_2MIN_SCRIPT.md` | The film's shot-by-shot script |
| `docs/VIDEO_SCRIPT.md`, `docs/VIDEO_DEMO_SCRIPT.md` | Earlier 60 s and 2 min scripts |
| `docs/MARKET_AND_DIFFERENTIATION.md` | Competitors, sources, validation plan |
| `docs/REAL_DATA_RESULTS.md` | Real-data model results |
| `docs/USABILITY_TEST.md` | 5-person usability test kit |

---

## 15. Known limits and what's next

**Not proven yet:**
- no real hotel pilot;
- no customer interviews;
- no usability test with real people;
- Hindi wording needs a native-speaker review;
- shift windows, offer windows and photo defaults are assumed.

**Not built yet:**
- money-flow data;
- open data for planners;
- official state-portal integration;
- clock-in/clock-out attendance;
- a hotel-specific Hindi welcome;
- push notifications in the background;
- a full offline mode;
- moving the owner portal off Streamlit.

**Known rough edges:**
- some timestamps are converted per page (the root fix is sending offsets from the server);
- the demo roster lives in 2029 and is mapped to today's weekday;
- free hosting sleeps.

**Next steps:**
1. 8–10 owner interviews with go/no-go targets.
2. A free 2-week pilot with 3 hotels or homestays, measuring hours short, overtime, check-ins and minutes from request to done.
3. A conversation with the state tourism department about the data layer.
4. Native-speaker Hindi review.
5. Change the demo passwords and rotate the API keys.

---

## 16. Where things are in the repo

| Topic | Path |
|---|---|
| Project rules | `CLAUDE.md`, `ml/CLAUDE.md`, `backend/CLAUDE.md` |
| Live shift context | `platform_api/hoi_platform/services/shifts.py`, `services/dispatch.py` |
| Jobs, offers, ranking | `platform_api/hoi_platform/services/dispatch.py` |
| Photo rules | `platform_api/hoi_platform/services/photo_proof.py` |
| Work log | `platform_api/hoi_platform/services/worklog.py`, `dashboard/pages/21_Work_Log.py` |
| Guest assistant | `platform_api/hoi_platform/services/concierge.py`, `guest_issues.yaml`, `services/places.py` |
| Voice | `platform_api/hoi_platform/services/voice.py`, `static/shared/voice.js` |
| Staffing and retention cover | `platform_api/hoi_platform/services/staffing.py`, `portal_client.py`, `backend/retention.py` |
| Staff app | `platform_api/hoi_platform/static/worker/` |
| Guest page | `platform_api/hoi_platform/static/guest/` |
| Owner portal pages | `dashboard/home.py`, `dashboard/pages/`, `dashboard/lib/` |
| Ops API key | `backend/auth.py` |
| Roster solver, forecast, attrition | `backend/` (see `backend/CLAUDE.md`), `ml/` |
| Travel guide | `portal/hoi_portal/` (routers, services, static) |
| Travel guide API reference | `docs/PORTAL_API.md` |
| Scenario simulator | `scripts/hoi_scenarios.py`, `scripts/scenario_report.py` |
| Demo model run | `scripts/run_demo_models.py` |
| Wake script | `scripts/wake_demo.py` |
