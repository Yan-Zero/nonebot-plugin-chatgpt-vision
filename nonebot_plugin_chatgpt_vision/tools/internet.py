import yaml
import markdownify
import readabilipy.simple_json

from httpx import AsyncClient
from typing import Tuple, Any

from . import Tool
from ..chat import chat


class FetchUrlTool(Tool):
    def __init__(
        self,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
    ):
        self.user_agent = user_agent

    def get_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "fetch",
                "description": "Fetches a URL from the internet and optionally extracts its contents as markdown.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to fetch",
                        },
                        "start_index": {
                            "type": "number",
                            "description": "The starting index of the content to return. Default is 0.",
                            "default": 0,
                        },
                        "max_length": {
                            "type": "number",
                            "description": "The maximum length of the content to return. If the content exceeds this length, it will be truncated. Default is 5000.",
                            "default": 5000,
                        },
                        "raw": {
                            "type": "boolean",
                            "description": "If true, fetch the raw content without attempting to simplify HTML to markdown. Default is false.",
                            "default": False,
                        },
                    },
                    "required": ["url"],
                },
            },
        }

    async def execute(
        self, url: str, start_index: int = 0, max_length: int = 5000, raw: bool = False
    ) -> str:
        async def fetch_url(
            url: str, user_agent: str, force_raw: bool = False
        ) -> Tuple[str, str]:
            """
            Fetch the URL and return the content in a form ready for the LLM, as well as a prefix string with status information.
            """
            async with AsyncClient() as client:
                response = await client.get(
                    url,
                    follow_redirects=True,
                    headers={"User-Agent": user_agent},
                    timeout=30,
                )
                response.raise_for_status()
                page_raw = response.text

            content_type = response.headers.get("content-type", "")
            is_page_html = (
                "<html" in page_raw[:100]
                or "text/html" in content_type
                or not content_type
            )

            if is_page_html and not force_raw:
                ret = readabilipy.simple_json.simple_json_from_html_string(
                    is_page_html, use_readability=True
                )
                if not ret["content"]:
                    return "<error>Page failed to be simplified from HTML</error>", ""
                content = markdownify.markdownify(
                    ret["content"],
                    heading_style=markdownify.ATX,
                )
                return content, ""

            return (
                page_raw,
                f"Content type {content_type} cannot be simplified to markdown, but here is the raw content:\n",
            )

        try:
            content, prefix = await fetch_url(url, self.user_agent, force_raw=raw)
            content = content[start_index : start_index + max_length]
            return prefix + content
        except Exception as e:
            return f"Error fetching URL {url}: {e}"


class SearchTool(Tool):
    """由 Gemini 驱动的搜索工具"""

    def get_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "search",
                "description": "使用网络搜索引擎搜索信息。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索查询内容"},
                        "max_results": {
                            "type": "number",
                            "description": "返回的最大结果数，默认为5",
                            "default": 5,
                        },
                        "addition": {
                            "type": "string",
                            "description": "附加信息，用自然语言描述，用以改进搜索结果。默认为空。",
                            "default": "",
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    async def execute(
        self, query: str, max_results: int = 5, addition: str = ""
    ) -> str:
        message = [
            {
                "role": "user",
                "content": f"""帮我搜索如下内容：
```
{query}
```

{f"附加信息：{addition}" if addition else ""}

请使用yaml格式返回搜索结果，格式如下：
```yaml
overview: <对搜索结果的简要总结，300字以内>
results:
  - title: <结果标题>
    link: <结果链接>
    snippet: <结果摘要，200字左右>
  - title: <结果标题>
    link: <结果链接>
    snippet: <结果摘要，200字左右>
  ...  最多返回 {max_results} 条结果。
```""",
            }
        ]
        try:
            response = await chat(
                message=message,
                model="gemini-2.5-flash",
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "googleSearch",
                        },
                    }
                ],
            )
            ret = response.choices[0].message.content

            # 提取代码块中的内容
            found = False
            if "```yaml" in ret:
                ret = ret.split("```yaml", 1)[1].rsplit("```", 1)[0].strip()
                found = True
            elif "```" in ret:
                ret = ret.split("```", 1)[1].rsplit("```", 1)[0].strip()
                found = True
            if not found:
                return ret

            try:
                parsed = yaml.safe_load(ret)
            except Exception:
                return ret
            if not isinstance(parsed, dict) or "results" not in parsed:
                return ret

            for item in parsed["results"]:
                if "link" in item:
                    async with AsyncClient() as client:
                        resp = await client.head(
                            item["link"],
                            follow_redirects=True,
                            headers={"User-Agent": "Mozilla/5.0"},
                            timeout=10,
                        )
                        item["link"] = str(resp.url)
            return yaml.safe_dump(parsed, allow_unicode=True)
        except Exception as e:
            return f"搜索时出错：{e}"
