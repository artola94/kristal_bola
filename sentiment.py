"""
Kristal Bola

Core module for monitoring social media sentiment on X using Grok API.
"""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator
from xai_sdk import Client
from xai_sdk.chat import system, user
from xai_sdk.tools import x_search

logger = logging.getLogger(__name__)
# Library best practice: avoid "No handlers" warnings when imported without run.py.
logger.addHandler(logging.NullHandler())


# DATA MODEL
class SentimentAnalysis(BaseModel):
    """Structured sentiment analysis result from Grok."""

    topic: str = Field(description="The topic being analyzed")
    timestamp: str = Field(description="UTC date/time of the analysis (ISO format)")
    overall_sentiment: Literal["positive", "negative", "neutral", "mixed"] = Field(
        description="Dominant overall sentiment"
    )
    sentiment_score: float = Field(
        description="Numeric score from -1.0 (very negative) to +1.0 (very positive)",
        ge=-1.0,
        le=1.0,
    )
    positive_percentage: float = Field(
        description="Estimated percentage of positive posts", ge=0, le=100
    )
    negative_percentage: float = Field(
        description="Estimated percentage of negative posts", ge=0, le=100
    )
    neutral_percentage: float = Field(
        description="Estimated percentage of neutral posts", ge=0, le=100
    )
    key_narratives: list[str] = Field(
        description="Key emerging narratives or themes (max 5)", max_length=5
    )
    influencers: list[str] = Field(
        description="Key users/influencers mentioned (top 3-5)", max_length=5
    )
    anomalies_or_shifts: str = Field(
        description="Any sudden change or anomaly detected in the last few hours"
    )
    raw_summary: str = Field(description="Brief 1-2 sentence summary of the current sentiment")

    @field_validator("sentiment_score", mode="before")
    @classmethod
    def _clamp_score(cls, v):
        """Clamp sentiment_score to [-1.0, 1.0]; Grok occasionally emits out-of-range values."""
        try:
            v = float(v)
        except (TypeError, ValueError):
            return v  # let pydantic raise a clear type error
        if v < -1.0:
            logger.warning(f"sentiment_score {v} below -1.0; clamped to -1.0")
            return -1.0
        if v > 1.0:
            logger.warning(f"sentiment_score {v} above 1.0; clamped to 1.0")
            return 1.0
        return v

    @field_validator(
        "positive_percentage", "negative_percentage", "neutral_percentage", mode="before"
    )
    @classmethod
    def _clamp_percent(cls, v):
        """Clamp percentage fields to [0, 100]."""
        try:
            v = float(v)
        except (TypeError, ValueError):
            return v
        if v < 0.0:
            logger.warning(f"percentage {v} below 0; clamped to 0")
            return 0.0
        if v > 100.0:
            logger.warning(f"percentage {v} above 100; clamped to 100")
            return 100.0
        return v


@dataclass
class MonitorConfig:
    """Configuration for a sentiment monitor."""

    poll_interval_seconds: int = 300
    window_minutes: int = 15
    max_retries: int = 3
    retry_delay_seconds: int = 30
    model: str = "grok-4-1-fast-reasoning"
    max_workers: int = 4
    mongodb_uri: Optional[str] = None
    mongodb_db: str = "kristal_bola"
    mongodb_collection: str = "sentiment_polls"

    @classmethod
    def from_env(cls) -> "MonitorConfig":
        """Create config from environment variables."""
        return cls(
            poll_interval_seconds=int(os.getenv("KRISTAL_POLL_INTERVAL", "300")),
            window_minutes=int(os.getenv("KRISTAL_WINDOW_MINUTES", "15")),
            max_retries=int(os.getenv("KRISTAL_MAX_RETRIES", "3")),
            retry_delay_seconds=int(os.getenv("KRISTAL_RETRY_DELAY", "30")),
            model=os.getenv("KRISTAL_MODEL", "grok-4-1-fast-reasoning"),
            max_workers=int(os.getenv("KRISTAL_MAX_WORKERS", "4")),
            mongodb_uri=os.getenv("KRISTAL_MONGODB_URI"),
            mongodb_db=os.getenv("KRISTAL_MONGODB_DB", "kristal_bola"),
            mongodb_collection=os.getenv("KRISTAL_MONGODB_COLLECTION", "sentiment_polls"),
        )


