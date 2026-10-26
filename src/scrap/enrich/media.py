"""Enrich: what medium a saved link is (a book, a film, a video ...): the site's own
rules first, which are certain, then the model's reading of the page."""

from urllib.parse import urlsplit

# Host (and its subdomains) -> medium; a path prefix narrows a host that carries several
SITES: list[tuple[str, str, str]] = [
    ("youtube.com", "", "video"),
    ("youtu.be", "", "video"),
    ("vimeo.com", "", "video"),
    ("goodreads.com", "", "book"),
    ("netflix.com", "", "tv"),
    ("disneyplus.com", "", "tv"),
    ("imdb.com", "", "film"),
    ("spotify.com", "/episode", "podcast"),
    ("spotify.com", "/show", "podcast"),
    ("spotify.com", "", "music"),
    ("podcasts.apple.com", "", "podcast"),
    ("music.apple.com", "", "music"),
    ("bandcamp.com", "", "music"),
    ("store.steampowered.com", "", "game"),
]


def site_media(url: str) -> str:
    """The medium a site's address says, or "" where it does not."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return ""
    for domain, prefix, medium in SITES:
        if (host == domain or host.endswith("." + domain)) and parts.path.startswith(
            prefix
        ):
            return medium
    return ""
