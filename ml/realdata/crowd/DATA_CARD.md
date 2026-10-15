# Data card: Char Dham crowd model (REAL public data)

Everything here is **real public data** (unlike the rest of `ml/`, which is synthetic). No personal
data of any kind is used: only counts of pilgrims per shrine per day, dates and weather.
Accessed 2026-10-15. Raw files are re-fetched by `python -m ml.realdata.crowd.fetch` into
`ml/data/real/crowd/raw/` (gitignored: the sites' terms do not clearly allow redistribution).
Only small tables of extracted figures are committed, each row naming its source.

## Sources

| Key | Source | What we take | Licence / terms |
|---|---|---|---|
| `utdb_2021_2023`, `utdb_2024`, `utdb_2025` | Uttarakhand Tourism Development Board, "Tourist Statistics of Major Tourist Destinations" (2021-2023, 2024, 2025). https://uttarakhandtourism.gov.in/assets/pdf/Statistic21-23.pdf, .../assets/media/UTDB_media_1743665047Yearly_Report_Statistics_2024.pdf, .../assets/media/UTDB_media_1785820386Uttarakhand_Tourist_Footfall-2025.pdf | Annual visitors for 28 destinations (`utdb_annual.csv`) | Government publication, no open licence stated. Facts extracted with attribution; PDFs not redistributed. |
| `sdc_2024` | SDC Foundation (Dehradun), *Data Analysis of 100 Days of Uttarakhand Char Dham Yatra 2024, Mid Term Report* v1.0. https://www.sdcuk.in/wp-content/uploads/2024/08/DataAnalysisOf100DaysOfUttarakhandCharDhamYatra2024MidTermReport_SDC-Foundation.pdf | Weekly pilgrims per shrine, 10 May - 17 Aug 2024 (`sdc_2024_weekly.csv`; the weekly sums equal the report's totals exactly), peak days, nil-arrival days (Kedarnath 1-10 and 14 Aug 2024) | Public NGO report, no licence stated; figures (facts) with attribution. Compiled from the daily figures of the State Emergency Operation Centre (USDMA) and district authorities; SDC says it does not vouch for them. |
| news checkpoints | 746 rows from news reports quoting official figures (temple committee BKTC, SEOC, district administrations, Tourism Department). Main publishers of the 356 rows used: Amar Ujala 165, ETV Bharat 90, Garhwal Post 24, SDC Foundation 19, IANS / PTI / ANI copy in other outlets. URL, publisher and date on every row (`checkpoints.csv`). | Daily, season-to-date and closing totals per shrine; opening / closing dates | Facts quoted with attribution; no article text is stored (notes are short paraphrases). Every number was re-found in the raw page text by a script (`verified_raw`). |
| holidays | Department of Personnel & Training (DoPT), Government of India, office memoranda "Holidays to be observed in Central Government offices", 2021-2027 (documents.doptcirculars.nic.in; URL per row in `holidays_in.csv`) | Gazetted holidays; festival days from the restricted list | Public government circulars, no open licence found; attribute to DoPT. Delhi / New Delhi list (other offices: 14 compulsory + 3 chosen locally). Two later OMs moved a holiday (Muharram 2021, Bakrid 2026); the revised date is used. |
| school vacations | Delhi Directorate of Education circulars (2023, 2025) and news reports of state orders (`school_vacations.csv`, URL per row) | Summer vacation windows | Official circulars / news, facts with attribution. See caveats below. |
| events | News reports (`events_uk.csv`): Kanwar Yatra (Haridwar) 2022-2026, Valley of Flowers and Hemkund Sahib opening / closing 2022-2026 | Context only (not a model feature) | Dates and short facts only. See caveats below. |
| `open_meteo` | Open-Meteo Historical Weather API (ERA5 / ERA5-Land reanalysis), https://archive-api.open-meteo.com/v1/archive, daily 2021-01-01..2026-10-12 at each shrine's coordinates (from `portal/hoi_portal/seed/destinations.py`) | Precipitation, snowfall, max / min temperature | **CC BY 4.0**, "Weather data by Open-Meteo.com". The free API is for non-commercial use; a commercial deployment needs an Open-Meteo plan. |

**Looked at and not used.** The official registration portal (registrationandtouristcare.uk.gov.in)
publishes no counts and its policy forbids reproducing content without UTDB permission. IndiaStat
lists monthly district-wise tourist visits, but it is paywalled with reuse restrictions. A public
GitHub Uttarakhand tourism project has no licence, so its data and code were not used. No Kaggle
or data.gov.in dataset of daily Char Dham counts was found.

## What is real and what is estimated

**No public daily series of pilgrim counts exists.** The SEOC publishes daily figures to the
press, but no archive was found. The target is therefore built from real figures, as follows
(`target.py`):

1. Every real figure becomes an **anchor** on the season's cumulative curve. The anchors are:
   - 0 on the day before opening;
   - the SDC weekly totals (2024);
   - season-to-date figures from the news;
   - the closing total.
2. The total between two anchors is **real**.
3. How that total splits across the days in between is not observed. Officially reported
   single days and nil days are fixed. The remaining total is **spread evenly** over the other
   days (`basis = spread`, an ESTIMATED day value).
4. Training weights a spread day by min(1, 7 / interval length), so long intervals count less.

| | 2022 | 2023 | 2024 | 2025 | 2026 (to 7 Oct) |
|---|---|---|---|---|---|
| Real anchors per shrine | 12-14 | 12-13 | 17 (weekly SDC to 17 Aug, then news) | 10-12 | 9-11 |
| Days with an officially reported single-day count (all 4 shrines) | 13 | 40 | 14 + 11 nil days | 28 | 20 |

Every day value between reports is an estimate. Day-of-week and single-holiday effects inside an
interval therefore cannot be learned or tested. The 2024 weekly totals are the densest real data.

**Places covered:** the model covers Kedarnath, Badrinath, Gangotri and Yamunotri only. Every
other destination has only an annual UTDB total, which says nothing about which days are busy,
so those destinations keep the portal's existing estimate. No month-by-month curve was invented
for them.

## Cleaning rules

All rules are applied by the merge step and the target builder, and every drop is logged in
`metrics.json`.

- **Rows used.** Only rows whose number was found in the raw page (`verified_raw = yes`) are used.
- **Rows excluded, with the reason in `excluded_because`:**
  - registrations (not visits);
  - combined totals for several shrines;
  - rows the collectors flagged as SUSPECT or CONTRADICTS;
  - a weekly total filed as a single day;
  - **rounded lower bounds**, such as "over 16.5 lakh", or any cumulative figure of 100,000 or
    more that is an exact multiple of 1,000. The rule can drop a genuinely exact figure about
    0.1% of the time.
- **Contradicting figures.** Two figures contradict each other when a later cumulative figure is
  below an earlier one, when one day has two different figures, or when the implied daily rate
  exceeds 1.25 times the highest single day reported for that shrine. In each contradiction the
  lowest-priority figure is dropped, in this order (highest priority first):
  1. SEOC-based weekly totals;
  2. closing-day totals quoted from the yatra administration;
  3. season-to-date figures;
  4. UTDB annual totals.
- **Figures too close together.** A cumulative figure less than 3 days after the previous kept
  one is dropped, because news dates are only accurate to plus or minus one day.

### Conflicts between sources (recorded, not hidden)

- **UTDB annual totals disagree with in-season official figures for several shrine-years:**
  - Gangotri 2024: UTDB gives 5,40,190, but SEOC already had 5,98,723 by 17 Aug, and the closing
    total was 8,15,273.
  - Yamunotri 2024: UTDB gives 5,15,067; the closing total was 7,14,755.
  - Badrinath 2024: UTDB gives 17,74,264; the closing total was 14,35,341. The UTDB figure would
    imply about 22,000 pilgrims a day in the last 4 weeks.
  - Gangotri and Yamunotri 2023: the UTDB totals are below reported October figures.

  We therefore use a UTDB total only where it agrees with the in-season figures (Badrinath,
  Gangotri and Yamunotri 2025). Other conflicts:
  - Badrinath 2023 closing total: 18,34,729 or 18,39,591.
  - Gangotri 2022: 6,24,516 or 6,38,244 (news) against 7,81,961 (UTDB).
- **Season dates.** All 2022-2025 opening and closing dates are sourced. The 2026 closing dates
  for the four shrines were **not yet announced** on 2026-10-15; they are announced on
  Vijayadashami, 20 Oct 2026. They are filled with the custom seen in every sourced year
  (2023-2025):
  - Kedarnath and Yamunotri close on Bhai Duj (11 Nov 2026, from the DoPT list);
  - Gangotri closes the day before;
  - Badrinath gets Bhai Duj as a PROVISIONAL lower bound (it closed 3-33 days after Bhai Duj in
    2022-2025).

  These rows are marked EXPECTED or PROVISIONAL in `season_dates.csv`; replace them when the
  dates are announced. In 2022 the temples closed one day after the DoPT Bhai Duj date, so the
  rule can be a day out.
- **School vacations** (`school_vacations.csv`):
  - Coverage is 25 state-years across Delhi, UP (basic schools), Haryana, Rajasthan, Gujarat,
    Maharashtra and Uttarakhand (2023 only). Only Delhi 2023 and 2025 come from official
    circulars; the rest come from news, and some rows are marked LOW CONFIDENCE in the notes.
  - 10 state-years are missing, including Uttarakhand 2022 and 2024-2026.
  - The feature `school_vac` uses only Delhi, UP and Haryana. A missing state-year (Delhi 2021,
    2022 and 2027; UP 2021 and 2027; Haryana 2021, 2023 and 2027) uses an ASSUMED typical window,
    15 May - 30 Jun (`calendar_data.py`).
- **Events** (`events_uk.csv`; context only, not used by the model):
  - Valley of Flowers: 2023 is missing, and the 2022 and 2026 closing dates are blank. In 2025
    the valley closed from 7 Aug, reopening date unknown.
  - Some dates were worked out from an article's date and weekday; the notes say which.
  - Kanwar Yatra: the 2023 and 2024 end dates are the announced dates, not confirmed afterwards.
    Every end date is set to Sawan Shivratri.
  - Footfall figures in this file are the sources' own estimates, not counts.
- **Weather** is ERA5 reanalysis on a grid of about 9-25 km. The grid cell's elevation is
  3,044-3,667 m and differs from each temple's. Heavy rain is ASSUMED to mean 35 mm or more on
  the day or the day before; this is a road-closure proxy, not an IMD warning criterion.
- **COVID.** The 2021 season, which was restricted by COVID, is not used: all training seasons
  (2022 onward) are post-COVID, so no regime feature is needed.
