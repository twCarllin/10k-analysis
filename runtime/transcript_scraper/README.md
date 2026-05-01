# transcript_scraper

Scrapes earnings call transcripts from Yahoo Finance using Node Stagehand (Chromium) + a Python async wrapper.

## Requirements

- Python 3.11+
- Node >= 20
- `config.json` in the project root with an `anthropic_api_key` field

## Setup

```bash
# Install Node dependencies and Chromium
cd runtime/transcript_scraper/node
npm install
npx playwright install chromium
```

No additional Python packages needed beyond `requirements.txt`.

## Usage

```python
import asyncio
from runtime.transcript_scraper import scrape_transcript

async def main():
    # Hard failure on error (default)
    transcript = await scrape_transcript("INTC", "Q1", "2026")
    print(transcript.date, len(transcript.raw_text))

    # Soft failure: returns None if transcript not found or scrape fails
    result = await scrape_transcript("AAPL", "Q2", "2025", skip_on_failure=True)
    if result is None:
        print("Transcript not available, skipping")

asyncio.run(main())
```

## Config

`config.json` (project root):
```json
{
  "anthropic_api_key": "sk-ant-..."
}
```

Alternatively, set the `ANTHROPIC_API_KEY` environment variable directly (overrides `config.json`).

## Notes

- Each scrape call costs ~$0.01–0.03 in LLM tokens (two Stagehand extract calls).
- Default timeout: 120 seconds per scrape.
- Retries: up to 3 attempts with exponential backoff on network/subprocess failures.
