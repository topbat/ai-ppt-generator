from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.pipeline.stages import qa_stages
from app.schemas.presentation import PresentationSpec, SlideSpec


class EmptyQuery:
    def filter_by(self, **kwargs):
        return self

    def all(self):
        return []


class EmptyDb:
    def query(self, model):
        return EmptyQuery()


@contextmanager
def _empty_db_session():
    yield EmptyDb()


def test_quality_report_contains_composition_and_key_slide_results(monkeypatch):
    monkeypatch.setattr(qa_stages, "db_session", _empty_db_session)
    spec = PresentationSpec(
        title="质量报告",
        total_pages=2,
        slides=[
            SlideSpec(page=1, type="cover", title="封面"),
            SlideSpec(page=2, type="title_content", title="正文"),
        ],
    )
    families = ["editorial"] * 3 + ["split"] * 3 + ["flow"] * 2 + ["data_focus"] * 2
    composition = {
        str(page): {
            "family": family,
            "fallback": False,
            "guard_issues": [],
        }
        for page, family in enumerate(families, start=1)
    }
    ctx = SimpleNamespace(
        target_pages=2,
        job_pk=9,
        data={
            "RENDER": {"render_notes": []},
            "FACT_CHECK": {"conflicts": 0},
            "MATCH": {"template_hit_rate": 1.0},
            "COMPOSE": {"composition_by_page": composition, "deck_issues": []},
            "KEY_SLIDE_DESIGN": {"selected": [3, 7], "applied": [3], "fallback": [7]},
        },
        _cache={"presentation_spec": spec},
    )

    report = qa_stages.build_report(ctx)

    assert report["composition"] == {
        "margin_violations": 0,
        "typography_violations": 0,
        "adjacent_fingerprint_duplicates": 0,
        "dominant_family_ratio": pytest.approx(0.3),
        "deck_rhythm_score": 100,
        "key_slides_selected": [3, 7],
        "key_slides_applied": [3],
        "key_slides_fallback": [7],
    }


def test_composition_score_deducts_explicit_guard_and_rhythm_issues(monkeypatch):
    monkeypatch.setattr(qa_stages, "db_session", _empty_db_session)
    spec = PresentationSpec(
        title="质量报告",
        total_pages=1,
        slides=[SlideSpec(page=1, type="title_content", title="正文")],
    )
    ctx = SimpleNamespace(
        target_pages=1,
        job_pk=9,
        data={
            "RENDER": {"render_notes": []},
            "COMPOSE": {
                "composition_by_page": {
                    "1": {
                        "family": "editorial",
                        "fallback": False,
                        "guard_issues": [
                            {"code": "margin_left"},
                            {"code": "font_too_small"},
                        ],
                    }
                },
                "deck_issues": [{"code": "adjacent_fingerprint_duplicate"}],
            },
        },
        _cache={"presentation_spec": spec},
    )

    report = qa_stages.build_report(ctx)

    assert report["composition"]["margin_violations"] == 1
    assert report["composition"]["typography_violations"] == 1
    assert report["composition"]["adjacent_fingerprint_duplicates"] == 1
    assert report["composition"]["deck_rhythm_score"] < 100


def test_short_deck_is_not_penalized_for_unavoidable_family_dominance(monkeypatch):
    monkeypatch.setattr(qa_stages, "db_session", _empty_db_session)
    spec = PresentationSpec(
        title="短文稿",
        total_pages=1,
        slides=[SlideSpec(page=1, type="title_content", title="正文")],
    )
    ctx = SimpleNamespace(
        target_pages=1,
        job_pk=9,
        data={
            "RENDER": {"render_notes": []},
            "COMPOSE": {
                "composition_by_page": {
                    "1": {"family": "editorial", "fallback": False, "guard_issues": []}
                },
                "deck_issues": [],
            },
        },
        _cache={"presentation_spec": spec},
    )

    report = qa_stages.build_report(ctx)

    assert report["composition"]["dominant_family_ratio"] == 1.0
    assert report["composition"]["deck_rhythm_score"] == 100
