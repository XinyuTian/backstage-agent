from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProjectPageClient:
    def fetch_html(self, url: str | None) -> str | None:
        if not url:
            return None
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
                )
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except (HTTPError, URLError, TimeoutError):
            return None
