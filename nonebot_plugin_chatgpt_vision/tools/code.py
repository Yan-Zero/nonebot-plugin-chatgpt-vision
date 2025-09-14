import asyncio
import async_tio  # 运行时代码沙箱
from typing import Any, Dict, Optional

from . import Tool


class _TioRunner:
    """tio.run 执行器（惰性初始化）。

    - Mathematica 直接使用官方 tio.run
    - Python 使用 w3cschool 的 TIO 兼容网关
    """

    def __init__(
        self,
        language: str,
        api_url: Optional[str] = None,
        arguments: Optional[list[str]] = None,
    ):
        self.language = language
        self.api_url = api_url
        self.arguments = arguments or []

    async def run(self, code: str, timeout: int | float | None = 60) -> str:
        async with async_tio.Tio() as client:
            if self.api_url:
                client.API_URL = self.api_url
            try:
                coro = client.execute(
                    code, language=self.language, arguments=self.arguments
                )
                result = await asyncio.wait_for(coro, timeout=timeout)
            except asyncio.TimeoutError:
                return "执行超时，请缩短代码或降低复杂度。"
            except Exception as ex:  # 网络/服务异常
                return f"执行失败：{ex}"

        # async_tio 的结果对象通常包含 output/stdout/stderr
        text = (
            getattr(result, "output", "")
            or getattr(result, "stdout", "")
            or getattr(result, "stderr", "")
        )
        return str(text).strip()


class MmaTool(Tool):
    """Mathematica 代码执行工具（基于 tio.run）"""

    def __init__(self):
        # -print 让 Mathematica 输出更接近交互式
        self.runner = _TioRunner(language="mathematica", arguments=["-print"])

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "run_mma",
                "description": "执行短小的 Mathematica (Wolfram Language) 代码并返回文本输出。不支持图形返回。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "要执行的 Mathematica 代码",
                        },
                        "timeout": {
                            "type": "number",
                            "description": "超时时间（秒），默认 60",
                        },
                    },
                    "required": ["code"],
                },
            },
        }

    async def execute(self, **kwargs) -> str:
        code: str = kwargs.get("code", "").strip()
        timeout: Optional[float] = kwargs.get("timeout", 60)
        if not code:
            return "代码为空。"
        return await self.runner.run(code, timeout=timeout)


class PyTool(Tool):
    """Python 代码执行工具（通过 w3cschool 的 TIO 兼容网关）。

    出于安全考虑，不在本地解释器执行任意代码。
    """

    def __init__(self):
        # w3cschool 的 tryio 网关（兼容 TIO 协议）
        self.runner = _TioRunner(
            language="python3",
            api_url="https://run.w3cschool.cn/tryio/cgi-bin/run/api/",
        )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "run_python",
                "description": """执行短小的 Python3 代码，环境为线上沙箱，版本为3.6.2 (default, Jul 19 2017, 13:09:21) [GCC 7.1.1 20170622 (Red Hat 7.1.1-3)]。
可以访问网络，但不支持交互式输入。""",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "要执行的 Python 代码",
                        },
                        "timeout": {
                            "type": "number",
                            "description": "超时时间（秒），默认 60",
                        },
                    },
                    "required": ["code"],
                },
            },
        }

    async def execute(self, **kwargs) -> str:
        code: str = kwargs.get("code", "").strip()
        timeout: Optional[float] = kwargs.get("timeout", 60)
        if not code:
            return "代码为空。"
        return await self.runner.run(code, timeout=timeout)
