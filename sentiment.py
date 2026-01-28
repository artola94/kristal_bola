"""
Kristal Bola

Core module for monitoring social media sentiment on X using Grok API.
"""

import os
import time
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional, Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from xai_sdk import Client
from xai_sdk.chat import system, user
from xai_sdk.tools import x_search

logger = logging.getLogger(__name__)


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
        le=1.0
    )
    positive_percentage: float = Field(
        description="Estimated percentage of positive posts",
        ge=0,
        le=100
    )
    negative_percentage: float = Field(
        description="Estimated percentage of negative posts",
        ge=0,
        le=100
    )
    neutral_percentage: float = Field(
        description="Estimated percentage of neutral posts",
        ge=0,
        le=100
    )
    key_narratives: List[str] = Field(
        description="Key emerging narratives or themes (max 5)",
        max_length=5
    )
    influencers: List[str] = Field(
        description="Key users/influencers mentioned (top 3-5)",
        max_length=5
    )
    anomalies_or_shifts: str = Field(
        description="Any sudden change or anomaly detected in the last few hours"
    )
    raw_summary: str = Field(
        description="Brief 1-2 sentence summary of the current sentiment"
    )


@dataclass
class MonitorConfig:
    """Configuration for a sentiment monitor."""
    poll_interval_seconds: int = 300
    window_minutes: int = 15
    max_retries: int = 3
    retry_delay_seconds: int = 30
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
        self.topics: List[str] = []
        self.client: Optional[Client] = None
        self.mongo_collection = None
        self.running = False
        self._callbacks: List[Callable[[dict], None]] = []

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

    def list_topics(self) -> List[str]:
        """Return list of monitored topics."""
        return self.topics.copy()

    def on_result(self, callback: Callable[[dict], None]) -> None:
        """Register a callback for when results are received."""
        self._callbacks.append(callback)

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
            logger.info(f"Connected to MongoDB: {self.config.mongodb_db}.{self.config.mongodb_collection}")
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
        since_str = since.strftime("%Y-%m-%d_%H:%M:%S_UTC")

        system_prompt = system(
            "You are an expert social media sentiment analyst. "
            "Analyze posts from X objectively and in a structured manner."
        )

        prompt = (
            f"Analyze ONLY posts on X about '{topic}' from {since_str} to the present. "
            "Use x_keyword_search with the 'since:' parameter to strictly enforce the date range. "
            "Return the response in structured JSON format."
        )

        chat = self.client.chat.create(
            model="grok-4-1-fast-reasoning",
            tools=[x_search()],
            response_format=SentimentAnalysis,
            temperature=0.2,
        )
        chat.append(system_prompt)
        chat.append(user(prompt))

        response = chat.sample()
        parsed = SentimentAnalysis.model_validate_json(response.content)
        doc = parsed.model_dump()
        doc["poll_timestamp"] = now.isoformat() + "Z"
        doc["window_minutes"] = self.config.window_minutes

        return doc

    def poll_with_retry(self, topic: str) -> Optional[dict]:
        """Run poll_topic with retries."""
        for attempt in range(1, self.config.max_retries + 1):
            try:
                return self.poll_topic(topic)
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

    def poll_all_topics(self) -> List[dict]:
        """Poll all topics once and return results."""
        results = []
        for topic in self.topics:
            logger.info(f"Polling: {topic}")
            result = self.poll_with_retry(topic)
            if result:
                results.append(result)
                self.save_result(result)
                self._notify_callbacks(result)
                logger.info(f"[{topic}] Sentiment: {result['overall_sentiment']} (score: {result['sentiment_score']:.2f})")
            else:
                logger.warning(f"[{topic}] No results.")
        return results

    def stop(self) -> None:
        """Request the monitor to stop."""
        self.running = False
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

        logger.info("=== Kristal Bola - Sentiment Monitor ===")
        logger.info(f"Topics: {', '.join(self.topics)}")
        logger.info(f"Poll interval: {self.config.poll_interval_seconds}s")
        logger.info(f"Analysis window: {self.config.window_minutes} minutes")

        poll_count = 0
        while self.running:
            poll_count += 1
            logger.info(f"--- Poll cycle #{poll_count} ---")

            self.poll_all_topics()

            if self.running:
                logger.info(f"Waiting {self.config.poll_interval_seconds}s until next poll...")
                for _ in range(self.config.poll_interval_seconds):
                    if not self.running:
                        break
                    time.sleep(1)

        logger.info("Monitor stopped.")
