from .interface import SearchEngine
from .duckduckgo import DuckDuckGo
from .scp import SCP


def get_searcher(searcher: str) -> SearchEngine:
    """
    Get a searcher by name.
    """
    if searcher == "duckduckgo":
        return DuckDuckGo()
    if searcher == "scp":
        return SCP()
    return None
