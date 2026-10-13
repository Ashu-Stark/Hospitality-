# HOI full product walkthrough video (about 6 min 30 s)

**For:** the voice artist, the person recording the screens, and the video editor.
**What it is:** a complete SaaS product tour of every HOI app, in the order a real hotel meets them. Same pace as the 60 s film
(about 2.4 words per second); voice-over is about 680 words, which leaves room for the clicks to play on screen. Same premium look as `docs/VIDEO_DEMO_SCRIPT.md`: off-white with soft
blue-violet glows, real screens in thin device frames, slow push-ins, one short caption per scene.
**Rule:** every scene is a real screen in the live apps. Nothing here is a mock-up.

**Accounts** (all passwords `123456`, demo data only; full list in `credentials.local.md`)

| App | URL | Sign in as |
|---|---|---|
| HOI team console | hoi-platform-admin.onrender.com | `hoi.admin` |
| Hotel portal (owner) | hoi-dashboard.onrender.com | `himsagar.owner` (hotel), `deodar.owner` (homestay), `himsagar.housekeeping` (department head) |
| Staff app (phone) | hoi-platform-api.onrender.com/worker/ | `HS05` (housekeeping), `HS18` (maintenance) |
| Guest page (phone) | Hotel portal → Rooms & guests → any room's QR link | no login |
| Travel guide | hoi-portal.vercel.app | public; `demo.admin` (state), `demo.business` (host), `demo.agency`, `demo.seeker`, `himsagar.ridge` |

Run `python scripts/wake_demo.py` 2–3 minutes before recording.

---

## Chapter 0 · Opening (0:00–0:30)

| Time | Screen | Caption | Voice-over |
|---|---|---|---|
| 0:00–0:08 | Dawn over the Mussoorie ridge, slow push-in | — | "Six a.m. in Mussoorie. Every room is booked, two housekeepers are off sick, and the shift plan is still a WhatsApp message." |
| 0:08–0:18 | Wave line: packed in summer, empty in winter | **Can't see the rush. Can't keep good people.** | "Small hotels and homestays in Uttarakhand run on people. But they can't see the rush coming, and good staff burn out and leave." |
| 0:18–0:30 | HOI logo; then five app icons fan out: Console, Hotel portal, Staff app, Guest page, Travel guide | **One system. Five apps.** | "This is HOI, Hospitality Operations Intelligence: one system with five simple apps, for the owner, the staff, the guest, the tourist and the state. Let's walk through a day." |

## Chapter 1 · Setting up a hotel (0:30–1:05)

| Time | Screen and clicks | Caption | Voice-over |
|---|---|---|---|
| 0:30–0:42 | Console as `hoi.admin`: Hotels → "Add a hotel" opens → plan modules ticked → hotel list | **Add a hotel in a minute** | "The HOI team adds a hotel and chooses what it can use. Every action here is logged." |
| 0:42–1:05 | Hotel portal → Settings → Setup by voice. Owner answers: "Hamare paas chaubees kamre hain, Mussoorie mein." Draft fills in: 24 rooms, Mussoorie. Owner checks the rest-hour rules, ticks the acknowledgement, presses Confirm. | **Set up by talking** | "The owner sets up the hotel by answering a few questions, in Hindi or English, by voice or typing. Nothing is saved until they check it and press Confirm, and legal values like rest hours must be confirmed by a person." |

## Chapter 2 · The owner's morning (1:05–1:40)

| Time | Screen and clicks | Caption | Voice-over |
|---|---|---|---|
| 1:05–1:20 | Hotel portal as `himsagar.owner` → Today. Zoom onto "Mostly fine. Look at: guest requests, low supplies." Glide across the five tiles. | **Is today OK? One look.** | "The owner's day starts on one screen that answers one question: is today OK? Rooms with guests, rooms to clean, staff on shift, guest requests waiting and supplies running low, each with one button." |
| 1:20–1:32 | Scroll to "Also needs you": "Room 101 needs the front desk. Nobody has taken it for 40 min." → Send again | **Nothing slips** | "Anything that's stuck shows up in plain words, with how long it has waited." |
| 1:32–1:40 | Tap **हिंदी** in the menu; the Today page switches to Hindi | **English or हिंदी** | "And the owner can switch the main screens to Hindi." |

