# Data card: Hotel Booking Demand (used by the cancellation model)

| | |
|---|---|
| Provenance | **REAL** bookings (not synthetic) from two hotels in Portugal: a city hotel in Lisbon and a resort hotel in the Algarve |
| Citation | Antonio, N., Almeida, A. & Nunes, L. (2019). Hotel booking demand datasets. *Data in Brief* 22, 41-49. doi:10.1016/j.dib.2018.11.126 |
| Licence | CC BY 4.0 (attribution required; commercial use allowed) |
| Source URL (file used) | https://raw.githubusercontent.com/rfordatascience/tidytuesday/master/data/2020/2020-02-11/hotels.csv (TidyTuesday mirror of the paper's data) |
| SHA-256 | `7c2ae42a7353905ea136e5c2287f17c92c5435826598bfbb8491c6f0c7b1fc06` (checked on every run by `ml/realdata/sources.py`) |
| Accessed | downloaded 2026-10-13 by `python run.py realdata`; the same file was re-verified by hash on 2026-10-15 for this model |
| Size | 119,390 bookings x 32 columns (City 79,330; Resort 40,060) |
| Dates | arrivals 2015-07-01 .. 2017-08-31 |
| Label | `is_canceled` (1 = cancelled or no-show: 43,017 cancellations + 1,207 no-shows) |
| Stored | `ml/data/realdata/raw/hotels.csv` (gitignored; re-downloaded and hash-checked by the training command) |

## What we use and what we do not

Used (booking-time fields only): hotel type, lead time, arrival month and weekday, nights
(weekend / week), meal plan, market segment, distribution channel, reserved room type,
deposit type, customer type, repeat guest flag, previous cancellations, previous non-cancelled
bookings, days on the waiting list, average daily rate, number of special requests, and
whether an agent or a company booked it. Two prediction-time fields are derived: days to
arrival and days since the booking was made.

Not used, with reasons (numbers from the full file):

| Column | Why not |
|---|---|
| reservation_status, reservation_status_date | the outcome and its date |
| assigned_room_type | set at check-in: bookings whose room differs from the reserved one cancel 5.4% of the time vs 41.6% otherwise |
| required_car_parking_spaces | recorded at arrival: 0 of the 7,416 bookings with a parking space were cancelled |
| booking_changes | a final count, updated until arrival or cancellation |
| country | filled in at check-in for many bookings (a known leak in this file); also nationality, which HOI never uses |
| adults, children, babies | party and family composition: not used (project rule) |
| agent, company (ids) | Portuguese agent / company ids; only "booked through an agent / a company" is kept |
| arrival_date_year | a trend term that cannot extrapolate to new years |

The original paper notes that its fields were extracted from the booking change log as of the
day before arrival. So some kept fields (average daily rate, special requests) may show their
final value rather than the value at booking. An ablation without them is in RESULTS.md.

## Known limits

- Two Portuguese hotels with high cancellation rates (city 41.7%, resort 27.8%) and mostly
  foreign leisure guests. They are not Uttarakhand hill hotels, which have monsoon and Char Dham
  seasons and road closures.
- Arrival dates are final: if a booking was moved, the original date is lost.
- The "Non Refund" deposit type cancels 99.4% of the time in this file, the opposite of what
  the name suggests. This is a known quirk of the data. The model learns it, and it would not
  carry over to a hotel where non-refundable bookings really are non-refundable.
- Guest names or contact details are not in the file. No personal data is used or stored.
