"""Tests for MonitorConfig and SentimentMonitor (no network, no xAI client)."""

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from sentiment import MonitorConfig, SentimentAnalysis, SentimentMonitor


class TestMonitorConfigDefaults:
    def test_defaults(self):
        c = MonitorConfig()
        assert c.poll_interval_seconds == 300
        assert c.window_minutes == 15
        assert c.max_retries == 3
        assert c.retry_delay_seconds == 30
        assert c.model == "grok-4-1-fast-reasoning"
        assert c.max_workers == 4
        assert c.mongodb_uri is None
        assert c.mongodb_db == "kristal_bola"
        assert c.mongodb_collection == "sentiment_polls"

    @pytest.mark.parametrize(
        "env,value,attr",
        [
            ("KRISTAL_POLL_INTERVAL", "60", "poll_interval_seconds"),
            ("KRISTAL_WINDOW_MINUTES", "45", "window_minutes"),
            ("KRISTAL_MAX_RETRIES", "5", "max_retries"),
            ("KRISTAL_RETRY_DELAY", "10", "retry_delay_seconds"),
            ("KRISTAL_MODEL", "grok-beta", "model"),
            ("KRISTAL_MAX_WORKERS", "8", "max_workers"),
            ("KRISTAL_MONGODB_DB", "mydb", "mongodb_db"),
            ("KRISTAL_MONGODB_COLLECTION", "mycol", "mongodb_collection"),
        ],
    )
    def test_from_env_reads_env_vars(self, monkeypatch, env, value, attr):
        monkeypatch.setenv(env, value)
        c = MonitorConfig.from_env()
        assert getattr(c, attr) == type(getattr(MonitorConfig(), attr))(value)

    def test_from_env_reads_mongodb_uri(self, monkeypatch):
        monkeypatch.setenv("KRISTAL_MONGODB_URI", "mongodb://localhost:27017")
        assert MonitorConfig.from_env().mongodb_uri == "mongodb://localhost:27017"

    def test_from_env_defaults_when_unset(self, monkeypatch):
        for k in [
            "KRISTAL_POLL_INTERVAL",
            "KRISTAL_WINDOW_MINUTES",
            "KRISTAL_MAX_RETRIES",
            "KRISTAL_RETRY_DELAY",
            "KRISTAL_MODEL",
            "KRISTAL_MAX_WORKERS",
            "KRISTAL_MONGODB_URI",
            "KRISTAL_MONGODB_DB",
            "KRISTAL_MONGODB_COLLECTION",
        ]:
            monkeypatch.delenv(k, raising=False)
        c = MonitorConfig.from_env()
        assert c == MonitorConfig()


class TestMonitorConfigValidation:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("poll_interval_seconds", 0),
            ("poll_interval_seconds", -5),
            ("window_minutes", 0),
            ("max_retries", 0),
            ("retry_delay_seconds", -1),
            ("max_workers", 0),
        ],
    )
    def test_invalid_values_raise(self, field, value):
        with pytest.raises(ValueError, match="Invalid MonitorConfig"):
            MonitorConfig(**{field: value})

    def test_error_message_names_field(self):
        with pytest.raises(ValueError, match="poll_interval_seconds"):
            MonitorConfig(poll_interval_seconds=0)

    def test_boundary_values_pass(self):
        c = MonitorConfig(
            poll_interval_seconds=1,
            window_minutes=1,
            max_retries=1,
            retry_delay_seconds=0,
            max_workers=1,
        )
        assert c.poll_interval_seconds == 1

    def test_from_env_bad_integer_raises_clear_error(self, monkeypatch):
        monkeypatch.setenv("KRISTAL_POLL_INTERVAL", "not-a-number")
        with pytest.raises(ValueError, match="KRISTAL_POLL_INTERVAL"):
            MonitorConfig.from_env()

    def test_from_env_negative_value_rejected(self, monkeypatch):
        monkeypatch.setenv("KRISTAL_WINDOW_MINUTES", "-10")
        with pytest.raises(ValueError, match="window_minutes"):
            MonitorConfig.from_env()


class TestTopicManagement:
    def test_add_topic(self):
        m = SentimentMonitor()
        m.add_topic("Bitcoin")
        assert m.list_topics() == ["Bitcoin"]

    def test_add_topic_dedup(self):
        m = SentimentMonitor()
        m.add_topic("Bitcoin")
        m.add_topic("Bitcoin")
        assert m.list_topics() == ["Bitcoin"]

    def test_add_multiple_topics(self):
        m = SentimentMonitor()
        m.add_topic("Bitcoin")
        m.add_topic("Ethereum")
        assert m.list_topics() == ["Bitcoin", "Ethereum"]

    def test_remove_topic(self):
        m = SentimentMonitor()
        m.add_topic("Bitcoin")
        assert m.remove_topic("Bitcoin") is True
        assert m.list_topics() == []

    def test_remove_nonexistent_topic(self):
        m = SentimentMonitor()
        assert m.remove_topic("Bitcoin") is False

    def test_list_topics_returns_copy(self):
        m = SentimentMonitor()
        m.add_topic("Bitcoin")
        lst = m.list_topics()
        lst.append("mutated")
        assert m.list_topics() == ["Bitcoin"]


