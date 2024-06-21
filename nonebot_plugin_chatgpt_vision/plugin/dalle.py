import aiohttp
from nonebot import get_plugin_config
from enum import Enum

from ..config import Config


class Size(Enum):
    SMALL = "256x256"
    MEDIUM = "512x512"
    LARGE = "1024x1024"


p_config: Config = get_plugin_config(Config)


async def draw_sd(
    prompt: str,
    n_prompt: str = "",
    image: str = None,
    size=Size.LARGE.value,
    times: int = 1,
):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {p_config.sd_key}",
        "Accept": "application/json",
    }
    data = {
        "prompt": prompt,
        "size": size,
        "batch_size": 1,
        "num_inference_steps": 40,
        "guidance_scale": 8,
        "negative_prompt": n_prompt,
    }

    async with aiohttp.ClientSession() as session:
        if image:
            data["image"] = image
            rsp = await session.post(
                url=p_config.sd_url + "image-to-image",
                headers=headers,
                json=data,
            )
        else:
            rsp = await session.post(
                url=p_config.sd_url + "text-to-image",
                headers=headers,
                json=data,
            )
        return await rsp.json()
