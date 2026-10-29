"""What Claude would cost for an import's pages and photos: rough, from typical token
counts per call and claude.PRICES for the models set (each call's real cost depends on
its text, and is counted in the daily budget as it is made)."""

from .. import claude

# Typical tokens (in, out with thinking) of each call, as measured on a real store
ENRICH_CALL = (18_000, 2_000)  # a text page's tags and summary (about $0.003 on Haiku)
RELATED_CALL = (10_000, 1_000)  # its first related pages (about $0.0015)
PHOTO_CALL = (6_000, 1_500)  # one photo read (about $0.05 on Opus)


def _usd(model: str, tokens: tuple[int, int]) -> float:
    usage = {"input_tokens": tokens[0], "output_tokens": tokens[1]}
    return claude.cost_microusd(model, usage) / 1e6


def per_page() -> float:
    """Dollars, roughly, for Claude to tag, summarise and relate one text page."""
    model = claude.text_model()[0]
    return _usd(model, ENRICH_CALL) + _usd(model, RELATED_CALL)


def per_photo() -> float:
    """Dollars, roughly, for Claude to read one photo."""
    return _usd(claude.model_name(), PHOTO_CALL)
