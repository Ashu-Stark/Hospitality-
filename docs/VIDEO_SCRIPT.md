# HOI video script (60 seconds)

**For:** whoever records the voice-over and edits `video.mp4` (1280×720, 60 s, 13 scenes of about 4 s).
About 140 words of voice-over fits 60 s at a calm pace. Every line describes something the product does today.

---

## Version A: new voice-over for the current video, scene by scene

Use this if you only re-record the voice and change the on-screen text, without new footage.

| Time | Scene on screen (current) | Voice-over | On-screen text change |
|---|---|---|---|
| 0:00–0:04 | Mountains, "Running a hotel is all about…" | "Running a hotel in the hills is all about people." | none |
| 0:04–0:08 | "Good staff quit without warning." | "But good staff quit without warning…" | none |
| 0:08–0:12 | "Packed in summer. Empty in winter." | "…and guests come in waves: Char Dham rush, then quiet months." | none |
| 0:12–0:16 | Logo, "Meet Hospitality Operations Intelligence" | "Meet HOI, the operations assistant for small hotels and homestays." | none |
| 0:16–0:24 | Phone notification, "Every update. The right action." | "Every checkout, guest request and low-stock alert becomes a job on the right person's phone. If nobody takes it, it moves on." | Change the sub-line "Bookings, requests and stock alerts…" to **"Checkouts, guest requests and stock alerts become clear jobs for the right person."** |
| 0:24–0:32 | Laptop, "Know who might quit. Before they do." | "It shows who may be thinking of leaving, and what to talk about. If the risk is high, it finds cover on Uttarakhand's travel and jobs site." | **Replace the names (Sunita, Ravi…) with staff IDs (HS05, HS12…)** to match the product and our privacy rule. |
| 0:32–0:36 | Tablet roster, "Shifts that plan themselves." | "Shifts plan themselves: fair, rested, ready in minutes." | Change "Balanced" to **"Rest rules kept"** (optional). |
| 0:36–0:40 | Curve, "See busy days coming." | "And it sees busy days coming, weeks ahead." | none |
| 0:40–0:48 | Phone, "Just speak. It becomes a task." | "Staff just speak, in Hindi or English: 'Room 204 ka geyser kaam nahi kar raha.' It becomes a task, with a photo when the job needs proof." | none |
| 0:48–0:52 | Tiles: Team, Guests, Stock, Money, Energy | "Guests scan a QR in their room to ask for anything, by voice, and find nearby places on the map." | **Replace "Money" and "Energy"** (not built) with **"Rooms: cleaned, checked, ready"** and **"Travel guide: verified stays and local jobs"**. |
| 0:52–0:56 | Logo | "Hospitality Operations Intelligence." | none |
| 0:56–1:00 | "Smarter hotels. Happier teams." | "Smarter hotels. Happier teams." | none |

**Voice-over only (Version A, about 145 words), for reading straight through:**

> Running a hotel in the hills is all about people. But good staff quit without warning, and guests come in waves: Char Dham
> rush, then quiet months.
> Meet HOI, the operations assistant for small hotels and homestays.
> Every checkout, guest request and low-stock alert becomes a job on the right person's phone. If nobody takes it, it moves on.
> It shows who may be thinking of leaving, and what to talk about. If the risk is high, it finds cover on Uttarakhand's travel and
> jobs site.
> Shifts plan themselves: fair, rested, ready in minutes. And it sees busy days coming, weeks ahead.
> Staff just speak, in Hindi or English: "Room 204 ka geyser kaam nahi kar raha." It becomes a task.
> Guests scan a QR in their room to ask for anything, and find nearby places on the map.
> Hospitality Operations Intelligence. Smarter hotels. Happier teams.

---

## Version B (recommended): re-cut with the new features and real screens

Use real screen recordings from the live apps for the new scenes (`python scripts/wake_demo.py` first).

| Time | Scene | Voice-over |
|---|---|---|
| 0:00–0:05 | Mountains. Text: **"Peak season. Every room full."** | "Saturday, peak season, Mussoorie. Every room is full…" |
| 0:05–0:10 | Text: **"Two staff missing. A guest waiting."** | "…two housekeepers didn't come, and room 104 is still waiting for towels." |
| 0:10–0:14 | Logo, "Meet HOI" | "Meet HOI. It helps small hotels see the rush coming and run every day smoothly." |
| 0:14–0:20 | **Guest room QR → chat**: guest taps "Towels", Confirm, "Sent to housekeeping" | "Guests scan the QR in their room and ask, by voice or touch, in Hindi or English." |
| 0:20–0:26 | **Staff phone**: "New job · Fresh towels · Room 104" → Accept → Done | "The request lands on the right person's phone. One tap to accept, one tap when done. When a guest checks out, cleaning is booked by itself." |
| 0:26–0:32 | **Owner's Today page**: "Mostly fine. Look at: guest requests." and five big numbers | "The owner sees in five seconds whether today is OK, and what needs attention." |
| 0:32–0:38 | **Forecast bar chart + shift plan** | "It predicts how full you'll be and plans fair shifts to match. Tested on real hotel data, it cut forecast error by more than half." |
| 0:38–0:46 | **"May leave soon?"** list with IDs → "Talk to them" → "3 matches on the travel guide" | "It shows who may be thinking of leaving and what to talk about, and if needed, finds cover on Uttarakhand's travel and jobs site." |
| 0:46–0:52 | **Staff voice**: "Room 204 ka geyser kaam nahi kar raha" → task card | "Staff just speak, and it becomes a task." |
| 0:52–0:56 | **Travel guide** home: places, stays, experiences, jobs | "And it's linked to a travel guide for tourists, verified stays and local jobs." |
| 0:56–1:00 | Logo, "Smarter hotels. Happier teams." | "HOI. Smarter hotels. Happier teams." |

**Voice-over only (Version B, about 150 words):**

> Saturday, peak season, Mussoorie. Every room is full, two housekeepers didn't come, and room 104 is still waiting for towels.
> Meet HOI. It helps small hotels see the rush coming and run every day smoothly.
> Guests scan the QR in their room and ask, by voice or touch, in Hindi or English.
> The request lands on the right person's phone. One tap to accept, one tap when done. When a guest checks out, cleaning is booked by itself.
> The owner sees in five seconds whether today is OK, and what needs attention.
> It predicts how full you'll be and plans fair shifts to match. Tested on real hotel data, it cut forecast error by more than half.
> It shows who may be thinking of leaving and what to talk about, and if needed, finds cover on Uttarakhand's travel and jobs site.
> Staff just speak, and it becomes a task.
> HOI. Smarter hotels. Happier teams.

---

## Wording rules for the video

- Say "**may** be thinking of leaving", not "warns you before someone quits". The model is a prompt to talk, not a certainty.
- "Cut forecast error by more than half" is true for 7 days ahead on the public Portuguese hotel data (−51% to −63%); 1 day ahead it is −82% to −83%. Don't call it Uttarakhand data.
- Don't show Money or Energy features, booking-system links or real people's names: none of these are in the product.
- Show staff as IDs (HS05) or role icons, never names or faces of real staff.
- Background music: keep it soft under the voice; the Hindi line should be clearly audible.