## Chapter 3 · The guest (1:40–2:30)

| Time | Screen and clicks | Caption | Voice-over |
|---|---|---|---|
| 1:40–1:50 | Phone: QR card in a room is scanned → guest page: hotel photo, "Ask us · Ready to help", six big buttons | **Scan. Ask.** | "Every room has a QR code. The guest scans it: no app, no login." |
| 1:50–2:02 | Tap **Towels** → "Of course, I'll ask housekeeping…" → **Confirm** → "✓ Sent to Housekeeping · received" | **One tap to ask** | "Towels, a room clean, Wi-Fi, food: one tap, one confirm, and the guest can see the request move from received to on the way to done." |
| 2:02–2:12 | Mic: "कमरे में चूहा है" → reply in Hindi with a confirm card for pest control | **Speaks Hindi** | "Guests can just speak, in Hindi or English. A rat in the room goes straight to the right team as an urgent job." |
| 2:12–2:22 | "hidden places near here" → place cards with "Quieter" labels → **Open in Maps** | **Local tips, on the map** | "Ask for places to visit, even quiet ones away from the crowds, and get cards that open straight in Maps." |
| 2:22–2:30 | A long reply is being read aloud → **Stop speaking**; speaker menu → Voice off | **Quiet when needed** | "The voice can be stopped any time, or switched off." |

## Chapter 4 · The staff (2:30–3:25)

| Time | Screen and clicks | Caption | Voice-over |
|---|---|---|---|
| 2:30–2:42 | Staff phone as `HS05`: header "Housekeeping · On shift". **New job · Fresh towels · Room 101** drops in with a countdown → **Accept** | **The right person, on shift** | "The request lands on the phone of a housekeeper who is on shift right now. If she doesn't answer in time, it moves to the next person." |
| 2:42–2:52 | Delivery job: **Start**, then **Done**, no camera | **One tap. Done.** | "Small jobs are one tap to start and one tap to finish." |
| 2:52–3:05 | Hotel portal → Rooms & guests: Room 104 → **Checkout** → status "Cleaning". Staff phone: "Checkout clean · room 104" → Start opens the camera for a before photo → Done with an after photo → room goes to inspection → Pass → **Ready** | **Checkout → clean → ready** | "When a guest checks out, a cleaning job is created by itself. Cleaning needs a before and after photo, then a quick inspection, and the room is ready for the next guest." |
| 3:05–3:15 | Staff `HS18` taps **Speak**: "Room 204 ka geyser kaam nahi kar raha" → task card **Fix the geyser · Room 204 · Maintenance** → Confirm | **Just speak** | "Staff don't type. They speak, and it becomes a task." |
| 3:15–3:25 | Supplies tab → "Soap running low" → sent. Then the thank-you points card | **Supplies and thanks** | "They can ask for supplies, and see the thank-you points they've earned for good work." |

## Chapter 5 · Planning ahead (3:25–4:10)

| Time | Screen and clicks | Caption | Voice-over |
|---|---|---|---|
| 3:25–3:38 | Week numbers: "Busiest day: Saturday, about 21 of 24 rooms full." Bar chart with Saturday highlighted | **See the rush coming** | "HOI predicts how full the hotel will be in the days ahead. Tested on real public hotel data, it was off by about 2 rooms a day ahead, against 11 for the usual rule of thumb." |
| 3:38–3:52 | Shift plan builds: morning, evening, night; "Biggest gaps: short of 1 housekeeping staff on Saturday morning" → **Request staff** | **Shifts that plan themselves** | "Then it builds a fair shift plan that keeps rest rules, and shows exactly where you're short." |
| 3:52–4:02 | Extra staff form, pre-filled → Send. Cut to the travel guide as `demo.agency`: notification "Urgent: hotel short of staff" | **Extra hands, on request** | "One tap asks staffing agencies on Uttarakhand's travel and jobs site for extra hands. No names or staff details are shared." |
| 4:02–4:10 | Stock: low items → Order | **Never run out** | "Stock works the same way: it warns you before you run out." |

## Chapter 6 · Keeping good people (4:10–4:55)