class SentimentMonitor:
    """
    Monitor for tracking sentiment on specific topics in X.

    Usage:
        monitor = SentimentMonitor(config)
        monitor.add_topic("Bitcoin ETF")
        monitor.start()
    """

    def __init__(self, config: Optional[MonitorConfig] = None):
        self.config = config or MonitorConfig.from_env()
        self.topics: list[str] = []
        self.client: Optional[Client] = None
        self.mongo_collection = None
        self.running = False
        self._callbacks: list[Callable[[dict], None]] = []
        self._stop_event = threading.Event()
        self._callback_lock = threading.Lock()

    def add_topic(self, topic: str) -> None:
        """Add a topic to monitor."""
        if topic not in self.topics:
            self.topics.append(topic)
            logger.info(f"Topic added: {topic}")

    def remove_topic(self, topic: str) -> bool:
        """Remove a topic from monitoring."""
        if topic in self.topics:
            self.topics.remove(topic)
            logger.info(f"Topic removed: {topic}")
            return True
        return False

    def list_topics(self) -> list[str]:
        """Return list of monitored topics."""
        return self.topics.copy()

    def on_result(self, callback: Callable[[dict], None]) -> None:
        """Register a callback for when results are received."""
        self._callbacks.append(callback)

    def clear_callbacks(self) -> None:
        """Clear all registered callbacks.

        Call before registering a new callback to avoid duplicate invocations
        across multiple start/stop cycles (e.g. interactive mode sessions).
        """
        self._callbacks = []

    def init_client(self) -> bool:
        """Initialize the xAI client."""
        api_key = os.getenv("XAI_API_KEY")
        if not api_key:
            logger.critical("XAI_API_KEY is not set.")
            return False
        self.client = Client(api_key=api_key)
        logger.info("xAI client initialized.")
        return True

    def init_mongodb(self) -> bool:
        """Initialize MongoDB connection if configured."""
        if not self.config.mongodb_uri:
            logger.warning("MongoDB URI not configured. Results will not be persisted.")
            return False
        try:
            from pymongo import MongoClient

            client = MongoClient(self.config.mongodb_uri)
            db = client[self.config.mongodb_db]
            self.mongo_collection = db[self.config.mongodb_collection]
            client.admin.command("ping")
            logger.info(
                f"Connected to MongoDB: {self.config.mongodb_db}.{self.config.mongodb_collection}"
            )
            return True
        except ImportError:
            logger.warning("pymongo not installed. Run: pip install pymongo")
            return False
        except Exception as e:
            logger.error(f"Error connecting to MongoDB: {e}")
            return False

    def save_result(self, doc: dict) -> bool:
        """Save result to MongoDB if available."""
        if self.mongo_collection is None:
            return False
        try:
            result = self.mongo_collection.insert_one(doc)
            logger.debug(f"Document inserted with _id: {result.inserted_id}")
            return True
        except Exception as e:
            logger.error(f"Error inserting into MongoDB: {e}")
            return False

    def poll_topic(self, topic: str) -> Optional[dict]:
        """Run a single sentiment poll for a topic."""
        if not self.client:
            logger.error("Client not initialized. Call init_client() first.")
            return None

        now = datetime.now(timezone.utc)
        since = now - timedelta(minutes=self.config.window_minutes)
        # x_search accepts a datetime for from_date (server-side Timestamp);
        # strip tzinfo to naive UTC for cross-version protobuf compatibility.
        from_date = since.replace(tzinfo=None)

        system_prompt = system(
            "You are an expert social media sentiment analyst. "
            "Analyze posts from X objectively and in a structured manner."
        )

        prompt = (
            f"Analyze posts on X about '{topic}' from the last "
            f"{self.config.window_minutes} minutes. "
            "Return the response in structured JSON format."
        )

        chat = self.client.chat.create(
            model=self.config.model,
            tools=[x_search(from_date=from_date)],
            response_format=SentimentAnalysis,
            temperature=0.2,
        )
        chat.append(system_prompt)
        chat.append(user(prompt))

        response = chat.sample()
        parsed = SentimentAnalysis.model_validate_json(response.content)
        doc = parsed.model_dump()
        doc["poll_timestamp"] = now.replace(tzinfo=None).isoformat() + "Z"
        doc["window_minutes"] = self.config.window_minutes

        return doc

    def poll_with_retry(self, topic: str) -> Optional[dict]:
        """Run poll_topic with retries on transient errors.

        Pydantic ValidationErrors are not retried: the same prompt will produce
        the same schema violation, so retrying only wastes API calls and time.
        """
        for attempt in range(1, self.config.max_retries + 1):
            try:
                return self.poll_topic(topic)
            except ValidationError as e:
                logger.error(f"[{topic}] Schema validation failed (not retryable): {e}")
                return None
            except Exception as e:
                logger.error(f"[{topic}] Attempt {attempt}/{self.config.max_retries} failed: {e}")
                if attempt < self.config.max_retries:
                    logger.info(f"Retrying in {self.config.retry_delay_seconds}s...")
                    time.sleep(self.config.retry_delay_seconds)
        logger.error(f"[{topic}] All retries failed.")
        return None

    def _notify_callbacks(self, result: dict) -> None:
        """Notify all registered callbacks."""
        for callback in self._callbacks:
            try:
                callback(result)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def poll_all_topics(self) -> list[dict]:
        """Poll all topics concurrently and return results.

        API calls run in parallel via a thread pool (bounded by
        ``config.max_workers``). Side effects (MongoDB save, callbacks) are
        serialized under ``_callback_lock`` to keep the exporter thread-safe.
        """
        if not self.topics:
            return []

        # Single topic: skip the pool overhead
        if len(self.topics) == 1:
            return self._poll_single(self.topics[0])

        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as pool:
            future_to_topic = {
                pool.submit(self.poll_with_retry, topic): topic for topic in self.topics
            }
            for future in as_completed(future_to_topic):
                topic = future_to_topic[future]
                try:
                    result = future.result()
                except Exception as e:
                    logger.error(f"[{topic}] Thread crashed: {e}")
                    result = None
                if result:
                    with self._callback_lock:
                        results.append(result)
                        self.save_result(result)
                        self._notify_callbacks(result)
                    logger.info(
                        f"[{topic}] Sentiment: {result['overall_sentiment']} (score: {result['sentiment_score']:.2f})"
                    )
                else:
                    logger.warning(f"[{topic}] No results.")
        return results

    def _poll_single(self, topic: str) -> list[dict]:
        """Poll a single topic without spawning a thread pool."""
        logger.info(f"Polling: {topic}")
        result = self.poll_with_retry(topic)
        if result:
            with self._callback_lock:
                self.save_result(result)
                self._notify_callbacks(result)
            logger.info(
                f"[{topic}] Sentiment: {result['overall_sentiment']} (score: {result['sentiment_score']:.2f})"
            )
            return [result]
        logger.warning(f"[{topic}] No results.")
        return []

    def stop(self) -> None:
        """Request the monitor to stop (reactive, wakes the wait loop)."""
        self.running = False
        self._stop_event.set()
        logger.info("Stop requested.")

    def run(self) -> None:
        """Start the monitoring loop."""
        if not self.topics:
            logger.error("No topics configured. Add topics before starting.")
            return

        if not self.client and not self.init_client():
            logger.error("Failed to initialize client. Aborting.")
            return

        self.init_mongodb()
        self.running = True
        self._stop_event.clear()

        logger.info("=== Kristal Bola - Sentiment Monitor ===")
        logger.info(f"Topics: {', '.join(self.topics)}")
        logger.info(f"Poll interval: {self.config.poll_interval_seconds}s")
        logger.info(f"Analysis window: {self.config.window_minutes} minutes")
        logger.info(f"Concurrency: {self.config.max_workers} workers")

        poll_count = 0
        while self.running:
            poll_count += 1
            logger.info(f"--- Poll cycle #{poll_count} ---")

            self.poll_all_topics()

            if self.running:
                logger.info(f"Waiting {self.config.poll_interval_seconds}s until next poll...")
                # Reactive wait: returns True immediately if stop() is called.
                if self._stop_event.wait(timeout=self.config.poll_interval_seconds):
                    break

        logger.info("Monitor stopped.")
