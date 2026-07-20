"""
Kristal Bola - Data Exporter Module

Handles exporting sentiment analysis results to CSV and Parquet formats.
"""

import csv
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)
# Library best practice: avoid "No handlers" warnings when imported without run.py.
logger.addHandler(logging.NullHandler())

# Characters that spreadsheet apps interpret as formula prefixes.
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")

# CSV column order
COLUMNS = [
    "poll_timestamp",
    "topic",
    "overall_sentiment",
    "sentiment_score",
    "positive_percentage",
    "negative_percentage",
    "neutral_percentage",
    "key_narratives",
    "influencers",
    "anomalies_or_shifts",
    "raw_summary",
    "window_minutes",
]


def sanitize_filename(name: str) -> str:
    """Convert a string to a safe filename component.

    Returns a non-empty fallback ("session") if the input contains only
    special characters and would otherwise produce an empty slug.
    """
    # Replace spaces and special chars with hyphens
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name.lower())
    # Collapse multiple hyphens
    while "--" in safe:
        safe = safe.replace("--", "-")
    safe = safe.strip("-")
    return safe or "session"


def escape_csv_formula(value):
    """Neutralize spreadsheet formula injection in CSV string cells.

    Values starting with =, +, - or @ are executed as formulas when the CSV
    is opened in Excel/Sheets. Prefixing with a single quote disables that.
    Non-string values pass through unchanged.
    """
    if isinstance(value, str) and value[:1] in _CSV_FORMULA_PREFIXES:
        return "'" + value
    return value


class SessionExporter:
    """
    Exports sentiment analysis results to CSV, Parquet or JSONL files.

    Thread-safe: all public methods are guarded by an internal lock, so
    callbacks from concurrent polling threads can call append() directly.

    Usage:
        exporter = SessionExporter(output_dir="./data", format="csv")
        exporter.start_session(["Bitcoin ETF", "Tech stocks"])

        # After each poll result:
        exporter.append(result_dict)

        # When done:
        filepath = exporter.close()
    """

    def __init__(
        self,
        output_dir: str = "./data",
        format: Literal["csv", "parquet", "jsonl"] = "csv",
    ):
        self.output_dir = Path(output_dir)
        self.format = format
        self.session_id: Optional[str] = None
        self.filepath: Optional[Path] = None
        self.topics: list[str] = []
        self.results_buffer: list[dict] = []
        self._csv_file = None
        self._csv_writer = None
        self._jsonl_file = None
        self._row_count = 0
        # RLock: start_session() may call close() while holding the lock.
        self._lock = threading.RLock()

    def _generate_filename(self) -> str:
        """Generate filename based on topics and timestamp.

        A short uuid suffix guarantees uniqueness even for two sessions
        started within the same second.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        suffix = uuid.uuid4().hex[:4]

        if len(self.topics) == 1:
            # Single topic: topic_session_timestamp_suffix.ext
            topic_slug = sanitize_filename(self.topics[0])
            return f"{topic_slug}_session_{timestamp}_{suffix}.{self.format}"
        else:
            # Multiple topics: multi_session_timestamp_suffix.ext
            return f"multi_session_{timestamp}_{suffix}.{self.format}"

    def _ensure_output_dir(self) -> None:
        """Create output directory if it doesn't exist."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _flatten_result(self, result: dict) -> dict:
        """Flatten a result dict for CSV export."""
        flat = {}
        for col in COLUMNS:
            value = result.get(col, "")
            # Convert lists to JSON strings
            if isinstance(value, list):
                value = json.dumps(value, ensure_ascii=False)
            flat[col] = value
        return flat

    def start_session(self, topics: list[str]) -> str:
        """
        Start a new export session.

        Args:
            topics: List of topics being monitored

        Returns:
            The filepath where data will be saved
        """
        with self._lock:
            if self.filepath is not None:
                logger.warning("Session already active. Closing previous session.")
                self.close()

            self.topics = topics
            self._ensure_output_dir()

            filename = self._generate_filename()
            self.filepath = self.output_dir / filename
            self.session_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            self._row_count = 0
            self.results_buffer = []

            if self.format == "csv":
                self._start_csv()
            elif self.format == "jsonl":
                self._start_jsonl()
            # Parquet: buffer results, write on close

            logger.info(f"Export session started: {self.filepath}")
            return str(self.filepath)

    def _start_csv(self) -> None:
        """Initialize CSV file with headers."""
        self._csv_file = open(self.filepath, "w", newline="", encoding="utf-8")
        self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=COLUMNS)
        self._csv_writer.writeheader()
        self._csv_file.flush()

    def _start_jsonl(self) -> None:
        """Initialize JSONL file (one JSON object per line, written on append)."""
        self._jsonl_file = open(self.filepath, "w", encoding="utf-8")

    def append(self, result: dict) -> None:
        """
        Append a poll result to the export.

        Args:
            result: Sentiment analysis result dictionary
        """
        with self._lock:
            if self.filepath is None:
                logger.warning("No active session. Call start_session() first.")
                return

            self._row_count += 1

            if self.format == "csv":
                flat = {k: escape_csv_formula(v) for k, v in self._flatten_result(result).items()}
                self._csv_writer.writerow(flat)
                self._csv_file.flush()  # Ensure data is written immediately
                logger.debug(f"Appended row {self._row_count} to CSV")
            elif self.format == "jsonl":
                # Native JSON lines: raw dict, nested lists preserved
                self._jsonl_file.write(json.dumps(result, ensure_ascii=False) + "\n")
                self._jsonl_file.flush()
                logger.debug(f"Appended row {self._row_count} to JSONL")
            else:
                # Parquet: buffer for batch write (unescaped values)
                self.results_buffer.append(self._flatten_result(result))
                logger.debug(f"Buffered row {self._row_count} for Parquet")

    def _write_parquet(self) -> None:
        """Write buffered results to Parquet file."""
        if not self.results_buffer:
            logger.warning("No data to write to Parquet.")
            return

        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            table = pa.Table.from_pylist(self.results_buffer)
            pq.write_table(table, self.filepath)
            logger.info(f"Wrote {len(self.results_buffer)} rows to Parquet")
        except ImportError:
            logger.error(
                "pyarrow not installed. Install with: pip install pyarrow\n"
                "Falling back to CSV export."
            )
            # Fallback to CSV (escape values as in normal CSV writes)
            self.format = "csv"
            self.filepath = self.filepath.with_suffix(".csv")
            self._start_csv()
            for result in self.results_buffer:
                self._csv_writer.writerow({k: escape_csv_formula(v) for k, v in result.items()})
            self._csv_file.close()
            self._csv_file = None

    def close(self) -> Optional[str]:
        """
        Close the export session and finalize the file.

        Returns:
            Path to the exported file, or None if no session was active
        """
        with self._lock:
            if self.filepath is None:
                return None

            if self.format == "csv":
                if self._csv_file:
                    self._csv_file.close()
                    self._csv_file = None
                    self._csv_writer = None
            elif self.format == "jsonl":
                if self._jsonl_file:
                    self._jsonl_file.close()
                    self._jsonl_file = None
            else:
                self._write_parquet()

            filepath = str(self.filepath)
            logger.info(f"Export session closed: {filepath} ({self._row_count} rows)")

            # Reset state
            self.session_id = None
            self.filepath = None
            self.topics = []
            self.results_buffer = []
            self._row_count = 0

            return filepath

    @property
    def is_active(self) -> bool:
        """Check if a session is currently active."""
        return self.filepath is not None

    @property
    def row_count(self) -> int:
        """Get the number of rows written in the current session."""
        return self._row_count
