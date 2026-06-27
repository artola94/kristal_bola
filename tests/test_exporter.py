"""Tests for the exporter module: sanitize_filename and SessionExporter."""

import csv
import json
from pathlib import Path

import pytest

from exporter import COLUMNS, SessionExporter, sanitize_filename


class TestSanitizeFilename:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Bitcoin ETF", "bitcoin-etf"),
            ("AI regulation", "ai-regulation"),
            ("Tech layoffs 2024", "tech-layoffs-2024"),
            ("Crypto!!!", "crypto"),
            ("  multiple   spaces  ", "multiple-spaces"),
            ("under_score", "under_score"),
            ("CamelCase", "camelcase"),
            ("a/b\\c:d", "a-b-c-d"),
        ],
    )
    def test_normal_cases(self, name, expected):
        assert sanitize_filename(name) == expected

    def test_empty_string_returns_fallback(self):
        assert sanitize_filename("") == "session"

    def test_only_special_chars_returns_fallback(self):
        assert sanitize_filename("!!!???...") == "session"

    def test_only_spaces_returns_fallback(self):
        assert sanitize_filename("   ") == "session"

    def test_unicode_alnum_preserved(self):
        # Python str.isalnum() is True for accented letters, so they are kept
        assert sanitize_filename("café") == "café"

    def test_no_leading_trailing_hyphens(self):
        assert sanitize_filename("---bitcoin---") == "bitcoin"


class TestSessionExporterCsv:
    def _sample_result(self, topic="Bitcoin ETF", score=0.5):
        return {
            "poll_timestamp": "2026-01-28T10:30:00Z",
            "topic": topic,
            "overall_sentiment": "positive",
            "sentiment_score": score,
            "positive_percentage": 55.0,
            "negative_percentage": 20.0,
            "neutral_percentage": 25.0,
            "key_narratives": ["institutional adoption", "SEC approval"],
            "influencers": ["@user1", "@user2"],
            "anomalies_or_shifts": "none",
            "raw_summary": "Optimistic sentiment.",
            "window_minutes": 15,
        }

    def test_start_session_creates_file_with_header(self, tmp_path):
        exp = SessionExporter(output_dir=str(tmp_path), format="csv")
        path = exp.start_session(["Bitcoin ETF"])
        assert Path(path).exists()
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
        assert header == COLUMNS

    def test_append_writes_row(self, tmp_path):
        exp = SessionExporter(output_dir=str(tmp_path), format="csv")
        path = exp.start_session(["Bitcoin ETF"])
        exp.append(self._sample_result())
        exp.close()
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["topic"] == "Bitcoin ETF"
        assert float(rows[0]["sentiment_score"]) == 0.5

    def test_lists_serialized_as_json(self, tmp_path):
        exp = SessionExporter(output_dir=str(tmp_path), format="csv")
        path = exp.start_session(["Bitcoin ETF"])
        exp.append(self._sample_result())
        exp.close()
        with open(path, newline="", encoding="utf-8") as f:
            row = next(csv.DictReader(f))
        assert json.loads(row["key_narratives"]) == ["institutional adoption", "SEC approval"]
        assert json.loads(row["influencers"]) == ["@user1", "@user2"]

    def test_close_returns_filepath(self, tmp_path):
        exp = SessionExporter(output_dir=str(tmp_path), format="csv")
        exp.start_session(["Bitcoin ETF"])
        exp.append(self._sample_result())
        path = exp.close()
        assert path is not None
        assert Path(path).exists()

    def test_close_resets_session(self, tmp_path):
        exp = SessionExporter(output_dir=str(tmp_path), format="csv")
        exp.start_session(["Bitcoin ETF"])
        exp.append(self._sample_result())
        exp.close()
        assert exp.is_active is False
        assert exp.filepath is None
        assert exp.row_count == 0

    def test_close_without_session_returns_none(self):
        exp = SessionExporter()
        assert exp.close() is None

    def test_append_without_session_warns(self, tmp_path, caplog):
        exp = SessionExporter(output_dir=str(tmp_path), format="csv")
        exp.append(self._sample_result())
        assert exp.row_count == 0
        assert any("No active session" in r.message for r in caplog.records)

    def test_multiple_rows(self, tmp_path):
        exp = SessionExporter(output_dir=str(tmp_path), format="csv")
        path = exp.start_session(["Bitcoin ETF", "Ethereum"])
        for i in range(5):
            exp.append(self._sample_result(score=i * 0.1))
        exp.close()
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 5
        assert exp.row_count == 0  # reset after close

    def test_single_topic_filename(self, tmp_path):
        exp = SessionExporter(output_dir=str(tmp_path), format="csv")
        path = exp.start_session(["Bitcoin ETF"])
        exp.close()
        name = Path(path).name
        assert name.startswith("bitcoin-etf_session_")
        assert name.endswith(".csv")

    def test_multi_topic_filename(self, tmp_path):
        exp = SessionExporter(output_dir=str(tmp_path), format="csv")
        path = exp.start_session(["Bitcoin ETF", "Ethereum"])
        exp.close()
        name = Path(path).name
        assert name.startswith("multi_session_")
        assert name.endswith(".csv")

    def test_start_session_when_active_closes_previous(self, tmp_path):
        exp = SessionExporter(output_dir=str(tmp_path), format="csv")
        first = exp.start_session(["Bitcoin ETF"])
        exp.append(self._sample_result())
        second = exp.start_session(["Ethereum"])
        assert Path(first).exists()
        assert Path(second).exists()
        assert first != second
        exp.close()


