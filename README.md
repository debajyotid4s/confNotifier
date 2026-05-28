# BD Conference Bot

A web scraper for monitoring conference announcements from Bangladeshi universities and special conferences.

## Project Structure

- **scraper/**: Main scraping application
  - `browser.py`: Web browser automation
  - `main.py`: Entry point
  - `sources/`: Source handlers
    - `universities.py`: Monitors 98 uni websites
    - `special.py`: Monitors ICCIT and similar non-uni conferences
  - `extractor.py`: Data extraction logic
  - `deduplicator.py`: Removes duplicate conferences
  - `notifier.py`: Notification handler
- **data/**: Persistent data storage
  - `seen.json`: Tracks seen conferences
- **config/**: Configuration files
  - `universities.json`: All 98 universities
  - `special_sources.json`: Special conference sources
- **.github/workflows/**: CI/CD automation
  - `scraper.yml`: Scheduled scraping workflow

## Setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Configure universities and special sources in `config/`

3. Run the scraper:
   ```bash
   python scraper/main.py
   ```

## License

MIT
