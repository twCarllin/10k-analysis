"""Serial HTTP transport with bounded retries and explicit diagnostics."""

import logging
import time
import requests

logger = logging.getLogger(__name__)


class Transport:
    def __init__(self, timeout=20, attempts=3, interval=0.5):
        self.session = requests.Session()
        self.timeout = timeout
        self.attempts = attempts
        self.interval = interval

    def get(self, url, **kwargs):
        for attempt in range(self.attempts):
            time.sleep(self.interval)
            try:
                response = self.session.get(url, timeout=self.timeout, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {response.status_code}")
                response.raise_for_status()
                return response
            except requests.RequestException as error:
                if attempt + 1 == self.attempts:
                    error.request_url = url
                    error.request_attempt = attempt + 1
                    error.add_note(f"HTTP url={url}; attempt={attempt + 1}")
                    raise
                logger.warning(
                    "HTTP request retry",
                    extra={
                        "event": "request_retry",
                        "url": url,
                        "attempt": attempt + 1,
                    },
                )
        raise RuntimeError("No HTTP attempts configured")
