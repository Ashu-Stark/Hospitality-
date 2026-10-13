# HOI usability test (5 people, about 1 hour)

Goal: get real numbers for "easy to use" before the next review. Use one person per role, and nobody who built the apps.
Each person does 3 tasks on a phone (or a laptop for the owner and the official). Do not help them; only read the task aloud.

## Before you start

1. Run `python scripts/wake_demo.py` 2-3 minutes before the first person (the free servers sleep).
2. Logins are in `credentials.local.md` (all passwords `123456`, demo data only).
3. For the guest: sign in to the hotel portal as `himsagar.owner`, open Rooms & guests, and open the guest link or QR for any room.
4. One teammate reads the tasks; another fills in the sheet below. Use a phone stopwatch.

## Tasks

| Person | Task | Done when | Target time |
|---|---|---|---|
| Hotel owner (laptop) | 1. "Is anything wrong in the hotel today?" | Names the problem from the Today page | 30 s |
| | 2. "Ask for one extra housekeeping person for Saturday." | Request sent | 90 s |
| | 3. "Which staff member should you talk to this week, and what about?" | Names HS05 or HS12 and one talking point | 60 s |
| Housekeeper (phone, `HS05`) | 1. "Accept the new job." | Job accepted | 20 s |
| | 2. "Finish the job you are working on." | Job marked done (with photo if asked) | 60 s |
| | 3. "Tell the app by voice that soap is running out." | Supply request sent | 60 s |
| Guest (phone, room link) | 1. "Ask for two extra towels." | Request confirmed | 30 s |
| | 2. "Find a quiet place to visit nearby and open it in Maps." | Maps opens | 45 s |
| | 3. "Make the assistant stop talking." | Speech stops | 10 s |
| Tourist (phone, hoi-portal.vercel.app) | 1. "Is Kedarnath very busy this week?" | Reads the busy level | 45 s |
| | 2. "Find a homestay near Mussoorie." | Opens one stay | 60 s |
| | 3. "Find a local food experience and ask to join." | Join request sent | 90 s |
| Official (laptop, `demo.admin` on the portal) | 1. "How many complaints are late?" | Reads the number | 30 s |
| | 2. "Approve one waiting application." | Application approved | 90 s |
| | 3. "Which place will be most crowded in the next 2 weeks?" | Names it | 45 s |

## Recording sheet (copy once per person)

| Task | Seconds | Done without help? (yes / with hint / gave up) | Where they hesitated or tapped the wrong thing | Their words |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

After the 3 tasks, ask two questions:
- "On a scale of 1 to 5, how easy was this?" (1 = very hard, 5 = very easy)
- "What was the most confusing moment?"

## What to report

- **Success rate:** tasks done without help ÷ 15.
- **Median time** per task, compared with the target.
- **Ease score:** the average of the 1-5 answers.
- **Top 3 confusing moments**, with a screenshot of each.

Five people will not give statistically strong numbers. Say so on the slide, and present them as a first check, not proof.