class TestCallbacks:
    def test_clear_callbacks(self):
        m = SentimentMonitor()
        m.on_result(lambda d: None)
        m.on_result(lambda d: None)
        assert len(m._callbacks) == 2
        m.clear_callbacks()
        assert len(m._callbacks) == 0

    def test_clear_callbacks_idempotent(self):
        m = SentimentMonitor()
        m.clear_callbacks()
        m.clear_callbacks()
        assert len(m._callbacks) == 0

    def test_callback_invoked(self):
        m = SentimentMonitor()
        received = []
        m.on_result(lambda d: received.append(d))
        m._notify_callbacks({"topic": "test"})
        assert received == [{"topic": "test"}]

    def test_callback_exception_isolated(self):
        """A failing callback must not block subsequent callbacks."""
        m = SentimentMonitor()
        ok = []
        m.on_result(lambda d: (_ for _ in ()).throw(RuntimeError("boom")))
        m.on_result(lambda d: ok.append(d))
        m._notify_callbacks({"topic": "test"})
        assert ok == [{"topic": "test"}]


class TestConcurrency:
    """Callbacks must be invoked safely under concurrent poll_all_topics.

    We mock poll_with_retry so it sleeps briefly (simulating API latency) and
    verify results are collected from multiple threads without loss.
    """

    def test_poll_all_topics_parallel(self, monkeypatch):
        m = SentimentMonitor()
        for t in ["a", "b", "c", "d"]:
            m.add_topic(t)

        def fake_poll(topic):
            time.sleep(0.05)
            return {"topic": topic, "sentiment_score": 0.0, "overall_sentiment": "neutral"}

        monkeypatch.setattr(m, "poll_with_retry", fake_poll)

        start = time.perf_counter()
        results = m.poll_all_topics()
        elapsed = time.perf_counter() - start

        # 4 topics x 0.05s in parallel with 4 workers -> ~0.05s, not ~0.20s
        assert len(results) == 4
        assert elapsed < 0.15, f"expected parallel, took {elapsed:.3f}s"
        assert {r["topic"] for r in results} == {"a", "b", "c", "d"}

    def test_single_topic_skips_pool(self, monkeypatch):
        m = SentimentMonitor()
        m.add_topic("solo")
        called = []
        monkeypatch.setattr(
            m,
            "poll_with_retry",
            lambda t: (
                called.append(t)
                or {"topic": t, "sentiment_score": 0.0, "overall_sentiment": "neutral"}
            ),
        )
        results = m.poll_all_topics()
        assert results == [
            {"topic": "solo", "sentiment_score": 0.0, "overall_sentiment": "neutral"}
        ]
        assert called == ["solo"]

    def test_empty_topics_returns_empty(self):
        m = SentimentMonitor()
        assert m.poll_all_topics() == []

    def test_thread_crash_isolated(self, monkeypatch):
        m = SentimentMonitor()
        m.add_topic("good")
        m.add_topic("bad")

        def fake_poll(topic):
            if topic == "bad":
                raise RuntimeError("crash")
            return {"topic": topic, "sentiment_score": 0.0, "overall_sentiment": "neutral"}

        monkeypatch.setattr(m, "poll_with_retry", fake_poll)
        results = m.poll_all_topics()
        assert len(results) == 1
        assert results[0]["topic"] == "good"


class TestBackoff:
    """Exponential backoff with jitter, interruptible via stop event."""

    def _monitor(self, **cfg):
        config = MonitorConfig(retry_delay_seconds=30, max_retries=3, **cfg)
        return SentimentMonitor(config)

    def test_backoff_delay_doubles_per_attempt(self, monkeypatch):
        monkeypatch.setattr("sentiment.random.uniform", lambda a, b: 1.0)
        m = self._monitor()
        assert m._backoff_delay(1) == 30
        assert m._backoff_delay(2) == 60
        assert m._backoff_delay(3) == 120

    def test_backoff_delay_has_jitter(self):
        m = self._monitor()
        delays = {m._backoff_delay(1) for _ in range(20)}
        # Jitter ±25% around 30 -> values in [22.5, 37.5], not all identical
        assert len(delays) > 1
        assert all(22.5 <= d <= 37.5 for d in delays)

    def test_retry_waits_via_stop_event_not_sleep(self, monkeypatch):
        m = self._monitor()
        m.poll_topic = MagicMock(side_effect=RuntimeError("api down"))
        monkeypatch.setattr("sentiment.random.uniform", lambda a, b: 1.0)
        waited = []
        monkeypatch.setattr(m._stop_event, "wait", lambda timeout: waited.append(timeout) or False)
        assert m.poll_with_retry("t") is None
        assert waited == [30, 60]  # no wait after the final attempt
        assert m.poll_topic.call_count == 3

    def test_stop_during_backoff_aborts_retries(self, monkeypatch):
        m = self._monitor()
        m.poll_topic = MagicMock(side_effect=RuntimeError("api down"))
        monkeypatch.setattr(m._stop_event, "wait", lambda timeout: True)
        assert m.poll_with_retry("t") is None
        # Aborted after the first failure instead of exhausting all retries
        assert m.poll_topic.call_count == 1

    def test_success_on_second_attempt(self, monkeypatch):
        m = self._monitor()
        good = {"topic": "t", "sentiment_score": 0.0}
        m.poll_topic = MagicMock(side_effect=[RuntimeError("flaky"), good])
        monkeypatch.setattr(m._stop_event, "wait", lambda timeout: False)
        assert m.poll_with_retry("t") == good
        assert m.poll_topic.call_count == 2


