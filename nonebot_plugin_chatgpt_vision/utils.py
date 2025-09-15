import json
import pathlib

USER_NAME_CACHE: dict = {}

QFACE = {}
try:
    with open(pathlib.Path(__file__).parent / "qface.json", "r", encoding="utf-8") as f:
        QFACE = json.load(f)
except Exception:
    QFACE = {}
