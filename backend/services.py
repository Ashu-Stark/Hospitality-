"""The only bridge to ml/: forecast.predict, attrition.score, attrition.rescore, voice.extract
(loaded from ml/artifacts; nothing is trained here, nothing reads ml/data/internal/), called
through their GUARDED versions (ml/forecast/guarded.py, ml/attrition/guarded.py; shared checks in
ml/guardrails.py), plus the guarded workload interface (ml/models/workload_api.py) and the
REAL-data cancellation interface (ml/realdata/hotel_alerts/api.py). Every forecast, score and
rescore therefore carries `confidence` and `checks`.

ModelService calls the real interfaces; MockService (MOCK=1) serves ml/data/mocks/*.json through
the same result types, so the frontend can run without the models.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Protocol

from backend.config import ML_ARTIFACTS, MOCKS_DIR, HotelData, hotel_data
from backend.schemas import (
    AttritionScore,
    BookingScores,
    Check,
    ForecastResult,
    GuardedAttritionScore,
    GuardedForecast,
    GuardedRescore,
    HeroInfo,
    LiveSignals,
    ModelVersion,
    RescoreResult,
    VoiceResult,
    WorkloadForecast,
)

MOCK_CHECK = Check(name="mock_mode", status="warn",
                   detail="MOCK mode: canned outputs from ml/data/mocks; prediction checks not run")


class NotAvailable(LookupError):
    """The request cannot be answered in this mode (e.g. MOCK has no such employee)."""


class Service(Protocol):
    def forecast(self, start: date, end: date, as_of: date | None) -> ForecastResult: ...

    def latest_week(self) -> date: ...

    def score(self, week_start: date | None, employee_ids: list[str] | None,
              live: LiveSignals | None = None, fallback_to_demo: bool = True,
              ) -> list[AttritionScore]: ...

    def rescore(self, employee_id: str, overrides: dict, week_start: date | None,
                protected_weekends_off: int | None) -> RescoreResult: ...

    def heroes(self) -> list[HeroInfo]: ...

    def voice(self, audio_path: Path) -> VoiceResult: ...

    def workload(self, week_start: date | None) -> WorkloadForecast: ...

    def cancellation(self, bookings: list[dict], as_of: date) -> BookingScores: ...


def model_versions(artifacts: Path = ML_ARTIFACTS) -> list[ModelVersion]:
    out = []
    for d in sorted(p for p in artifacts.glob("*/*") if (p / "model.joblib").exists()):
        h = d / "dataset_hash.json"
        sha = json.loads(h.read_text("utf-8"))["combined_sha256"] if h.exists() else ""
        out.append(ModelVersion(name=d.parent.name, version=d.name, dataset_sha256=sha))
    return out


class ModelService:
    """The trained artifacts applied to one hotel's SYNTHETIC data (HOI_HOTEL_DATA; models are
    never retrained per hotel: the feature columns are identical)."""

    def __init__(self, hotel: str | None = None) -> None:
        self.hotel: HotelData = hotel_data(hotel)

    def forecast(self, start: date, end: date, as_of: date | None) -> GuardedForecast:
        from ml.forecast import guarded

        return guarded.predict(start, end, as_of, data_dir=self.hotel.data_dir,
                               rooms=self.hotel.rooms)

    def latest_week(self) -> date:
        from ml import attrition

        return attrition.api.latest_week(data_dir=self.hotel.data_dir)

    def score(self, week_start: date | None, employee_ids: list[str] | None,
              live: LiveSignals | None = None, fallback_to_demo: bool = True,
              ) -> list[GuardedAttritionScore]:
        """Live records first (per person, never mixed with demo data), then the SYNTHETIC demo
        tables for the people without a live score (fallback, labelled demo_synthetic)."""
        from ml.attrition import guarded

        def demo(ids: list[str] | None, note: str | None) -> list[GuardedAttritionScore]:
            out = guarded.score(week_start or self.latest_week(), ids,
                                data_dir=self.hotel.data_dir)
            if note:
                extra = Check(name="live_data", status="warn", detail=note)
                out = [s.model_copy(update={"checks": [*s.checks, extra]}) for s in out]
            return out

        if live is None:
            return demo(employee_ids, None)
        scores, skipped = guarded.score_live(live, None, employee_ids)
        if not scores:
            if not fallback_to_demo:
                raise ValueError("no live records to score yet")
            return demo(employee_ids, "no live HOI records yet for this week: scored from the "
                                      "SYNTHETIC demo data")
        if not fallback_to_demo:
            return scores
        done = {s.employee_id for s in scores}
        rest = ([e for e in employee_ids if e not in done] if employee_ids is not None
                else None)
        if rest == []:
            return scores
        week = week_start or self.latest_week()
        try:
            pool = demo(None, None)
        except ValueError:
            return scores
        wanted = set(rest) if rest is not None else None
        note = Check(name="live_data", status="warn",
                     detail="no live HOI record for this person: scored from the SYNTHETIC "
                            f"demo data (week {week})")
        return scores + [s.model_copy(update={"checks": [*s.checks, note]}) for s in pool
                         if s.employee_id not in done
                         and (wanted is None or s.employee_id in wanted)]

    def rescore(self, employee_id: str, overrides: dict, week_start: date | None,
                protected_weekends_off: int | None) -> RescoreResult:
        from ml import attrition

        merged = dict(overrides)
        if protected_weekends_off:
            merged = {**attrition.protected_weekends_off(employee_id, protected_weekends_off,
                                                         week_start,
                                                         data_dir=self.hotel.data_dir), **merged}
        from ml.attrition import guarded

        return guarded.rescore(employee_id, merged, week_start, data_dir=self.hotel.data_dir)

    def heroes(self) -> list[HeroInfo]:
        from ml import attrition

        return attrition.heroes(data_dir=self.hotel.data_dir)

    def voice(self, audio_path: Path) -> VoiceResult:
        from ml import voice

        return voice.extract(audio_path)

    def workload(self, week_start: date | None) -> WorkloadForecast:
        from ml.models import workload_api

        return workload_api.predict_next_week(self.hotel.data_dir, week_start)

    def cancellation(self, bookings: list[dict], as_of: date) -> BookingScores:
        from ml.realdata.hotel_alerts import api as cancellation

        return cancellation.score_bookings(bookings, as_of)


class MockService:
    """Serves the frontend mock files; only what they contain is available."""

    def __init__(self, mocks_dir: Path = MOCKS_DIR) -> None:
        self.dir = mocks_dir

    def _load(self, name: str) -> object:
        return json.loads((self.dir / f"{name}.json").read_text(encoding="utf-8"))

    def forecast(self, start: date, end: date, as_of: date | None) -> GuardedForecast:
        full = ForecastResult.model_validate(self._load("forecast_week"))
        days = [d for d in full.days if start <= d.date <= end]
        if not days:
            raise NotAvailable(f"MOCK forecast covers {full.days[0].date}..{full.days[-1].date}")
        return GuardedForecast(**full.model_dump(), rooms=hotel_data().rooms, confidence="low",
                               checks=[MOCK_CHECK], fallback_used=False).model_copy(
            update={"days": days})

    def latest_week(self) -> date:
        return AttritionScore.model_validate(self._load("attrition_scores")[0]).week_start

    def score(self, week_start: date | None, employee_ids: list[str] | None,
              live: LiveSignals | None = None, fallback_to_demo: bool = True,
              ) -> list[GuardedAttritionScore]:
        scores = [GuardedAttritionScore(**AttritionScore.model_validate(x).model_dump(),
                                        confidence="low", checks=[MOCK_CHECK])
                  for x in self._load("attrition_scores")]
        if week_start is not None and week_start != scores[0].week_start:
            raise NotAvailable(f"MOCK scores exist only for week {scores[0].week_start}")
        if employee_ids is None:
            return scores
        by_id = {s.employee_id: s for s in scores}
        missing = sorted(set(employee_ids) - set(by_id))
        if missing:
            raise NotAvailable(f"not in the MOCK scores: {missing}")
        return [by_id[e] for e in employee_ids]

    def rescore(self, employee_id: str, overrides: dict, week_start: date | None,
                protected_weekends_off: int | None) -> RescoreResult:
        r = RescoreResult.model_validate(self._load("rescore_sunita"))
        if employee_id != r.employee_id:
            raise NotAvailable(f"MOCK rescore exists only for {r.employee_id}")
        return GuardedRescore(**r.model_dump(), confidence="low", checks=[MOCK_CHECK])

    def heroes(self) -> list[HeroInfo]:
        return [HeroInfo.model_validate(x) for x in self._load("heroes")]

    def voice(self, audio_path: Path) -> VoiceResult:
        raise NotAvailable("voice is not mocked; run without MOCK=1")

    def workload(self, week_start: date | None) -> WorkloadForecast:
        raise NotAvailable("workload is not mocked; run without MOCK=1")

    def cancellation(self, bookings: list[dict], as_of: date) -> BookingScores:
        raise NotAvailable("cancellation scoring is not mocked; run without MOCK=1")
