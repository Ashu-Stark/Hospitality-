# Competitor scan: what to borrow, where HOI differs

**Audience:** the team. **Checked:** 2026-10-13 via web search. Vendor pages are marketing; treat feature claims as unverified until a demo.

**Differentiation:** distribution layers (GDS, OTAs, channel managers, PMS), Zostel/OYO/state-scheme operating models, affordability, staffing, incentives, community experiences and the prioritised roadmap are in `docs/MARKET_AND_DIFFERENTIATION.md`.

## Hotel operations / housekeeping / task platforms

| Product | Publicly stated strengths | What HOI borrows |
|---|---|---|
| Flexkeeping | Housekeeping, maintenance, collaboration, automation and QA suites; checklists, SOPs, automated cleanings, lost & found; PMS integrations (Mews, Cloudbeds, Oracle) | Room-type checklists inside a job; QA inspection step after "done" |
| hotelkit | Real-time room status, special requests, task visibility (reviewer-cited on Hotel Tech Report) | Live board of every open request |
| ALICE / Actabl | Task management, real-time messaging, ops analytics; ticketing with photos and live ticket tracking, per-attendant progress (Hotel Tech Report) | Photo on tickets, per-worker progress |
| Optii | Listed as the benchmark on review sites; current features not verified | — |

## Inventory

| Product | Publicly stated strengths | What HOI borrows |
|---|---|---|
| HelloShift | PAR thresholds, low-stock alerts, notification owners, usage history | Owner per alert; usage history per item |
| Stayntouch (guide) | Reorder point = daily usage × lead time + safety stock, below PAR | Reorder-point formula shown in the UI |
| Vyapar (India) | Free stock tracking across items, stores, transactions | Simple multi-store stock view |

## Workforce and retention (from the team's earlier analysis)

Legion (forecast + scheduling, no individual attrition risk), inFeedo (risk → action, no roster), Darwinbox / Pocket HRMS (HR system of record, no predictive roster), MEND (staffing marketplace).

## Where HOI is different (and how to say it honestly)

1. **One loop:** forecast → roster → dispatch → inventory → retention signals in one product. Competitors cover one or two of these.
2. **Retention-aware dispatch:** auto-assign avoids piling extra jobs on staff already flagged for overload. We found no competitor publicly offering this.
3. **Forecast-aware purchasing:** reorder quantities scale with forecast occupancy, not just static par.
4. **Proof of work:** server-time-stamped, hashed before/after photos (ALICE/Actabl also do photo tickets, so this is parity, not a moat).
5. **Honest limits:** synthetic data only; no PMS integration, payroll or native app yet. Competitors above have real customers.

## Sources

- https://flexkeeping.com/hotel-task-management-software/ · https://www.flexkeeping.com/housekeeping-software
- https://hoteltechreport.com/optii/alternatives
- https://www.capterra.com/p/153733/ALICE/
- https://helloshift.featurebase.app/help/articles/7592403-inventory-management
- https://www.stayntouch.com/articles/?p=299
- https://vyaparapp.in/free/inventory-management-software/hotel
- https://www.cleverence.com/articles/for-business/inventory-management-in-hotel-industry-4073/

## eZee Absolute (Yanolja Cloud Solution), India hotel PMS — checked 2026-10-13

Source: https://www.ezeeabsolute.com/hotel-management-software-in-india.php (now redirects to Yanolja Cloud Solution). The page lists:
fast check-in/out, police inquiry form (foreign-guest reporting), reservations from all sources, rate management, user privileges,
meal plans and packages, a mobile guest self-service portal (self check-in, service requests, bills), a mobile app for operations,
GST-compliant invoicing (GSP integration, e-invoice via ClearTax IRN/QR), booking engine, channel manager, POS, and local market managers
(including Dehradun, Mussoorie and Uttarakhand).

| eZee capability | HOI decision | Why |
|---|---|---|
| Reservations, rates, booking engine, channel manager, POS | **Not built: integrate** | That is a PMS; HOI is the operations and retention layer next to it. Room status and occupancy actuals should come from the PMS. |
| Guest self-service: request services | **Built**: QR per room → auto-dispatched job | Feeds HOI's dispatch, which eZee does not have |
| Fast check-in/out | **Built**: room status board (checkout → cleaning job → inspection → ready) | Room turnaround is housekeeping work, HOI's core |
| GST-compliant invoices | **Partly**: GST on purchase orders (HSN, CGST/SGST/IGST, GSTIN check, printable PO) | Guest invoices belong to the PMS |
| Mobile app for operations | **Built**: separate staff app (PWA) with live camera and Hindi | Frontline-first, unlike a manager app |
| User privileges | **Built**: 6 roles, tenant isolation, audit | |
| Police inquiry form (Form C) | **Not built** | It needs guest identity documents; HOI deliberately holds no guest personal data |
| Local presence | Not a software feature | eZee has market managers in Uttarakhand; HOI would need local partners |

Honest gap: eZee has many hotels and real data (testimonials cite chains such as Zostel); HOI is a prototype on synthetic data.