class TestStopEvent:
    """The stop_event enables reactive shutdown (no 1s sleep polling)."""

    def test_stop_sets_event(self):
        m = SentimentMonitor()
        assert m._stop_event.is_set() is False
        m.stop()
        assert m._stop_event.is_set() is True
        assert m.running is False

    def test_event_wait_returns_immediately_when_set(self):
        m = SentimentMonitor()
        m._stop_event.set()
        # If broken (busy loop), this would block; with Event it returns True at once
        assert m._stop_event.wait(timeout=2.0) is True

    def test_event_wait_times_out_when_not_set(self):
        m = SentimentMonitor()
        start = time.perf_counter()
        assert m._stop_event.wait(timeout=0.1) is False
        assert time.perf_counter() - start >= 0.1


class TestPollTopic:
    """poll_topic must pass from_date to x_search (server-side time filtering)."""

    def _build_monitor_with_mock_client(self, window_minutes=15):
        m = SentimentMonitor(MonitorConfig(window_minutes=window_minutes))
        m.client = MagicMock()
        captured = {}

        def fake_create(model, tools, response_format, temperature):
            captured["tools"] = tools
            captured["model"] = model
            chat = MagicMock()
            response = MagicMock()
            response.content = SentimentAnalysis(
                topic="test",
                timestamp="2026-01-01T00:00:00Z",
                overall_sentiment="neutral",
                sentiment_score=0.0,
                positive_percentage=33.0,
                negative_percentage=33.0,
                neutral_percentage=34.0,
                key_narratives=["a"],
                influencers=["@x"],
                anomalies_or_shifts="none",
                raw_summary="ok",
            ).model_dump_json()
            chat.sample.return_value = response
            return chat

        m.client.chat.create = fake_create
        return m, captured

    def test_passes_from_date_to_x_search(self):
        m, captured = self._build_monitor_with_mock_client(window_minutes=15)
        before = datetime.now(timezone.utc)
        m.poll_topic("test")
        after = datetime.now(timezone.utc)

        assert len(captured["tools"]) == 1
        tool = captured["tools"][0]
        assert hasattr(tool, "x_search")
        ts = tool.x_search.from_date
        assert ts.seconds > 0
        # from_date should be ~15 minutes before now, within tolerance
        delta_before = before.timestamp() - ts.seconds
        delta_after = after.timestamp() - ts.seconds
        assert 14 * 60 <= delta_before <= 16 * 60
        assert 14 * 60 <= delta_after <= 16 * 60

    def test_from_date_reflects_window_minutes(self):
        m, captured = self._build_monitor_with_mock_client(window_minutes=60)
        m.poll_topic("test")
        ts = captured["tools"][0].x_search.from_date
        delta = datetime.now(timezone.utc).timestamp() - ts.seconds
        assert 59 * 60 <= delta <= 61 * 60

    def test_uses_configured_model(self):
        m, captured = self._build_monitor_with_mock_client()
        m.config.model = "grok-custom"
        m.poll_topic("test")
        assert captured["model"] == "grok-custom"

    def test_returns_doc_with_poll_metadata(self):
        m, _ = self._build_monitor_with_mock_client(window_minutes=30)
        doc = m.poll_topic("test")
        assert doc["window_minutes"] == 30
        assert doc["poll_timestamp"].endswith("Z")
        assert "+00:00Z" not in doc["poll_timestamp"]
        assert doc["topic"] == "test"
        assert "sentiment_score" in doc

    def test_no_client_returns_none(self):
        m = SentimentMonitor()
        assert m.poll_topic("test") is None

    def test_validation_error_propagates(self):
        """poll_topic must raise ValidationError so poll_with_retry does not retry."""
        m = SentimentMonitor()
        m.client = MagicMock()

        def fake_create(model, tools, response_format, temperature):
            chat = MagicMock()
            response = MagicMock()
            response.content = '{"topic": "broken"}'  # missing required fields
            chat.sample.return_value = response
            return chat

        m.client.chat.create = fake_create
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            m.poll_topic("test")
