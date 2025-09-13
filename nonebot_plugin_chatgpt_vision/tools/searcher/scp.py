import aiohttp
import bs4
from .duckduckgo import DuckDuckGo


class SCP(DuckDuckGo):
    """
    SCP搜索引擎
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name = "scp"

    async def search(self, query: str, **kwargs) -> str:
        return await super().search(
            query + " -spc site:scp-wiki-cn.wikidot.com", **kwargs
        )

    async def mclick(self, index: str, **kwargs) -> str:
        if index > len(self.output) or index < 1:
            return "Index out of range"
        async with aiohttp.ClientSession() as session:
            async with session.get(self.output[index - 1]["href"]) as response:
                soup = bs4.BeautifulSoup(await response.text(), "html.parser")
                return self.converter.handle(str(soup.find("div", id="page-content")))
