# HOI — full product scope (what exists, what is being built, what is roadmap)

**Audience:** the team. `[x]` built · `[b]` building in this round · `[r]` roadmap (not built).

## 1. Surfaces and who uses them

| Surface | Who | Access |
|---|---|---|
| Marketing website (`website/`) | Prospects, judges | Public, static HTML |
| Platform console | HOI staff (super-admin) | `platform_admin` role |
| Hotel dashboard | Owner / GM / HR / department heads / storekeeper | Role-filtered pages, one hotel group (tenant) |
| Employee app | Frontline staff | `worker` role; mobile-first; sees only their own shift, jobs, tasks, supply requests |

## 2. Access and roles `[b]`

- Sign in with username + password/PIN (PBKDF2-SHA256, 200k iterations, salted; lockout after 5 failed attempts for 5 minutes).
- Sign up only with a one-time **invite code** from a hotel admin (the code fixes the role and tenant).
- One-click demo accounts for each role on the demo hotel (clearly labelled).
- Role → pages:

| Page | owner/GM | HR | dept head | storekeeper | worker |
|---|---|---|---|---|---|
| Overview, Tasks | ✓ | ✓ | ✓ | – | – |
| Risk, Employee, What-if, Closed loop | ✓ | ✓ | – | – | – |
| Roster, Dispatch, Voice | ✓ | – | ✓ | – | – |
| Inventory | ✓ | – | ✓ (request/view) | ✓ | – |
| Setup (properties, staff, users, invites), Admin | ✓ | – | – | – | – |
| Employee app (My day, Jobs, Supplies, My tasks) | – | – | – | – | ✓ |

- Workers never see risk scores, their own or anyone else's (privacy and purpose limitation).
- Audit log of admin actions (who, what, when, tenant).

## 3. Platform console (super-admin) `[b]`

Tenants list (plan, status, properties, staff, users, jobs, last activity) · onboard a new hotel group (creates the tenant plus a one-time owner invite) · suspend / reactivate · change plan · enable/disable modules · audit log · "open as owner" (impersonation, labelled and audited).

## 4. Hotel dashboard

`[x]` Overview · Risk list · Employee · What-if · Roster · Closed loop · Tasks · Voice · Dispatch · Worker preview · Setup · Admin (built in earlier rounds).

## 5. Inventory `[b]`

| Flow | Detail |
|---|---|
| Catalog | items with category (linen, amenities, cleaning, F&B dry store, maintenance spares), unit, unit cost, par level, reorder point, supplier, lead time |
| Locations | main store + floor pantries / kitchen store; stock per location |
| Ledger | every movement: receive, issue, transfer, adjust (count), waste/damage, return; who, when, why, linked job/room |
| Requisition | worker or department requests → storekeeper approves (full/partial) → issue moves stock |
| Low stock | below reorder point → alert |
| Forecast-aware reorder | suggested quantity = par scaled by next-7-day forecast occupancy − on hand − on order (the HOI differentiator: inventory follows the same forecast as the roster) |
| Purchasing | draft PO → approve → sent → receive (GRN, partial receipts) → closed |
| Stock count | cycle count per location, variance and value, posts adjustments |
| Wastage | damaged or expired, with reason |
| Analytics | stock value, consumption by department, cost per occupied room (CPOR), top movers, wastage % |
| Linen par | linen on hand vs rooms × par (e.g. 3 par) |
| `[r]` | barcode/QR scanning, GST e-invoice, supplier portal, batch expiry for F&B, multi-property transfers |

## 6. Employee app `[b]`

My day (today's shift, week schedule from the roster) · Jobs (ping with countdown, accept/decline, before/after photo) · Supplies (request items, track status) · My tasks (backend tasks assigned to me, ack/done).

## 7. Marketing website `[b]`

Hero · problem · feature sections (retention, roster, dispatch + photo proof, inventory, forecast) · how the closed loop works · comparison by category (cited) · plans (no prices yet) · FAQ (data, privacy, synthetic demo) · CTA to the live demo · responsive + motion · same design language as the app.

## 8. Roadmap `[r]`

OIDC/SSO login · billing · Telegram/WhatsApp push for pings · PMS integration (room status) · payroll/attendance · native mobile app · multi-property roll-up dashboards · real-data pilot.
