"""Tests for the SentimentAnalysis model: clamp validators and schema.

These reproduce the production bug from 2026-01-28 where Grok emitted
sentiment_score = -1.6 and the whole poll cycle was discarded.
"""

import pytest
from pydantic import ValidationError

from sentiment import SentimentAnalysis


def _valid_payload(**overrides):
    base = {
        "topic": "Bitcoin ETF",
        "timestamp": "2026-01-28T10:30:00Z",
        "overall_sentiment": "positive",
        "sentiment_score": 0.5,
        "positive_percentage": 55.0,
        "negative_percentage": 20.0,
        "neutral_percentage": 25.0,
        "key_narratives": ["institutional adoption", "SEC approval"],
        "influencers": ["@user1", "@user2"],
        "anomalies_or_shifts": "none",
        "raw_summary": "Optimistic sentiment around ETF approval.",
    }
    base.update(overrides)
    return base


class TestSentimentScoreClamp:
    """The production bug: scores outside [-1.0, 1.0] must be clamped, not rejected."""

    def test_below_minus_one_clamps_to_minus_one(self):
        r = SentimentAnalysis.model_validate(_valid_payload(sentiment_score=-1.6))
        assert r.sentiment_score == -1.0

    def test_well_below_minus_one_clamps_to_minus_one(self):
        r = SentimentAnalysis.model_validate(_valid_payload(sentiment_score=-3.5))
        assert r.sentiment_score == -1.0

    def test_above_plus_one_clamps_to_plus_one(self):
        r = SentimentAnalysis.model_validate(_valid_payload(sentiment_score=1.4))
        assert r.sentiment_score == 1.0

    def test_boundary_minus_one_passes(self):
        r = SentimentAnalysis.model_validate(_valid_payload(sentiment_score=-1.0))
        assert r.sentiment_score == -1.0

    def test_boundary_plus_one_passes(self):
        r = SentimentAnalysis.model_validate(_valid_payload(sentiment_score=1.0))
        assert r.sentiment_score == 1.0

    def test_zero_passes(self):
        r = SentimentAnalysis.model_validate(_valid_payload(sentiment_score=0.0))
        assert r.sentiment_score == 0.0

    def test_non_numeric_raises_validation_error(self):
        with pytest.raises(ValidationError):
            SentimentAnalysis.model_validate(_valid_payload(sentiment_score="not-a-number"))


class TestPercentageClamp:
    """Percentage fields must clamp to [0, 100]."""

    @pytest.mark.parametrize(
        "field", ["positive_percentage", "negative_percentage", "neutral_percentage"]
    )
    def test_above_100_clamps(self, field):
        r = SentimentAnalysis.model_validate(_valid_payload(**{field: 120.0}))
        assert getattr(r, field) == 100.0

    @pytest.mark.parametrize(
        "field", ["positive_percentage", "negative_percentage", "neutral_percentage"]
    )
    def test_below_zero_clamps(self, field):
        r = SentimentAnalysis.model_validate(_valid_payload(**{field: -10.0}))
        assert getattr(r, field) == 0.0

    def test_boundary_100_passes(self):
        r = SentimentAnalysis.model_validate(_valid_payload(positive_percentage=100.0))
        assert r.positive_percentage == 100.0

    def test_boundary_zero_passes(self):
        r = SentimentAnalysis.model_validate(_valid_payload(negative_percentage=0.0))
        assert r.negative_percentage == 0.0


class TestSchemaValidation:
    """Non-clampable schema violations must still raise ValidationError (not silently pass)."""

    def test_missing_required_field_raises(self):
        payload = _valid_payload()
        del payload["topic"]
        with pytest.raises(ValidationError):
            SentimentAnalysis.model_validate(payload)

    def test_invalid_literal_raises(self):
        payload = _valid_payload(overall_sentiment="bullish")  # not in Literal
        with pytest.raises(ValidationError):
            SentimentAnalysis.model_validate(payload)

    def test_too_many_narratives_raises(self):
        payload = _valid_payload(key_narratives=["a", "b", "c", "d", "e", "f"])
        with pytest.raises(ValidationError):
            SentimentAnalysis.model_validate(payload)

    def test_too_many_influencers_raises(self):
        payload = _valid_payload(influencers=["a", "b", "c", "d", "e", "f"])
        with pytest.raises(ValidationError):
            SentimentAnalysis.model_validate(payload)


class TestPercentageSumCheck:
    """Percentages should roughly sum to 100; large deviations log a warning."""

    def test_sum_100_no_warning(self, caplog):
        with caplog.at_level("WARNING", logger="sentiment"):
            SentimentAnalysis.model_validate(_valid_payload())
        assert not any("percentage sum" in r.message for r in caplog.records)

    def test_sum_within_tolerance_no_warning(self, caplog):
        with caplog.at_level("WARNING", logger="sentiment"):
            SentimentAnalysis.model_validate(
                _valid_payload(
                    positive_percentage=60.0, negative_percentage=20.0, neutral_percentage=17.0
                )
            )
        assert not any("percentage sum" in r.message for r in caplog.records)

    def test_sum_far_off_warns(self, caplog):
        with caplog.at_level("WARNING", logger="sentiment"):
            SentimentAnalysis.model_validate(
                _valid_payload(
                    positive_percentage=10.0, negative_percentage=10.0, neutral_percentage=10.0
                )
            )
        assert any("percentage sum 30.0 outside 95-105" in r.message for r in caplog.records)

    def test_warning_does_not_reject_payload(self):
        r = SentimentAnalysis.model_validate(
            _valid_payload(
                positive_percentage=10.0, negative_percentage=10.0, neutral_percentage=10.0
            )
        )
        assert r.positive_percentage == 10.0


class TestModelDump:
    """model_dump round-trips and preserves clamped values."""

    def test_dump_contains_clamped_score(self):
        r = SentimentAnalysis.model_validate(_valid_payload(sentiment_score=-1.6))
        d = r.model_dump()
        assert d["sentiment_score"] == -1.0
        assert d["topic"] == "Bitcoin ETF"
