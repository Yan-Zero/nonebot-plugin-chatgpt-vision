import yaml
from duckduckgo_search import AsyncDDGS
from .interface import SearchEngine


class DuckDuckGo(SearchEngine):
    """
    DuckDuckGo search engine
    """

    def __init__(self):
        self.name = "DuckDuckGo"

    async def search(self, query: str) -> str:
        """
        Search for query using DuckDuckGo
        """
        rsp = await AsyncDDGS().atext(query, max_results=5)
        if rsp:
            return yaml.dump(rsp, allow_unicode=True)
        return "Not Found, Don't Try Again."
