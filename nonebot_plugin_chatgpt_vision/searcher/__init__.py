from .duckduckgo import DuckDuckGo
from .interface import SearchEngine


def get_searcher(searcher: str) -> SearchEngine:
    """
    Get a searcher by name.
    """
    if searcher == "duckduckgo":
        return DuckDuckGo()
    raise ValueError(f"Unknown searcher: {searcher}")
