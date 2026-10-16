# Data card: US OPM Federal Workforce Data (checked 2026-10-16; NOT used for training)

**Decision: not used.** The data cannot produce the required label without record linkage
that the release does not support. Nothing from it is stored in the repo.

## Source

- Site: https://data.opm.gov/explore-data/data/data-downloads (replaced FedScope in 2026;
  legacy files: https://www.opm.gov/data/datasets/).
- Programmatic access: `https://data.opm.gov/api/v1/files/{employment|accessions|separations}`,
  no key; monthly Parquet files. Current listings start in 2005 and run to August 2026.
- Employment (status) snapshot, September 2024: 2,313,216 records (one row per employee,
  `count` = 1), 64 columns, ~76 MB Parquet. Separations, October 2024: 18,598 records,
  69 columns.

## Terms of use

- The download page states the data excludes personally identifiable information, that some
  fields are redacted under OPM's Data Release Policy, and that it is meant for open access by
  analysts and researchers. The page footer shows "(c) 2026 Office of Personnel Management".
- **No explicit licence or public-domain statement was found** on the site or the API page.
  Works of the US federal government are generally not subject to copyright in the US
  (17 U.S.C. 105), but this was not confirmed on the site. The Data Release Policy PDF could not
  be read as text here (no PDF tool installed), so its exact terms are unverified.
- Had it been used: evaluation only, raw files kept in the gitignored `ml/data/realdata/raw/`,
  never redistributed.

## What the files contain

- Separation type: `separation_category` (e.g. QUIT 6,280; TERMINATION (EXPIRED APPT/OTHER)
  4,696; RETIREMENT - VOLUNTARY 3,306; TRANSFER OUT 2,592; OTHER 1,393; RIF 4 in October 2024).
  **Quits are identifiable** and can be separated from retirements and RIFs.
- Work fields that would be allowed: length of service, grade / pay plan, salary, occupational
  series / group / category, supervisory status, work schedule, agency (for agency size).
- Protected / personal fields present that would be excluded: `age_bracket`, `veteran_indicator`,
  education; the site notes sex is published in other views.
- **No person identifier** in either file (no employee id, no pseudonymous key).

## Why it was stopped

The requested label is "quit within 12 months of a snapshot". That needs each person in the
September snapshot to be linked to their separation record in the following 12 months. Without
an identifier the only option is matching on quasi-identifiers (service computation date +
agency sub-element + occupational series + duty station + grade). That is effectively a
re-identification technique, goes against the purpose of a privacy-protecting release, and
would give a noisy, unverifiable label. A case-control alternative (separations vs the next
snapshot) would answer a different question and leak post-snapshot information. The brief said
not to force it, so it was not used. The downloaded test files were deleted.
