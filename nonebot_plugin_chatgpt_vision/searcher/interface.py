class SearchEngine:
    def __init__(self, name: str):
        self.name = name

    def search(self, query: str) -> str:
        """
        搜索并返回结果列表
        """
        raise NotImplementedError

    async def search_async(self, query: str) -> str:
        """
        异步搜索并返回结果列表
        """
        raise NotImplementedError
