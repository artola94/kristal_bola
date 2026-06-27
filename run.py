#!/usr/bin/env python3
"""
Kristal Bola - CLI Runner

Entry point for the sentiment monitoring system.
Supports both CLI arguments and interactive mode.

Usage:
    # CLI mode
    python run.py --topic "Bitcoin ETF" --topic "Fed rates" --mongo-uri "mongodb://localhost"

    # Interactive mode (no arguments)
    python run.py
"""

import argparse
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Optional

# Load environment variables from .env file
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed, use system env vars

from exporter import SessionExporter
from sentiment import MonitorConfig, SentimentMonitor

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("kristal_bola.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# Global references for signal handling
monitor: Optional[SentimentMonitor] = None
exporter: Optional[SessionExporter] = None


def signal_handler(signum, frame):
    """Handle termination signals."""
    sig_name = signal.Signals(signum).name
    print(f"\n[!] Signal {sig_name} received. Shutting down...")
    if monitor:
        monitor.stop()
    if exporter and exporter.is_active:
        filepath = exporter.close()
        if filepath:
            print(f"[!] Data exported to: {filepath}")


def setup_signals():
    """Register signal handlers."""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Kristal Bola - Social Media Sentiment Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run.py --topic "Bitcoin ETF"
  python run.py --topic "AI regulation" --topic "Tech layoffs" --interval 60
  python run.py --mongo-uri "mongodb://localhost:27017" --topic "Climate change"
  python run.py  # Interactive mode
        """,
    )

    parser.add_argument(
        "-t",
        "--topic",
        action="append",
        dest="topics",
        metavar="TOPIC",
        help="Topic to monitor (can be specified multiple times)",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=int,
        default=int(os.getenv("KRISTAL_POLL_INTERVAL", "300")),
        metavar="SECONDS",
        help="Poll interval in seconds (default: from env or 300)",
    )
    parser.add_argument(
        "-w",
        "--window",
        type=int,
        default=int(os.getenv("KRISTAL_WINDOW_MINUTES", "15")),
        metavar="MINUTES",
        help="Analysis time window in minutes (default: from env or 15)",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("KRISTAL_MODEL", "grok-4-1-fast-reasoning"),
        metavar="MODEL",
        help="xAI model for analysis (default: from env or grok-4-1-fast-reasoning)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=int(os.getenv("KRISTAL_MAX_WORKERS", "4")),
        metavar="N",
        help="Concurrent topic polls (default: from env or 4)",
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.getenv("KRISTAL_MONGODB_URI"),
        metavar="URI",
        help="MongoDB connection URI (default: from env)",
    )
    parser.add_argument(
        "--mongo-db",
        default=os.getenv("KRISTAL_MONGODB_DB", "kristal_bola"),
        metavar="NAME",
        help="MongoDB database name (default: from env or kristal_bola)",
    )
    parser.add_argument(
        "--mongo-collection",
        default=os.getenv("KRISTAL_MONGODB_COLLECTION", "sentiment_polls"),
        metavar="NAME",
        help="MongoDB collection name (default: from env or sentiment_polls)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Force interactive mode even with other arguments",
    )

    # Export options
    parser.add_argument(
        "--export-format",
        choices=["csv", "parquet"],
        default=os.getenv("KRISTAL_EXPORT_FORMAT", "csv"),
        metavar="FORMAT",
        help="Export format: csv or parquet (default: from env or csv)",
    )
    parser.add_argument(
        "--export-dir",
        default=os.getenv("KRISTAL_EXPORT_DIR", "./data"),
        metavar="DIR",
        help="Directory for exported data (default: from env or ./data)",
    )
    parser.add_argument("--no-export", action="store_true", help="Disable data export to file")

    return parser.parse_args()


def clear_screen():
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def print_header():
    """Print the application header."""
    print("\n" + "=" * 50)
    print("       KRISTAL BOLA - Sentiment Monitor")
    print("=" * 50)


def print_current_config(monitor: SentimentMonitor, exp: Optional[SessionExporter] = None):
    """Print current configuration."""
    print("\n[Current Configuration]")
    print(f"  Poll interval: {monitor.config.poll_interval_seconds}s")
    print(f"  Analysis window: {monitor.config.window_minutes} min")
    print(f"  MongoDB: {monitor.config.mongodb_uri or 'Not configured'}")
    if exp:
        print(f"  Export: {exp.format.upper()} -> {exp.output_dir}/")
    else:
        print("  Export: Disabled")

    topics = monitor.list_topics()
    print(f"\n[Topics] ({len(topics)})")
    if topics:
        for i, topic in enumerate(topics, 1):
            print(f"  {i}. {topic}")
    else:
        print("  (none)")


def interactive_add_topic(monitor: SentimentMonitor):
    """Interactively add a topic."""
    print("\n[Add Topic]")
    topic = input("Enter topic to monitor (or empty to cancel): ").strip()
    if topic:
        monitor.add_topic(topic)
        print(f"  ✓ Added: {topic}")
    else:
        print("  Cancelled.")


def interactive_remove_topic(monitor: SentimentMonitor):
    """Interactively remove a topic."""
    topics = monitor.list_topics()
    if not topics:
        print("\n  No topics to remove.")
        return

    print("\n[Remove Topic]")
    for i, topic in enumerate(topics, 1):
        print(f"  {i}. {topic}")

    choice = input("Enter number to remove (or empty to cancel): ").strip()
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(topics):
            removed = topics[idx]
            monitor.remove_topic(removed)
            print(f"  ✓ Removed: {removed}")
        else:
            print("  Invalid selection.")
    else:
        print("  Cancelled.")


def interactive_configure_mongodb(monitor: SentimentMonitor):
    """Interactively configure MongoDB."""
    print("\n[Configure MongoDB]")
    print(f"  Current URI: {monitor.config.mongodb_uri or 'Not set'}")
    print(f"  Current DB: {monitor.config.mongodb_db}")
    print(f"  Current Collection: {monitor.config.mongodb_collection}")

    uri = input("\nEnter MongoDB URI (or empty to skip): ").strip()
    if uri:
        monitor.config.mongodb_uri = uri
        print(f"  ✓ URI set: {uri}")

    db = input("Enter database name (or empty to keep current): ").strip()
    if db:
        monitor.config.mongodb_db = db
        print(f"  ✓ Database: {db}")

    collection = input("Enter collection name (or empty to keep current): ").strip()
    if collection:
        monitor.config.mongodb_collection = collection
        print(f"  ✓ Collection: {collection}")


def interactive_configure_polling(monitor: SentimentMonitor):
    """Interactively configure polling settings."""
    print("\n[Configure Polling]")
    print(f"  Current interval: {monitor.config.poll_interval_seconds}s")
    print(f"  Current window: {monitor.config.window_minutes} min")

    interval = input("\nEnter poll interval in seconds (or empty to keep): ").strip()
    if interval.isdigit():
        monitor.config.poll_interval_seconds = int(interval)
        print(f"  ✓ Interval: {interval}s")

    window = input("Enter analysis window in minutes (or empty to keep): ").strip()
    if window.isdigit():
        monitor.config.window_minutes = int(window)
        print(f"  ✓ Window: {window} min")


def interactive_configure_export(exp: SessionExporter) -> Optional[SessionExporter]:
    """Interactively configure export settings."""
    print("\n[Configure Export]")
    print(f"  Current format: {exp.format}")
    print(f"  Current directory: {exp.output_dir}")

    print("\n  1. CSV format")
    print("  2. Parquet format")
    print("  3. Disable export")
    print("  4. Keep current settings")

    choice = input("\nSelect option: ").strip()

    if choice == "1":
        exp.format = "csv"
        print("  ✓ Format: CSV")
    elif choice == "2":
        exp.format = "parquet"
        print("  ✓ Format: Parquet")
    elif choice == "3":
        print("  ✓ Export disabled")
        return None
    elif choice == "4":
        print("  ✓ Keeping current settings")
        return exp
    else:
        print("  ✓ Keeping current settings")
        return exp

    directory = input("Enter export directory (or empty to keep current): ").strip()
    if directory:
        exp.output_dir = Path(directory)
        print(f"  ✓ Directory: {directory}")

    return exp


def interactive_mode(
    monitor: SentimentMonitor,
    exp: Optional[SessionExporter] = None,
    args: Optional[argparse.Namespace] = None,
):
    """Run the interactive menu."""
    while True:
        print_header()
        print_current_config(monitor, exp)

        print("\n[Menu]")
        print("  1. Add topic")
        print("  2. Remove topic")
        print("  3. Configure MongoDB")
        print("  4. Configure polling")
        print("  5. Configure export")
        print("  6. Start monitoring")
        print("  7. Run single poll (test)")
        print("  0. Exit")

        choice = input("\nSelect option: ").strip()

        if choice == "1":
            interactive_add_topic(monitor)
        elif choice == "2":
            interactive_remove_topic(monitor)
        elif choice == "3":
            interactive_configure_mongodb(monitor)
        elif choice == "4":
            interactive_configure_polling(monitor)
        elif choice == "5":
            if exp is None:
                # Recreate respecting CLI/env flags (e.g. --export-format parquet)
                exp = SessionExporter(
                    output_dir=args.export_dir if args else "./data",
                    format=args.export_format if args else "csv",
                )
            exp = interactive_configure_export(exp)
        elif choice == "6":
            if not monitor.list_topics():
                print("\n  [!] Add at least one topic first.")
                input("Press Enter to continue...")
                continue
            if not os.getenv("XAI_API_KEY"):
                print("\n  [!] XAI_API_KEY environment variable not set.")
                input("Press Enter to continue...")
                continue

            # Start export session if enabled
            if exp:
                exp.start_session(monitor.list_topics())
                monitor.clear_callbacks()
                monitor.on_result(exp.append)
                print(f"\n  Export enabled: {exp.filepath}")

            print("\n  Starting monitor... (Ctrl+C to stop)")
            input("Press Enter to begin...")
            monitor.run()

            # Close export session
            if exp and exp.is_active:
                filepath = exp.close()
                print(f"\n  Data exported to: {filepath}")

            print("\n  Monitor stopped.")
            input("Press Enter to continue...")
        elif choice == "7":
            if not monitor.list_topics():
                print("\n  [!] Add at least one topic first.")
                input("Press Enter to continue...")
                continue
            if not os.getenv("XAI_API_KEY"):
                print("\n  [!] XAI_API_KEY environment variable not set.")
                input("Press Enter to continue...")
                continue

            # Start export session for single poll if enabled.
            # Register append as the sole callback so poll_all_topics drives
            # the export; no manual append below (would duplicate rows).
            if exp:
                exp.start_session(monitor.list_topics())
                monitor.clear_callbacks()
                monitor.on_result(exp.append)

            print("\n  Running single poll...")
            if monitor.init_client():
                results = monitor.poll_all_topics()
                print(f"\n  Completed. {len(results)} result(s) received.")
                for r in results:
                    print(f"\n  [{r['topic']}]")
                    print(f"    Sentiment: {r['overall_sentiment']} ({r['sentiment_score']:.2f})")
                    print(f"    Summary: {r['raw_summary']}")

            # Close export session
            if exp and exp.is_active:
                filepath = exp.close()
                print(f"\n  Data exported to: {filepath}")

            input("\nPress Enter to continue...")
        elif choice == "0":
            print("\nGoodbye!")
            break
        else:
            print("\n  Invalid option.")
            input("Press Enter to continue...")


def cli_mode(args: argparse.Namespace, monitor: SentimentMonitor, exp: Optional[SessionExporter]):
    """Run in CLI mode with provided arguments."""
    global exporter
    exporter = exp

    # Add topics
    for topic in args.topics:
        monitor.add_topic(topic)

    # Validate
    if not os.getenv("XAI_API_KEY"):
        logger.critical("XAI_API_KEY environment variable not set.")
        sys.exit(1)

    # Start export session if enabled
    if exp:
        exp.start_session(monitor.list_topics())
        monitor.clear_callbacks()
        monitor.on_result(exp.append)

    # Start monitoring
    print_header()
    print(f"\nTopics: {', '.join(args.topics)}")
    print(f"Interval: {args.interval}s | Window: {args.window}min")
    if args.mongo_uri:
        print(f"MongoDB: {args.mongo_uri}")
    if exp:
        print(f"Export: {exp.format.upper()} -> {exp.filepath}")
    print("\nStarting monitor... (Ctrl+C to stop)\n")

    monitor.run()

    # Close export session
    if exp and exp.is_active:
        filepath = exp.close()
        print(f"\nData exported to: {filepath}")


def main():
    global monitor, exporter

    setup_signals()
    args = parse_args()

    # Build config from args (env vars loaded as argparse defaults)
    config = MonitorConfig(
        poll_interval_seconds=args.interval,
        window_minutes=args.window,
        model=args.model,
        max_workers=args.max_workers,
        mongodb_uri=args.mongo_uri,
        mongodb_db=args.mongo_db,
        mongodb_collection=args.mongo_collection,
    )

    monitor = SentimentMonitor(config)

    # Create exporter if not disabled
    exp: Optional[SessionExporter] = None
    if not args.no_export:
        exp = SessionExporter(
            output_dir=args.export_dir,
            format=args.export_format,
        )
    exporter = exp

    # Decide mode
    if args.interactive or not args.topics:
        # Interactive mode
        interactive_mode(monitor, exp, args)
    else:
        # CLI mode
        cli_mode(args, monitor, exp)


if __name__ == "__main__":
    main()
