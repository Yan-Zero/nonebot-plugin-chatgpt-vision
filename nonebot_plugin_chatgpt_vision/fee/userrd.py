from nonebot import get_plugin_config
from datetime import datetime
from datetime import timedelta

from ..config import Config

p_config: Config = get_plugin_config(Config)


def get_comsumption(usage: dict, model: str) -> float:
    pt = usage.get("prompt_tokens", 100)
    ct = usage.get("completion_tokens", 100)

    if model.startswith("gpt-3.5"):
        return (0.5 * pt + 1.5 * ct) / 1_000_000
    if model.startswith("gpt-4o"):
        return (5 * pt + 15 * ct) / 1_000_000
    if model.startswith("gpt-4-"):
        return (30 * pt + 60 * ct) / 1_000_000
    if model.startswith("glm-4-"):
        return (13.9 * pt + 13.9 * ct) / 1_000_000
    if model.startswith("gemini-2.5-flash"):
        return (0.12 * pt + 1 * ct) / 1_000_000
    if model.startswith("gemini-2.5-pro"):
        return (0.5 * pt + 4 * ct) / 1_000_000
    return (10 * pt + 30 * ct) / 1_000_000


class UserRD:
    chatlog: list
    model: str
    consumption: float
    time: datetime
    count: int

    def __init__(
        self,
        chatlog: list = None,
        consumption: float = p_config.limit_for_single_user,
        model: str = p_config.openai_default_model,
        count: int = 0,
    ) -> None:
        self.chatlog = [] if not chatlog else chatlog
        self.time = datetime.now()
        self.consumption = consumption
        self.model = model
        self.count = count

    def check(self) -> bool:
        if self.consumption > 0:
            return False
        if datetime.now() - self.time > timedelta(days=1):
            self.time = datetime.now()
            if self.consumption < p_config.limit_for_single_user:
                self.consumption = p_config.limit_for_single_user
            return False
        return True

    def image(self, count: int = 1):
        if self.model.startswith("gpt-4o"):
            self.consumption += 0.003825 * count
        else:
            self.consumption += 0.00765 * count

    def append(self, response) -> bool:
        pt = response.get("prompt_tokens", 100)
        try:
            self.consumption -= get_comsumption(
                response.get(
                    "usage",
                    {
                        "prompt_tokens": 100,
                        "completion_tokens": 100,
                    },
                ),
                response.get("model", p_config.openai_default_model),
            )
        except Exception:
            self.consumption -= 0.01
        self.count += 1
        self.chatlog.append(response["choices"][0]["message"])

        if pt > p_config.max_history_tokens or self.count >= p_config.max_chatlog_count:
            self.chatlog.pop(0)
