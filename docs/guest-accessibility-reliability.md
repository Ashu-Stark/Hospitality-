# Guest page and staff app: retry safety and accessibility

Branch `saumya/guest-accessibility-reliability` (Saumya Goswami). Covers the guest QR page (`/guest/`) and the staff phone
app (`/worker/`) served by `platform_api`. Full write-up with screenshots: [PDF](Guest_Accessibility_Reliability_Saumya_Goswami.pdf).

## 1. Retry safety: one tap, one job

### What was wrong (reproduced in tests first)

| Situation | Before | Evidence |
|---|---|---|
| Guest asks for towels; the answer is lost (hotel Wi-Fi, a gateway 504 from a sleeping Render server after the app already created the job); the guest taps again | **Two jobs** for the same towels, two staff offers | `test_without_a_key_a_retried_guest_request_creates_a_second_job` (still passes: old clients behave as before) |
| Six parallel taps with the same request | **5 jobs** (the per-room limit of 5 stopped the sixth) | first run of `test_parallel_double_tap_with_one_key_creates_one_job`: `assert (5 - 0) == 1` |
| A worker's "accept" succeeds, the answer is lost, the phone retries | The retry gets **409 "This offer is no longer available"**, so the worker is told they failed although they have the job | first run of `test_retried_staff_action_is_replayed_not_turned_into_an_error` |
| A supply request is retried | **3 identical requisitions** from 3 sends | first run of `test_retried_supply_request_is_stored_once`: 3 ids |
| `shared/net.js` retried any POST after a 502/503/504, on the comment "the app never saw the request" | Not true for a 504: the gateway gives up while the app is still working | read of `net.js` |

### What changed

- `hoi_platform/idempotency.py` (new): an optional `Idempotency-Key` header. The first request reserves the key (unique
  index), runs the action and stores the answer. The same key with the same body gets the stored answer back with
  `Idempotent-Replayed: true`. A key still running gets 409, which is safe to retry. The same key with a different body
  gets 422. If the action fails, the key is released so a corrected retry works. Keys are scoped by room token or user and
  endpoint. Records expire after 24 h (TTL index `idempotency_keys.created_at`).
- Used on: `POST /public/guest/{token}/requests` and `/actions` (the concierge's Confirm), `POST /dispatch/jobs/{id}/accept|decline|start|complete`
  and `POST /inventory/requests`. **Backward compatible**: without the header nothing changes.
- `shared/net.js`: `HOINet.key(signature)` gives one key per user attempt and keeps it until the server has answered,
  so tapping again after "no connection" is a retry, not a new request. A POST is retried automatically only when
  it carries a key.
- `guest/guest.js`, `worker/app.js`: send the key on those endpoints; the buttons were already disabled while sending.

## 2. Accessibility (WCAG 2.1 AA)

### How it was measured

`platform_api/tests/a11y/audit.mjs` opens every page state in headless Chrome/Edge at phone size (390 x 844) and checks
four things. Guest: Ask, Hotel info, My requests, Check-out and Hotel info in Hindi. Staff: sign-in, Today, Jobs,
Supplies and Me, 10 states in all.

1. axe-core 4.10 with the WCAG 2.0/2.1 A and AA rules
2. visible controls smaller than 44 x 44 px
3. Devanagari text inside an element whose language is English (WCAG 3.1.2; axe does not check this)
4. whether "Request sent" reaches the `role=status` region (WCAG 4.1.3)

"Before" is commit `a679ba4` (main); "after" is this branch.

| Check (10 page states) | Before | After |
|---|---|---|
| axe violations | 2 page states, **28 elements** (`aria-prohibited-attr`, serious) | **0** |
| Controls under 44 x 44 px | **5 distinct controls** (English/Hindi buttons 40 px high, photo-credit button 22 x 22, two checkboxes 20 x 20) | **0** |
| Hindi text without `lang="hi"` | **24 text nodes** (the हिंदी button on 6 page states, 18 Hindi labels under the request buttons) | **0** |
| "Request sent" announced to screen readers | **No** (the toast had no role) | **Yes** |

### What was wrong and the fix

| Problem | Who it affects | Fix |
|---|---|---|
| Veg / non-veg marks were `<i aria-label="veg">` without a role, so screen readers ignore the label | A blind vegetarian guest cannot tell which dishes are veg | `role="img"` |
| Toasts ("Request sent", "Job done") were only visual | Screen-reader users never hear that the request went through | A polite `role="status"` region; each toast's text is copied there (cleared first, so a repeat is read again) |
| Hindi labels on an English page (and the हिंदी button) had no `lang` | Read out letter by letter or with an English voice | `lang="hi"` / `lang="en"` on the other language's text |
| Language buttons 40 px high, photo-credit button 22 x 22 px, "Keep me signed in" and "voice" checkboxes 20 x 20 px | Mis-taps on phones, harder for older staff and guests | 44 px minimum. The credit button keeps a 22 px dot inside a 44 px tap area, and the checkbox labels are 44 px tall |
| Staff tab icons (◐ ⚡ ▣ ◉) were read aloud ("high voltage, Jobs") | Screen-reader users | `aria-hidden="true"`, as the guest page already did |

Already fine, and kept that way: zoom is not disabled, focus outlines are visible (`:focus-visible`), and errors use
`role="alert"`.

### Keeping it fixed

`tests/test_accessibility.py` serves the app on a free port, runs the audit and fails on any axe violation, small
target, unmarked Hindi text or a missing status message. Removing the `role="img"` fix made it fail at once
(`aria-prohibited-attr x11`). CI installs Node 22 and `npm ci --prefix platform_api/tests/a11y`; the test is skipped,
not failed, where Node, axe-core or Chrome are missing.

## 3. Tests

| | Before | After |
|---|---|---|
| `platform_api` suite (mongomock, offline) | 325 passed | **336 passed** (+10 idempotency, +1 accessibility gate) |
| `test_idempotency.py` repeated 15 times | | 15/15 passed (parallel double-tap included) |

## Limitations

- The parallel double-tap test runs on mongomock. Its unique index behaves like MongoDB's for this purpose, but it has not
  been tested against a real Atlas cluster under load.
- A key is kept until the server answers. If a guest closes the page during a lost-answer retry, a later tap is a new
  attempt (a second job is possible, as before).
- Automated checks find only part of WCAG. Screen-reader use with TalkBack and NVDA, colour contrast on photos behind
  text, and the voice features still need a manual test with real users (see `docs/USABILITY_TEST.md`).
- The 44 px rule is WCAG 2.5.5 (AAA) and platform guidance, stricter than the AA minimum. It was chosen because the
  people using these pages are on phones.
