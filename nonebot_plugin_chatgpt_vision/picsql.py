import aiohttp
import json
from nonebot import require
from nonebot import get_plugin_config
from urllib.parse import urljoin

from .config import Config
from .config import PicData

p_config = get_plugin_config(Config)


if p_config.image_mode == 0:
    require("nonebot_plugin_savepic")
    from nonebot_plugin_savepic.core.sql import randpic  # type: ignore

else:
    import bs4
    import random
    from urllib.parse import quote

    async def randpic(
        name: str, group: str = "globe", vector: bool = False
    ) -> tuple[PicData, str]:
        try:
            async with aiohttp.ClientSession(
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
                }
            ) as session:
                rsp = await session.get(
                    f"https://www.doutupk.com/search?keyword={quote(name)}"
                )
                if rsp.status != 200:
                    return None, ""
                soup = bs4.BeautifulSoup(await rsp.text(), "html.parser")
                rp = soup.find("div", class_="random_picture")
                if not rp:
                    return None, ""
                images = rp.find_all("img")
                if not images:
                    return None, ""
                length = len(images)
                pic = PicData(
                    name=name,
                    group=group,
                    url=images[random.randint(0, min(length - 1, 10))]["data-backup"],
                )
                return pic, "（随机检索）"
        except Exception:
            return None, ""


async def resnet_50(url: str) -> str:
    """图片分类"""
    if not p_config.image_classification_url:
        return "notfound"
    if not p_config.image_classification_id:
        return "notfound"
    async with aiohttp.ClientSession() as session:
        rsp = await session.post(
            p_config.image_classification_url,
            json={"account_id": p_config.image_classification_id, "image_url": url},
        )
        if rsp.status != 200:
            return "notfound"
        try:
            data = await rsp.text()
            return json.loads(data)["description"].strip().replace('"', "")
        except Exception:
            return "notfound"


async def upload_image(url: str) -> str:
    """上传图片"""
    if not p_config.image_cdn_key:
        return url
    if not p_config.image_cdn_url:
        return url
    if not p_config.image_cdn_put_url:
        return url
    async with aiohttp.ClientSession(
        headers={
            "Authorization": f"Bearer {p_config.image_cdn_key}",
            "Content-Type": "application/json",
        }
    ) as session:
        rsp = await session.post(
            p_config.image_cdn_put_url,
            json={"image_url": url},
        )
        try:
            return urljoin(p_config.image_cdn_url, (await rsp.json())["hash"])
        except Exception:
            return url
