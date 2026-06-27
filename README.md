# Kristal Bola

Real-time social media sentiment monitoring system powered by Grok (xAI).

Kristal Bola monitors X (Twitter) for specific topics and analyzes public sentiment using AI, providing structured insights about how people feel about any subject.

---

## Table of Contents

1. [Features](#features)
2. [Requirements](#requirements)
3. [Installation](#installation)
   - [Step 1: Install Python](#step-1-install-python)
   - [Step 2: Download the Project](#step-2-download-the-project)
   - [Step 3: Create a Virtual Environment](#step-3-create-a-virtual-environment)
   - [Step 4: Install Dependencies](#step-4-install-dependencies)
   - [Step 5: Get Your xAI API Key](#step-5-get-your-xai-api-key)
   - [Step 6: Configure Environment Variables](#step-6-configure-environment-variables)
4. [Usage](#usage)
   - [Interactive Mode](#interactive-mode)
   - [Command Line Mode](#command-line-mode)
5. [Configuration Options](#configuration-options)
6. [Data Export](#data-export)
7. [MongoDB Setup (Optional)](#mongodb-setup-optional)
8. [Output Format](#output-format)
9. [Troubleshooting](#troubleshooting)
10. [Project Structure](#project-structure)
11. [License](#license)

---

## Features

- **Real-time sentiment analysis** of any topic on X (Twitter)
- **Multiple topics** monitoring simultaneously
- **Structured output** with sentiment scores, percentages, and summaries
- **Anomaly detection** for sudden shifts in public opinion
- **Influencer tracking** to identify key voices
- **Data export** to CSV or Parquet files for analysis
- **MongoDB integration** for data persistence (optional)
- **Interactive and CLI modes** for flexibility

---

## Requirements

- **Python 3.9 or higher**
- **xAI API Key** (for Grok access)
- **Internet connection**
- **MongoDB** (optional, for data persistence)

---

## Installation

### Step 1: Install Python

If you don't have Python installed:

**Windows:**
1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Download the latest Python 3.x version
3. Run the installer
4. **IMPORTANT:** Check the box "Add Python to PATH" during installation
5. Click "Install Now"

**macOS:**
```bash
# Using Homebrew (recommended)
brew install python
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
```

**Verify installation:**
```bash
python --version
# Should show: Python 3.9.x or higher
```

---

### Step 2: Download the Project

**Option A: Clone with Git**
```bash
git clone https://github.com/artola94/kristal_bola.git
cd kristal_bola
```

**Option B: Download ZIP**
1. Download the project ZIP file
2. Extract it to a folder of your choice
3. Open a terminal/command prompt in that folder

---

### Step 3: Create a Virtual Environment

A virtual environment keeps project dependencies isolated from your system Python.

**Windows (Command Prompt):**
```cmd
python -m venv venv
venv\Scripts\activate
```

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

> **Note:** If you get an error about execution policies in PowerShell, run:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

**macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

You should see `(venv)` at the beginning of your terminal prompt, indicating the virtual environment is active.

---

### Step 4: Install Dependencies

With your virtual environment activated:

```bash
pip install -r requirements.txt
```

This installs all required dependencies including optional ones (MongoDB, Parquet support).

---

### Step 5: Get Your xAI API Key

1. Go to [console.x.ai](https://console.x.ai)
2. Create an account or sign in
3. Navigate to "API Keys" section
4. Click "Create API Key"
5. Copy the key (you won't be able to see it again!)

---

### Step 6: Configure Environment Variables

1. **Copy the example configuration:**

   **Windows (Command Prompt):**
   ```cmd
   copy .env.example .env
   ```

   **macOS/Linux:**
   ```bash
   cp .env.example .env
   ```

2. **Edit the `.env` file:**

   Open `.env` in any text editor (Notepad, VS Code, nano, etc.) and replace the placeholder with your actual API key:

   ```
   XAI_API_KEY=xai-your-actual-api-key-here
   ```

3. **Save the file**

> **SECURITY WARNING:** Never share your `.env` file or commit it to version control. The `.gitignore` file is configured to exclude it automatically.

---

## Usage

### Interactive Mode

The easiest way to use Kristal Bola is through the interactive menu:

```bash
python run.py
```

You'll see a menu like this:

```
==================================================
       KRISTAL BOLA - Sentiment Monitor
==================================================

[Current Configuration]
  Poll interval: 300s
  Analysis window: 15 min
  MongoDB: Not configured
  Export: CSV -> data/

[Topics] (0)
  (none)

[Menu]
  1. Add topic
  2. Remove topic
  3. Configure MongoDB
  4. Configure polling
  5. Configure export
  6. Start monitoring
  7. Run single poll (test)
  0. Exit

Select option:
```

**Quick Start:**
1. Select `1` to add a topic (e.g., "Bitcoin price")
2. Select `7` to run a single test poll
3. If it works, select `6` to start continuous monitoring
4. Data will be automatically exported to `./data/` as CSV

---

### Command Line Mode

For automation or scripting, use command line arguments:

**Single topic:**
```bash
python run.py --topic "Bitcoin ETF"
```

**Multiple topics:**
```bash
python run.py --topic "AI regulation" --topic "Tech layoffs" --topic "Climate change"
```

**With custom settings:**
```bash
python run.py --topic "Federal Reserve" --interval 60 --window 30
```

**With MongoDB:**
```bash
python run.py --topic "Stock market" --mongo-uri "mongodb://localhost:27017"
```

**Export to Parquet instead of CSV:**
```bash
python run.py --topic "AI stocks" --export-format parquet
```

**Custom export directory:**
```bash
python run.py --topic "Tech news" --export-dir "./my_data"
```

**Disable export (only MongoDB or console):**
```bash
python run.py --topic "Crypto" --no-export
```

**See all options:**
```bash
python run.py --help
```

---

## Configuration Options

| Option | Environment Variable | CLI Flag | Default | Description |
|--------|---------------------|----------|---------|-------------|
| API Key | `XAI_API_KEY` | - | (required) | Your xAI API key |
| Poll Interval | `KRISTAL_POLL_INTERVAL` | `--interval` | 300 | Seconds between polls |
| Window | `KRISTAL_WINDOW_MINUTES` | `--window` | 15 | Minutes of data to analyze |
| Max Retries | `KRISTAL_MAX_RETRIES` | - | 3 | Retry attempts on failure |
| Retry Delay | `KRISTAL_RETRY_DELAY` | - | 30 | Seconds between retries |
| Model | `KRISTAL_MODEL` | - | grok-4-1-fast-reasoning | xAI model used for analysis |
| Max Workers | `KRISTAL_MAX_WORKERS` | - | 4 | Concurrent topic polls |
| MongoDB URI | `KRISTAL_MONGODB_URI` | `--mongo-uri` | - | MongoDB connection string |
| MongoDB DB | `KRISTAL_MONGODB_DB` | `--mongo-db` | kristal_bola | Database name |
| MongoDB Collection | `KRISTAL_MONGODB_COLLECTION` | `--mongo-collection` | sentiment_polls | Collection name |
| Export Format | `KRISTAL_EXPORT_FORMAT` | `--export-format` | csv | Export format (csv/parquet) |
| Export Directory | `KRISTAL_EXPORT_DIR` | `--export-dir` | ./data | Directory for exported files |
| Disable Export | - | `--no-export` | false | Disable file export |

---

## Data Export

Each monitoring session automatically exports data to files for later analysis.

### File Naming

Files are named based on topics and session start time:

| Scenario | Filename Example |
|----------|------------------|
| Single topic | `bitcoin-etf_session_2024-01-15_103045.csv` |
| Multiple topics | `multi_session_2024-01-15_103045.csv` |

### CSV Format

CSV files can be opened in Excel, Google Sheets, or any data analysis tool:

```csv
poll_timestamp,topic,overall_sentiment,sentiment_score,positive_percentage,...
2024-01-15T10:30:00Z,Bitcoin ETF,positive,0.65,58.5,...
2024-01-15T10:35:00Z,Bitcoin ETF,positive,0.62,55.2,...
```

List fields (`key_narratives`, `influencers`) are stored as JSON strings.

### Parquet Format

For large datasets or data science workflows, use Parquet:

```bash
python run.py --topic "AI news" --export-format parquet
```

**Requires:** `pip install pyarrow`

Parquet offers:
- ~10x smaller file sizes
- Faster loading in pandas/polars
- Native support for arrays and complex types

### Reading Exported Data

**Python (pandas):**
```python
import pandas as pd

# CSV
df = pd.read_csv("./data/bitcoin-etf_session_2024-01-15_103045.csv")

# Parquet
df = pd.read_parquet("./data/bitcoin-etf_session_2024-01-15_103045.parquet")

# Parse JSON columns
import json
df['key_narratives'] = df['key_narratives'].apply(json.loads)
```

---

## MongoDB Setup (Optional)

MongoDB allows you to store sentiment analysis results for historical analysis.

### Local MongoDB Installation

**Windows:**
1. Download from [mongodb.com/try/download/community](https://www.mongodb.com/try/download/community)
2. Run the installer
3. MongoDB will run as a service automatically

**macOS:**
```bash
brew tap mongodb/brew
brew install mongodb-community
brew services start mongodb-community
```

**Linux (Ubuntu):**
```bash
sudo apt install mongodb
sudo systemctl start mongodb
sudo systemctl enable mongodb
```

### Cloud MongoDB (MongoDB Atlas)

1. Go to [mongodb.com/atlas](https://www.mongodb.com/atlas)
2. Create a free account
3. Create a free cluster
4. Get your connection string
5. Add it to your `.env` file:
   ```
   KRISTAL_MONGODB_URI=mongodb+srv://user:password@cluster.mongodb.net
   ```

---

## Output Format

Each poll returns structured data like this:

```json
{
  "topic": "Bitcoin ETF",
  "timestamp": "2024-01-15T10:30:00Z",
  "overall_sentiment": "positive",
  "sentiment_score": 0.65,
  "positive_percentage": 58.5,
  "negative_percentage": 22.3,
  "neutral_percentage": 19.2,
  "key_narratives": [
    "SEC approval expectations",
    "Institutional adoption",
    "Price predictions"
  ],
  "influencers": [
    "@exampleuser1",
    "@exampleuser2"
  ],
  "anomalies_or_shifts": "Significant increase in positive sentiment over the last hour",
  "raw_summary": "Discussion is predominantly optimistic about potential ETF approval, with focus on institutional interest."
}
```

---

## Troubleshooting

### "XAI_API_KEY is not set"

**Cause:** The API key wasn't loaded from `.env` or environment.

**Solution:**
1. Make sure `.env` file exists in the project folder
2. Check that `XAI_API_KEY=your-key` is in the file (no spaces around `=`)
3. Make sure `python-dotenv` is installed: `pip install python-dotenv`

### "ModuleNotFoundError: No module named 'xai_sdk'"

**Cause:** Dependencies not installed.

**Solution:**
```bash
pip install xai-sdk pydantic python-dotenv
```

### "python: command not found" or "'python' is not recognized"

**Cause:** Python not installed or not in PATH.

**Solution:**
- Windows: Reinstall Python and check "Add Python to PATH"
- macOS/Linux: Use `python3` instead of `python`

### Virtual environment not activating

**Windows PowerShell:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\venv\Scripts\Activate.ps1
```

**Make sure you're in the project directory:**
```bash
cd path/to/kristal_bola
```

### MongoDB connection errors

1. Check MongoDB is running:
   - Windows: Check Services app for "MongoDB"
   - macOS/Linux: `sudo systemctl status mongodb`

2. Verify your connection string is correct

3. For Atlas: Make sure your IP is whitelisted in Network Access

### Rate limiting or API errors

The xAI API has rate limits. If you hit them:
1. Increase `KRISTAL_POLL_INTERVAL` in your `.env`
2. The system will automatically retry with the configured delay

---

## Project Structure

```
kristal_bola/
├── run.py              # Entry point (CLI & interactive)
├── sentiment.py        # Core monitoring module
├── exporter.py         # Data export module (CSV/Parquet)
├── data/               # Exported data files (created on first run)
│   └── *.csv / *.parquet
├── .env                # Your configuration (not in git)
├── .env.example        # Configuration template
├── .gitignore          # Git ignore rules
├── README.md           # This file
└── kristal_bola.log    # Log file (created on first run)
```

---

## License

MIT License - See LICENSE file for details.
