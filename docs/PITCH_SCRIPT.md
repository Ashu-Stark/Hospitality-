# HOI pitch script

**For:** the Team Innov8 presenter, 3-minute pitch plus questions (AI-Tourism Hackathon 2026, TBI-GEU).
**Rule for the presenter:** say only what is below. Numbers come from `docs/REAL_DATA_RESULTS.md` and
`docs/MARKET_AND_DIFFERENTIATION.md`. Anything marked *(to validate)* is our belief, not yet proven with real hotels. Say so if asked.

---

## The hook (first 15 seconds)

> "Saturday, peak season, Mussoorie. Every room is full. Two housekeepers didn't turn up. The guest in room 104 has asked
> for towels twice, and the owner is planning next week's shifts on WhatsApp.
> Nobody saw this Saturday coming, though the data to predict it already existed.
> We built the system that sees it coming and tells every person in the hotel what to do next."

*(This is an illustrative scene, not a real hotel. Do not present it as a case study.)*

---

## 1. Problem in one line

> "Small hotels and homestays in Uttarakhand can't see the next rush coming, so they are short-staffed at peaks, staff burn
> out and leave, and guests wait."

## 2. Why, what, for whom

| | One sentence to say |
|---|---|
| **Why** | Tourism in Uttarakhand is very seasonal (Char Dham, summer, festivals), and small properties plan staff by memory, paper or WhatsApp *(to validate)*. |
| **What** | HOI predicts how full the hotel will be, plans shifts from that prediction, sends each job to the right person's phone, and flags who may leave before they do. |
| **For whom** | Owners of small hotels and registered homestays in Uttarakhand (about 10–40 rooms), and the state, which needs trained staff and fair, verified stays. |

## 3. Customer vs user

| | Who | Can they buy it for themselves? |
|---|---|---|
| **Customer (pays)** | The hotel or homestay owner. Later, homestay clusters, and the state tourism department for the travel portal *(to validate)*. | **Yes.** An owner buys it for their own property, the same way they buy a booking system. |
| **Users (use it daily)** | Owner and manager (Today page), department heads, housekeeping, kitchen and front-desk staff (phone app with voice), guests (room QR chat), tourists (travel site), district officials, job seekers and staffing agencies. | **No.** Staff, guests and tourists never pay. That is why it has to be free for them, on any phone, with no app store. |

Line to say:
> "The owner pays. But the people who make it work are the housekeeper with a basic Android phone and the guest in room 104.
> So we designed for them first: voice, Hindi, one button per job."

## 4. Everyone involved

| Stakeholder | What they need | What HOI gives them |
|---|---|---|
| Owner or general manager | Know if today is OK; no surprises at peaks; keep good staff | One-line answer and five numbers on the Today page; shift plan from the forecast; "talk to them" prompts |
| Frontline staff | Clear instructions, fair work, recognition | One job, one button, in Hindi or by voice; thank-you points; fair shifts |
| Guest | Fast help without calling | Room QR chat: towels, cleaning, problems, nearby places with map links |
| Tourist | Where to go, how busy, where to stay safely | Travel site: busy levels, road alerts, verified stays, local experiences |
| District and state officials | Registered businesses, complaints handled, crowd warnings | Approvals, complaint queue, crowding forecast |
| Job seekers and agencies | Seasonal work that matches skills | Hiring board, skill matching, urgent requests from hotels |

## 5. Solution: say outcomes, not features

> "We don't sell a dashboard. We sell three results:"
1. **No surprise rush.** The hotel knows next week's busy days, and the shift plan follows automatically.
2. **No lost request.** Every guest request becomes a job on the right person's phone, and it moves on if nobody takes it. When a guest checks out, a cleaning job is created on its own.
3. **Fewer people quit in peak season.** The owner gets a short list of who to talk to this week, with what to talk about. If the risk is high, HOI finds matching job seekers on the state hiring board, or posts the job in one click.

## 6. Outcome-driven: prediction, then action, then a measurable result

| Prediction | Action it drives | How we measure it |
|---|---|---|
| **Rooms full in the next 1–30 days.** Tested on a real public hotel dataset (Hotel Booking Demand, two hotels in Portugal): 1 day ahead we were off by **1.9 rooms vs 10.9** for "same day last week" (**−83%**), and 7 days ahead **5.3 vs 10.9 rooms (−51%)**. | Shift plan built from the forecast; extra staff requested before the rush | Hours short per week; peak days covered; overtime hours |
| **Who may leave.** On 1,129 real employee records the model ranks a leaver above a stayer **66%** of the time, against **55%** for a simple checklist. That is modest, so we use it as a prompt to talk, never as a verdict. | Talking points for the owner; cover lined up from the hiring board | Check-ins done; people who left during peak, before and after the pilot |
| **Guest requests and stock** | Jobs routed to on-shift staff; low-stock alerts | Minutes from request to done; stock-outs per month |

