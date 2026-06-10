# BD Conference Bot

A web scraper for monitoring conference announcements from Bangladeshi universities and special conferences.

## Project Structure

- **scraper/**: Main scraping application
  - `browser.py`: Web browser automation (Selenium, anti-bot measures)
  - `main.py`: Entry point and orchestrator
  - `extractor.py`: LLM-based data extraction (Gemini 2.5 Flash)
  - `notifier.py`: Telegram channel notification handler
  - `sources/`: Discovery source handlers
    - `crt_monitor.py`: Certificate transparency log scanning
    - `homepage_links.py`: University homepage link scanning
    - `special.py`: Recurring conference URL probing
- **config/**: Configuration files
  - `universities.json`: Bangladeshi university domains
  - `special_sources.json`: Special conference sources (ICCIT, QPAIN, etc.)
- **db/**: Database schema
  - `schema.sql`: PostgreSQL table definitions
- **.github/workflows/**: CI/CD automation
  - `scraper.yml`: Scheduled scraping workflow (every 6 hours)

## Setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Configure universities and special sources in `config/`
3. Set environment variables: `DATABASE_URL`, `GOOGLE_AI_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`
4. Run the scraper:
   ```bash
   python scraper/main.py
   ```

## License

MIT
