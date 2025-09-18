import re
import json
import pathlib

from typing import List
from lxml import etree  # type: ignore
from xml.sax.saxutils import escape as _xml_escape, quoteattr as _xml_q

USER_NAME_CACHE: dict = {}

QFACE = {}
try:
    with open(pathlib.Path(__file__).parent / "qface.json", "r", encoding="utf-8") as f:
        QFACE = json.load(f)
except Exception:
    QFACE = {}


def fix_xml(xml: str) -> str:
    """
    流式把脏“类 XML”规约为**合规 XML 片段**（可能包含多个顶层 <p>）。
    新增规则：同一 <p> 内最多 1 个 <reply/>；第 2 个起自动分段，并在该 <reply/> 后补一个空格。
    """
    VOID = {"mention", "reply", "image", "face", "br"}
    IGNORE = {"time", "name", "uid"}
    # NEW: 判定“可见内容”的简易正则（存在非空白，或出现这些可见标记）
    _VISIBLE_TAGS_RE = re.compile(r"<(code|br|mention|reply|image|face)\b", re.I)

    def _escape_text(s: str) -> str:
        if not s:
            return ""
        s = s.replace("&nbsp;", " ").replace("\u00a0", " ")
        return _xml_escape(s)

    # NEW: outside/cur 是否有“可见内容”
    def _has_visible(fragment: str) -> bool:
        if not fragment:
            return False
        # 去掉所有 XML 标签再看是否有非空白
        text_only = re.sub(r"<[^>]+>", "", fragment)
        if text_only.strip():
            return True
        # 或包含可见的自闭合/块级标记
        return bool(_VISIBLE_TAGS_RE.search(fragment))

    class _Target:
        def __init__(self):
            self.out_ps: List[str] = []
            self.cur: List[str] = []
            self.outside: List[str] = []
            self.p_depth: int = 0
            self.in_code: bool = False
            self.code_lang: str = "text"
            self.code_buf: List[str] = []
            self.skip_stack: List[str] = []
            self.reply_seen_in_p: bool = False

        def _append_text(self, s: str):
            if not s:
                return
            if self.in_code:
                self.code_buf.append(s)
                return
            if self.p_depth > 0:
                self.cur.append(_escape_text(s))
            else:
                # NEW: p 外的纯空白一律丢弃，避免生成空 <p>
                s_norm = s.replace("&nbsp;", " ").replace("\u00a0", " ")
                if s_norm.strip():
                    self.outside.append(_escape_text(s_norm))
                # else: 忽略

        def _emit_fragment_into_current_scope(self, frag: str):
            if not frag:
                return
            if self.p_depth > 0:
                self.cur.append(frag)
            else:
                self.outside.append(frag)

        def _emit_void(self, name: str, attrs: dict):
            if name == "mention":
                uid = attrs.get("uid", "10001")
                return f"<mention uid={_xml_q(uid)}/>"
            if name == "reply":
                mid = attrs.get("id", "0")
                return f"<reply id={_xml_q(mid)}/>"
            if name == "image":
                url = attrs.get("url")
                name_attr = attrs.get("name")
                if url and str(url).startswith("http"):
                    return f"<image url={_xml_q(url)}/>"
                if name_attr:
                    return f"<image name={_xml_q(name_attr)}/>"
                return ""
            if name == "face":
                face_id = attrs.get("id", "0")
                return f"<face id={_xml_q(face_id)}/>"
            if name == "br":
                return "<br/>"
            return ""

        def _flush_p(self):
            if self.cur:
                self.out_ps.append("<p>" + "".join(self.cur) + "</p>")
                self.cur.clear()
            self.reply_seen_in_p = False

        def _flush_outside_as_p(self):
            if not self.outside:
                return
            fragment = "".join(self.outside)
            # 仅当“可见”时才包成段；否则丢弃（避免 <p>\n\n</p>）
            if _has_visible(fragment):
                self.out_ps.append("<p>" + fragment + "</p>")
            self.outside.clear()

        def start(self, tag: str, attrs: dict):
            if tag == "root":
                return

            if self.in_code:
                frag = "<" + tag
                for k, v in (attrs or {}).items():
                    frag += f" {k}={_xml_q(v)}"
                frag += ">"
                self.code_buf.append(frag)
                return

            if tag in IGNORE:
                self.skip_stack.append(tag)
                return

            if tag in VOID:
                frag = self._emit_void(tag, attrs or {})
                if not frag:
                    self.skip_stack.append(tag)
                    return

                if tag == "reply":
                    if self.p_depth > 0:
                        if self.reply_seen_in_p:
                            # 第二个及以后 reply：切段
                            self._flush_p()
                        self._emit_fragment_into_current_scope(frag)
                        self.reply_seen_in_p = True
                    else:
                        self._emit_fragment_into_current_scope(frag)
                    self.skip_stack.append(tag)
                    return

                self._emit_fragment_into_current_scope(frag)
                self.skip_stack.append(tag)
                return

            if tag == "code":
                self.in_code = True
                self.code_lang = (attrs or {}).get("lang", "text") or "text"
                self.code_buf.clear()
                self.skip_stack.append("code")
                return

            if tag == "p":
                if self.p_depth == 0 and self.outside:
                    # 先把 p 外的内容按可见性打包
                    self._flush_outside_as_p()
                self.p_depth += 1
                if self.p_depth == 1:
                    self.reply_seen_in_p = False
                return

            self.skip_stack.append("")

        def data(self, text: str):
            if not text:
                return
            if (
                (not self.in_code)
                and self.skip_stack
                and self.skip_stack[-1] in (IGNORE | VOID | {"code"})
            ):
                return
            self._append_text(text)

        def end(self, tag: str):
            if tag == "root":
                return

            if self.in_code:
                if tag == "code":
                    if self.skip_stack and self.skip_stack[-1] == "code":
                        self.skip_stack.pop()
                    code_text = "".join(self.code_buf)
                    frag = (
                        "<code lang="
                        + _xml_q(self.code_lang or "text")
                        + ">"
                        + _escape_text(code_text)
                        + "</code>"
                    )
                    self._emit_fragment_into_current_scope(frag)
                    self.code_buf.clear()
                    self.code_lang = "text"
                    self.in_code = False
                else:
                    self.code_buf.append(f"</{tag}>")
                return

            if self.skip_stack:
                top = self.skip_stack[-1]
                if top and top == tag:
                    self.skip_stack.pop()
                    return
                if top == "":
                    self.skip_stack.pop()
                    return

            if tag == "p":
                if self.p_depth > 0:
                    self.p_depth -= 1
                    if self.p_depth == 0:
                        self._flush_p()
                return
            # 其它未知标签：无操作

        def comment(self, text: str):
            return

        def close(self) -> str:
            if self.in_code:
                code_text = "".join(self.code_buf)
                frag = (
                    "<code lang="
                    + _xml_q(self.code_lang or "text")
                    + ">"
                    + _escape_text(code_text)
                    + "</code>"
                )
                self._emit_fragment_into_current_scope(frag)
                self.code_buf.clear()
                self.in_code = False
                self.code_lang = "text"

            if self.p_depth > 0:
                self.p_depth = 0
                self._flush_p()

            # 打包 outside（仅当可见）
            self._flush_outside_as_p()

            return "".join(self.out_ps)

    target = _Target()
    parser = etree.XMLParser(
        target=target,
        recover=True,
        resolve_entities=False,
        no_network=True,
    )
    parser.feed("<root>")
    parser.feed(xml)
    parser.feed("</root>")
    return parser.close()
