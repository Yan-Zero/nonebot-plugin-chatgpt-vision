import yaml
import html2text
import aiohttp
from duckduckgo_search import AsyncDDGS
from .interface import SearchEngine


class DuckDuckGo(SearchEngine):
    """
    DuckDuckGo search engine
    """

    output: list

    def __init__(self, **kwargs):
        self.name = "DuckDuckGo"
        self.converter = html2text.HTML2Text()
        self.converter.ignore_links = True
        self.converter.ignore_images = True
        self.output = []

    async def search(self, query: str, max_results: int = 3, **kwargs) -> str:
        """
        Search for query using DuckDuckGo
        """
        self.output = await AsyncDDGS().atext(query, max_results=max_results)
        if self.output:
            return yaml.dump(
                {
                    i + 1: {"title": content["title"], "body": content["body"]}
                    for i, content in enumerate(self.output)
                },
                allow_unicode=True,
            )
        return "Not Found, Try other's words."

    async def mclick(self, index: str, **kwargs) -> str:
        if index < 1 or index > len(self.output):
            return "Index out of range"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.output[index - 1]["href"],
                    timeout=15,
                ) as response:
                    return self.converter.handle(await response.text())
        except Exception as e:
            return "Maybe the link is limited.\nError: " + str(e)