| Time | Screen and clicks | Caption | Voice-over |
|---|---|---|---|
| 4:10–4:22 | People → May leave soon? Tiles: 2 check in this week, 3 keep an eye on, 14 doing fine. Table with IDs only | **Talk before they leave** | "HOI shows who may be thinking of leaving. It uses work patterns only, like late shifts and missed breaks, never age, gender or anything personal." |
| 4:22–4:32 | Open HS05: talking points in plain words → **We talked** | **What to talk about** | "For each person it suggests what to talk about. It's a prompt to talk, not a verdict." |
| 4:32–4:44 | High-risk card → **Look on the job portal** → "3 matches on the Uttarakhand Travel Guide" (codes, skills, availability) | **Cover, lined up** | "If the risk is high, it finds people with the right skills on the state's jobs board, shown without names, or posts the job in one click." |
| 4:44–4:55 | Sign in as `himsagar.housekeeping`: sees only housekeeping; a pay reason reads "Private: ask HR" | **Private by design** | "Department heads see only their own team, and anything about pay stays private to the owner and HR." |

## Chapter 7 · Homestay mode and settings (4:55–5:15)

| Time | Screen and clicks | Caption | Voice-over |
|---|---|---|---|
| 4:55–5:07 | Hotel portal as `deodar.owner`: the simple homestay Today page (6 rooms, 3 helpers) | **Small? Even simpler.** | "A six-room homestay gets a simpler version: just today, rooms, guest requests, staff and stock." |
| 5:07–5:15 | Settings → "Photos staff must take": before and after ticks per job type | **Your rules** | "Each hotel chooses which jobs need photo proof." |

## Chapter 8 · The travel guide (5:15–6:05)

| Time | Screen and clicks | Caption | Voice-over |
|---|---|---|---|
| 5:15–5:27 | hoi-portal.vercel.app home: "Find your place in the hills", Good to go now, road alert | **For tourists** | "Every hotel is part of a bigger network: the Uttarakhand Travel Guide." |
| 5:27–5:39 | Kedarnath page: weather, How busy today, Roads, busy-seasons strip, Plan your visit | **Know before you go** | "Tourists see the weather, how busy a place is, road alerts and the best months, before they travel." |
| 5:39–5:47 | Stays (verified hotels and homestays) → Experiences → a home-cooked meal → **Ask to join** | **Verified stays. Local hosts.** | "They find registered stays, and local experiences run by village hosts." |
| 5:47–5:55 | Jobs: job seekers, staffing agencies, "Urgent: hotel short of staff" | **Seasonal jobs** | "Job seekers and agencies find seasonal work that matches their skills." |
| 5:55–6:05 | Signed in as `demo.admin`: Officials' area side menu → Numbers: "4 places will be very crowded in the next 14 days" → Applications → Approve | **For the state** | "And district officials approve registrations, handle complaints and see crowding coming, so they can act early." |

## Chapter 9 · Close (6:05–6:30)

| Time | Screen | Caption | Voice-over |
|---|---|---|---|
| 6:05–6:17 | Three badges animate in: **Works on any phone** · **Hindi + English voice** · **No booking commission** | — | "HOI works on any phone, speaks Hindi, and never takes a cut of your bookings. Booking software helps you sell the room; HOI helps you run the stay." |
| 6:17–6:30 | Logo on the mountain gradient. Bottom line: "AI-Tourism Hackathon 2026 · Graphic Era, Dehradun". Small type: "Demo data. Forecast tested on a public hotel dataset." | **Smarter hotels. Happier teams.** | "HOI. Smarter hotels. Happier teams." |

---

## Voice-over only (read straight through)

