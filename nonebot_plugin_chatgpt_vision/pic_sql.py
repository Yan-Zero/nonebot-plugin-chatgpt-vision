from nonebot import get_driver
from nonebot import get_plugin_config

from .config import Config

p_config = get_plugin_config(Config)
gdriver = get_driver()


if p_config.image_model == 0:
    import dashscope
    import asyncpg
    import sqlalchemy as sa
    from http import HTTPStatus
    from dashscope import TextEmbedding
    from sqlalchemy.ext.asyncio.session import AsyncSession
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import select
    from .model import PicData

    _async_database = None
    _async_embedding_database = None

    def word2vec(word: str) -> list[float]:
        resp = TextEmbedding.call(
            model=TextEmbedding.Models.text_embedding_v2, input=word, text_type="query"
        )
        if resp.status_code != HTTPStatus.OK:
            raise RuntimeError("Dashscope API Error")
        return resp.output["embeddings"][0]["embedding"]

    def AsyncDatabase():
        if not _async_database:
            raise RuntimeError("Database is not initialized")
        return _async_database

    async def update_vec(pic: PicData):
        if pic is None:
            return
        if not pic.u_vec_text:
            return

        async with AsyncSession(_async_database) as db_session:
            # if pic.u_vec_text:
            pic.u_vec_text = False
            await _async_embedding_database.execute(
                "UPDATE savepic_word2vec SET embedding = $1 WHERE id = $2",
                str(word2vec(pic.name)),
                pic.id,
            )
            await db_session.merge(pic)
            await db_session.commit()

    async def randpic(
        name: str, group: str = "globe", vector: bool = False
    ) -> tuple[PicData, str]:
        name = name.strip().replace("%", r"\%").replace("_", r"\_")

        async with AsyncSession(_async_database) as db_session:
            if not name:
                pic = await db_session.scalar(
                    select(PicData)
                    .where(sa.or_(PicData.group == group, PicData.group == "globe"))
                    .where(PicData.name != "")
                    .order_by(sa.func.random())
                )
                await update_vec(pic)
                return pic, ""

            if pic := await db_session.scalar(
                select(PicData)
                .where(sa.or_(PicData.group == group, PicData.group == "globe"))
                .where(PicData.name.ilike(f"%{name}%"))
                .order_by(sa.func.random())
            ):
                await update_vec(pic)
                return pic, ""

            if not vector:
                return None, ""

            datas = await _async_embedding_database.fetch(
                (
                    "SELECT id FROM savepic_word2vec "
                    "WHERE embedding IS NOT NULL "
                    "ORDER BY embedding <#> $1 LIMIT 8;"
                ),
                str(word2vec(name)),
            )
            if pic := await db_session.scalar(
                select(PicData)
                .where(sa.or_(PicData.group == group, PicData.group == "globe"))
                .where(PicData.id.in_([i["id"] for i in datas]))
                .where(PicData.name != "")
                .order_by(sa.func.random())
            ):
                await update_vec(pic)
                return pic, "（语义向量相似度检索）"

            pic = await db_session.scalar(
                select(PicData)
                .where(sa.or_(PicData.group == group, PicData.group == "globe"))
                .where(PicData.name != "")
                .order_by(sa.func.random())
            )
            return pic, "（随机检索）"

    async def init_db():
        global _async_database, _async_embedding_database
        _async_database = create_async_engine(
            p_config.savepic_sqlurl,
            future=True,
            pool_size=2,
            # connect_args={"statement_cache_size": 0},
        )
        if p_config.embedding_sqlurl.startswith("postgresql+asyncpg"):
            p_config.embedding_sqlurl = "postgresql" + p_config.embedding_sqlurl[18:]
        _async_embedding_database = await asyncpg.create_pool(
            p_config.embedding_sqlurl,
            min_size=1,
            max_size=2,  # , statement_cache_size=0,
        )
        dashscope.api_key = p_config.dashscope_api

    @gdriver.on_startup
    async def _():
        if not p_config.savepic_sqlurl:
            raise Exception("请配置 savepic_sqlurl")

        await init_db()

else:
    import aiohttp
    import bs4
    import random
    from urllib.parse import quote

    async def randpic(
        name: str, group: str = "globe", vector: bool = False
    ) -> tuple[PicData, str]:
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
