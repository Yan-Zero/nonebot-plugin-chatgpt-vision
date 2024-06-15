class SearchEngine:
    def __init__(self, name: str, **kwargs):
        self.name = name

    async def search(self, query: str, **kwargs) -> str:
        """
        异步搜索并返回结果列表
        """
        raise NotImplementedError

    async def mclick(self, index: str, **kwargs) -> str:
        """
        异步点击并返回结果
        """
        raise NotImplementedError