> Six a.m. in Mussoorie. Every room is booked, two housekeepers are off sick, and the shift plan is still a WhatsApp message.
> Small hotels and homestays in Uttarakhand run on people. But they can't see the rush coming, and good staff burn out and leave.
> This is HOI, Hospitality Operations Intelligence: one system with five simple apps, for the owner, the staff, the guest, the tourist
> and the state. Let's walk through a day.
>
> The HOI team adds a hotel and chooses what it can use. Every action here is logged.
> The owner sets up the hotel by answering a few questions, in Hindi or English, by voice or typing. Nothing is saved until they check
> it and press Confirm, and legal values like rest hours must be confirmed by a person.
>
> The owner's day starts on one screen that answers one question: is today OK? Rooms with guests, rooms to clean, staff on shift,
> guest requests waiting and supplies running low, each with one button. Anything that's stuck shows up in plain words, with how long
> it has waited. And the owner can switch the main screens to Hindi.
>
> Every room has a QR code. The guest scans it: no app, no login. Towels, a room clean, Wi-Fi, food: one tap, one confirm, and the
> guest can see the request move from received to on the way to done. Guests can just speak, in Hindi or English. A rat in the room
> goes straight to the right team as an urgent job. Ask for places to visit, even quiet ones away from the crowds, and get cards that
> open straight in Maps. The voice can be stopped any time, or switched off.
>
> The request lands on the phone of a housekeeper who is on shift right now. If she doesn't answer in time, it moves to the next person.
> Small jobs are one tap to start and one tap to finish. When a guest checks out, a cleaning job is created by itself. Cleaning needs a
> before and after photo, then a quick inspection, and the room is ready for the next guest. Staff don't type. They speak, and it
> becomes a task. They can ask for supplies, and see the thank-you points they've earned for good work.
>
> HOI predicts how full the hotel will be in the days ahead. Tested on real public hotel data, it was off by about 2 rooms a day ahead,
> against 11 for the usual rule of thumb. Then it builds a fair shift plan that keeps rest rules, and shows exactly where you're short.
> One tap asks staffing agencies on Uttarakhand's travel and jobs site for extra hands. No names or staff details are shared.
> Stock works the same way: it warns you before you run out.
>
> HOI shows who may be thinking of leaving. It uses work patterns only, like late shifts and missed breaks, never age, gender or
> anything personal. For each person it suggests what to talk about. It's a prompt to talk, not a verdict. If the risk is high, it finds
> people with the right skills on the state's jobs board, shown without names, or posts the job in one click. Department heads see only
> their own team, and anything about pay stays private to the owner and HR.
>
> A six-room homestay gets a simpler version: just today, rooms, guest requests, staff and stock. Each hotel chooses which jobs need
> photo proof.
>
> Every hotel is part of a bigger network: the Uttarakhand Travel Guide. Tourists see the weather, how busy a place is, road alerts and
> the best months, before they travel. They find registered stays, and local experiences run by village hosts. Job seekers and agencies
> find seasonal work that matches their skills. And district officials approve registrations, handle complaints and see crowding coming,
> so they can act early.
>
> HOI works on any phone, speaks Hindi, and never takes a cut of your bookings. Booking software helps you sell the room; HOI helps you
> run the stay.
> HOI. Smarter hotels. Happier teams.

---

## Recording checklist

- [ ] `python scripts/wake_demo.py`, then wait for "All awake".
- [ ] Record desktop at 2560×1440 and the phones at 390×844; export at 1920×1080.
- [ ] Hide the browser bar and pointer; add soft tap rings in the edit.
- [ ] For chapter 4, create the jobs live while recording (guest asks, then the staff phone gets it), so the timings are real.
- [ ] For chapter 4's checkout, use an occupied room; the cleaning job appears on the housekeeping phone within seconds.
- [ ] For chapter 6, record as `himsagar.owner`, then `himsagar.housekeeping` (sign out in between).
- [ ] The voice onboarding (chapter 1) works typed with no keys; real voice needs the AI setting and the owner's consent tick. If voice is off, record it typed and keep the voice-over as it is ("by voice or typing").
- [ ] Keep "(demo)" visible in the hotel name somewhere in chapter 2.

## Accuracy rules (check before export)

- **Staff:** show staff as IDs (HS05) and role icons, never names or faces.
- **Leaving risk:** say "may be thinking of leaving", never "will quit".
- **Forecast numbers:** "about 2 rooms vs 11" is the 1-day-ahead result on the public Portuguese Hotel Booking Demand data (1.9 vs 10.9 rooms). Don't call it Uttarakhand data.
- **Features to leave out:** no money, revenue, energy or booking-system features; they are not in the product.
- **Hindi:** the Hindi wording on screen is a draft. Have a native speaker check the frames you show.
- **Shorter cut (about 3 min):** keep chapters 0, 2, 3, 4 (without supplies), 5 (forecast and shifts), 6 (first two scenes), 8 (first scene) and 9.