Line to say:
> "Our forecast was tested on real hotel data, not just our demo. The demo hotel itself is made-up data,
> and the next step is a 2-week pilot to measure these numbers in a real Uttarakhand property."

## 7. Moat: why us, not eZee, STAAH or OYO

> "Booking software and OTAs help hotels **sell the room**. We help them **run the stay** after the booking. We sit next to them, not against them."

1. **Closed loop.** Forecast, then shifts, then jobs, then results flow back. Every week of a hotel's own data makes its own predictions better.
2. **Built for the frontline.** Voice and Hindi, one button per job, works on any phone through a web link.
3. **Linked to the state travel site.** Verified stays, a hiring board and staffing agencies are on the same network. More hotels bring more job seekers and agencies, which makes every hotel easier to staff.
4. **No booking commission, ever.** We are not a middleman on room revenue.

*(Be honest if asked: this is an early moat. It gets stronger with each hotel's data and with the network on the travel site.)*

## 8. Long-term business

| Stage | Who pays | Price *(proposal, to validate)* |
|---|---|---|
| Start | Registered homestays | **Free**, so they adopt it and data starts to flow |
| Grow | Small hotels, 1 property up to about 40 rooms | **About ₹999–1,999 per month**, less than or similar to a small booking system |
| Scale | Hotel groups; clusters of 8–10 homestays sharing staff | Quote, or one shared subscription |
| Platform | State tourism department (travel site, hiring board, crowd forecasts) | Government contract *(to validate)* |

Growth path: Mussoorie and Rishikesh first, then the Char Dham routes, then other hill states with the same seasonal pattern.

## 9. Close (last 15 seconds)

> "Peak season will come every year. With HOI, the hotel sees it coming, every person knows their next job, and good staff stay.
> We're asking for two things: introductions to 3 hotels or homestays for a free 2-week pilot, and mentor time on pricing."

---

## 60-second version

> "Saturday, peak season, Mussoorie: every room full, two housekeepers missing, a guest waiting for towels. Small hotels in
> Uttarakhand can't see the rush coming. HOI predicts how full the hotel will be, builds the shift plan from it, sends every guest
> request to the right person's phone, and tells the owner who may leave and what to talk about. On real hotel data our forecast cut
> the error by 83% one day ahead. The owner pays a small monthly fee; staff and guests use it free, by voice, in Hindi. Booking tools
> sell the room; we run the stay. We want 3 pilot hotels to prove it in Uttarakhand."

## Hard questions: honest answers

| If they ask | Say |
|---|---|
| "Is this real hotel data?" | "The demo hotel is made-up data. The forecast was tested on a real public dataset of two Portuguese hotels. We have no Uttarakhand pilot yet; that is our next step." |
| "Has any hotel agreed to pay?" | "Not yet. The prices are a proposal. We plan 8–10 interviews with go/no-go targets, for example at least 2 of 3 managers willing to pay ₹999 a month." |
| "Why won't OYO or eZee just add this?" | "They focus on selling rooms and owner revenue. We found no public sign of forecast-based shift planning or photo-checked housekeeping in their products. Our edge is frontline voice in Hindi and the link to the state hiring network." |
| "Isn't predicting who leaves a form of surveillance?" | "We use job and shift data only, never age, gender, religion or health. The output is a prompt to talk, and pay reasons are visible only to the owner and HR." |
| "What if the internet is bad?" | "The staff app works through a web link on any phone and keeps its screens offline. A full offline mode is on our list." |
| "How will you reach hotels?" | "Through the district tourism office's registered homestay list, the GEU hospitality faculty, and the free homestay tier." |

## Timing guide (3 minutes)

| Part | Seconds |
|---|---|
| Hook | 15 |
| Problem, why, what, for whom | 25 |
| Customer vs user | 20 |
| Solution as outcomes, with a 20-second live demo (guest asks for towels, staff phone gets the job) | 50 |
| Prediction to outcome, with numbers | 30 |
| Moat | 20 |
| Business and close | 20 |