class TestSessionExporterParquet:
    def test_parquet_buffer_and_write(self, tmp_path):
        pytest.importorskip("pyarrow")
        exp = SessionExporter(output_dir=str(tmp_path), format="parquet")
        path = exp.start_session(["Bitcoin ETF"])
        exp.append(
            {
                "poll_timestamp": "2026-01-28T10:30:00Z",
                "topic": "Bitcoin ETF",
                "overall_sentiment": "positive",
                "sentiment_score": 0.5,
                "positive_percentage": 55.0,
                "negative_percentage": 20.0,
                "neutral_percentage": 25.0,
                "key_narratives": '["a"]',
                "influencers": '["@x"]',
                "anomalies_or_shifts": "none",
                "raw_summary": "ok",
                "window_minutes": 15,
            }
        )
        exp.close()
        assert Path(path).exists()
        import pyarrow.parquet as pq

        table = pq.read_table(path)
        assert table.num_rows == 1
        assert table.column_names == COLUMNS

    def test_parquet_fallback_to_csv_without_pyarrow(self, tmp_path, monkeypatch):
        """If pyarrow is missing, exporter falls back to CSV."""
        # Simulate pyarrow not importable
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "pyarrow" or name.startswith("pyarrow."):
                raise ImportError("simulated")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        exp = SessionExporter(output_dir=str(tmp_path), format="parquet")
        exp.start_session(["Bitcoin ETF"])
        exp.append(
            {
                "poll_timestamp": "2026-01-28T10:30:00Z",
                "topic": "Bitcoin ETF",
                "overall_sentiment": "positive",
                "sentiment_score": 0.5,
                "positive_percentage": 55.0,
                "negative_percentage": 20.0,
                "neutral_percentage": 25.0,
                "key_narratives": '["a"]',
                "influencers": '["@x"]',
                "anomalies_or_shifts": "none",
                "raw_summary": "ok",
                "window_minutes": 15,
            }
        )
        path = exp.close()
        # After fallback, close() returns the .csv path
        assert Path(path).suffix == ".csv"
        assert Path(path).exists()


class TestExporterProperties:
    def test_is_active_false_before_start(self):
        exp = SessionExporter()
        assert exp.is_active is False

    def test_is_active_true_after_start(self, tmp_path):
        exp = SessionExporter(output_dir=str(tmp_path), format="csv")
        exp.start_session(["Bitcoin ETF"])
        assert exp.is_active is True
        exp.close()

    def test_row_count_tracks_appends(self, tmp_path):
        exp = SessionExporter(output_dir=str(tmp_path), format="csv")
        exp.start_session(["Bitcoin ETF"])
        r = {
            "poll_timestamp": "t",
            "topic": "x",
            "overall_sentiment": "positive",
            "sentiment_score": 0.1,
            "positive_percentage": 50.0,
            "negative_percentage": 25.0,
            "neutral_percentage": 25.0,
            "key_narratives": [],
            "influencers": [],
            "anomalies_or_shifts": "",
            "raw_summary": "",
            "window_minutes": 15,
        }
        for _ in range(3):
            exp.append(r)
        assert exp.row_count == 3
