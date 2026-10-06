"""Detect social-media links in free text and classify their platform."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from bbot.models import Link

PLATFORMS = {
    "Facebook": ("facebook.com", "fb.watch", "fb.com"),
    "Instagram": ("instagram.com", "instagr.am"),
    "X": ("x.com", "twitter.com"),
    "YouTube": ("youtube.com", "youtu.be"),
    "TikTok": ("tiktok.com",),
}

_BARE = r"(?:www\.)?(?:facebook\.com|fb\.watch|instagram\.com|x\.com|twitter\.com)/"
URL_RE = re.compile(rf"(?:https?://|{_BARE})[^\s<>\"']+", re.I)


def detect_links(text: str) -> list[Link]:
    links: list[Link] = []
    for raw in URL_RE.findall(text or ""):
        url = raw.rstrip(".,;:!?)]}")
        if not url.lower().startswith("http"):
            url = "https://" + url
        host = (urlparse(url).hostname or "").lower()
        platform = "Other"
        for name, domains in PLATFORMS.items():
            if any(host == d or host.endswith("." + d) for d in domains):
                platform = name
                break
        links.append(Link(platform, url))
    return links
