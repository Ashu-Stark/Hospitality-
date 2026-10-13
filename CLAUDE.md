# Hospitality Operations Intelligence (HOI): project-wide rules

These rules apply to every folder in this repo: `ml/`, `backend/`, `platform_api/`, `portal/`, `dashboard/` and `website/`.

- **All data is SYNTHETIC.** It comes from the seeded generator in `ml/generator/`, using
  ASSUMED parameters. Label it as synthetic everywhere it appears: datasets, charts, tables,
  model cards, API responses, demo screens and docs. Never present it as real hotel data.
- **No personal or protected attributes, anywhere.** Employees are ids only. Never add, generate,
  store, display or use as a feature: real names, gender, age, religion, caste, health or family
  status. Exception: the fictional demo-hero display names (`ml/data/demo/hero_display_names.json`,
  `ml/data/mocks/heroes.json`) are permitted: scripted, synthetic, demo-only, and excluded from all
  training data.
- **`ml/data/internal/` is generator-only.** It holds hidden traits the simulator uses to create
  behaviour (e.g. latent_frustration, overtime_propensity). Model training, evaluation, backend
  and frontend code must never read it. It is gitignored and rebuilt by `python run.py generate`.
- Windows + PowerShell; no Makefiles or Linux-only commands. Do not add dependencies without
  telling the user first.

ML-specific details (layout, commands, data files, models, status): see [ml/CLAUDE.md](ml/CLAUDE.md).
Backend details (FastAPI + MongoDB: endpoints, roster solver, task engine, closed loop): see
[backend/CLAUDE.md](backend/CLAUDE.md). The backend uses only the ml entry points (forecast.predict,
attrition.score, attrition.rescore, voice.extract) loaded from ml/artifacts.

## Repository map

| Folder | What | Database (MongoDB Atlas) |
|---|---|---|
| `ml/` | Synthetic data generator, models, evaluation (team) | none (files in ml/data, ml/artifacts) |
| `backend/` | ML / ops API: forecast, attrition, CP-SAT roster, tasks, closed loop (team; deployed on Render) | `hoi_ops` |
| `platform_api/` | HOI platform API: accounts, tenants, dispatch, rooms, photos, inventory; serves the staff app and guest pages | `hoi_platform` |
| `portal/` | Uttarakhand tourism & hospitality portal (concept; not an official site) | `hoi_portal` |
| `dashboard/` | Streamlit manager dashboard | none (talks to the APIs) |
| `website/` | Static marketing site | none |

- `MONGODB_URI` is a secret: root `.env` (gitignored) locally, the host's secret store in deployment. Never commit or print it.
  Storage conventions: [docs/MONGODB.md](docs/MONGODB.md). Tests run offline on mongomock.
- One venv for everything at the repo root: `py -3.12 -m venv .venv`, then install each folder's requirements.

## Hotel onboarding by voice

An owner sets up a hotel by answering guided questions (Hindi / English / Hinglish, voice or
typed); a draft is saved as a property only after Confirm. Code in `backend/onboarding/`, screen
`dashboard/pages/15_Hotel_Setup.py` ("Hotel setup (voice)", not the workspace Setup page).
Details, endpoints, config files and eval: [docs/onboarding.md](docs/onboarding.md).

- Works with no keys and no audio (typed text + rule-based extractor + number normaliser). The
  LLM (Groq, `GROQ_API_KEY` from the environment only) and cloud speech-to-text run only when a
  config flag in `backend/onboarding/onboarding.yaml` allows it (default off) AND the owner ticks
  the consent box. Free AI tiers give no privacy guarantee: never send real names, salaries or
  staff data; tests and eval use SYNTHETIC text only, tests never call the network.
- Legal values (min rest hours, overtime multiplier, weekly off) always need verification and an
  explicit acknowledgement at Confirm; they depend on labour rules a qualified person must confirm.
- Hindi / Hinglish accuracy on real audio is untested; numbers are the most error-prone part.
  Eval scores (`python run.py eval-onboarding`) come from sentences we wrote, so they are optimistic.
- Every onboarding value is ASSUMED and in YAML (onboarding, templates, questions, numbers,
  lexicon); Hindi wording is a draft for the HM student. Templates reference the ml / backend work
  standards instead of copying them.
