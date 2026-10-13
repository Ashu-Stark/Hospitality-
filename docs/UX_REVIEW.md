# UI/UX review — findings and fixes

**Audience:** the team. **Method:** heuristic review against the reference designs (Train.png), measured WCAG contrast, and real-browser runs at 1440 px (desktop) and 390 px (phone) with Playwright and Chrome.

## Fixed in this round

| # | Finding | Severity | Fix |
|---|---|---|---|
| 1 | Refreshing the browser signed managers out | High | Rotating refresh token in a `SameSite=Strict` cookie; the session restores on reload. Verified in Chrome. |
| 2 | Access tokens now expire after 30 min, which would kick users mid-shift | High | The client silently refreshes on a 401 and retries once; platform admins get their open hotel back |
| 3 | Muted text #898781 was 3.2:1 on the page background (below 4.5:1) | High (a11y) | #6b6a65 (4.8:1) everywhere: dashboard, staff app, guest page, website |
| 4 | White text on the light end of the orange hero was 2.8:1 | High (a11y) | Deeper gradient; body text sits on ≥4.5:1, the bright tone only in the text-free corner |
| 5 | Blue text on light-blue chips was 4.1:1 | Medium (a11y) | #1557c0 (5.9:1) |
| 6 | No visible keyboard focus on custom controls | Medium (a11y) | 3 px focus ring on buttons, links, tabs and inputs |
| 7 | With 16 nav items, the active page scrolled out of view | Medium | The nav wraps to two rows on desktop and stays a scrolling row on phones |
| 8 | Rooms: supervisors had to find rooms in a dropdown | Medium | "Needs your attention" queue with one-click Pass / Re-clean and live job status; the action dropdown lists rooms that need action first |
| 9 | Staff app showed the wrong "today" in India (UTC date conversion) | High | Local-date formatting; verified with an IST machine |
| 10 | Staff app: a variable shadowed a helper and silently broke rendering | High | Fixed; a full end-to-end browser run is part of the checks |
| 11 | Camera reopen could leave a dead end | Medium | Video released on close; "Try again" button when the camera fails |
| 12 | Hindi mode still showed English shift, day and department names | Low | Translated |

## Staff app and guest page: design decisions

- **Phone-first:** bottom tab bar, ≥52 px buttons, one primary action per screen, works with one hand.
- **The ping is impossible to miss:** large countdown ring, vibration, a red dot on the Jobs tab, and a toast when on another tab.
- **Live camera only:** no file picker, so gallery photos cannot be reused. Server-time stamp and hash.
- **Hindi/English** toggle, remembered on the phone. The Hindi copy is plain and short; review it with native-speaking staff before rollout.
- **Works offline** for the app shell, with a clear "you are offline" bar. Actions need a connection.
- **Guest page** asks for nothing personal, shows request status in plain words, and rate-limits per room.

## Still open (not fixed)

- The dashboard is a Streamlit app: dense tables are hard to use on phones. Managers on the move should get a dedicated mobile view (the staff app pattern) later.
- No screen-reader audit was done (only contrast and focus); Streamlit widgets have mixed ARIA support.
- Charts rely on hover tooltips; add table views for touch and assistive-technology users.
- Hindi copy needs native-speaker review; other languages (Garhwali, Nepali for many hill staff) are not covered.
- Usability testing with real hotel staff has not happened. This review is expert/heuristic only.
