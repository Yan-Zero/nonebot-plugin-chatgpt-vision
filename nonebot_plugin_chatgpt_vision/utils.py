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

    def _escape_text(s: str) -> str:
        if not s:
            return ""
        s = s.replace("&nbsp;", " ").replace("\u00a0", " ")
        return _xml_escape(s)

    class _Target:
        def __init__(self):
            self.out_ps: List[str] = []  # 已完成段
            self.cur: List[str] = []  # 当前 <p> 内容
            self.outside: List[str] = []  # <p> 之外的片段（最终会包装为自己的 <p>）
            self.p_depth: int = 0
            self.in_code: bool = False
            self.code_lang: str = "text"
            self.code_buf: List[str] = []
            self.skip_stack: List[str] = []
            # —— 新增：当前 <p> 内是否已出现 reply ——
            self.reply_seen_in_p: bool = False

        def _append_text(self, s: str):
            if not s:
                return
            if self.in_code:
                self.code_buf.append(s)
            elif self.p_depth > 0:
                self.cur.append(_escape_text(s))
            else:
                self.outside.append(_escape_text(s))

        def _flush_p(self):
            if self.cur:
                self.out_ps.append("<p>" + "".join(self.cur) + "</p>")
                self.cur.clear()
            # 每次结束一个逻辑段后，清除该段的 reply 计数
            self.reply_seen_in_p = False

        def _emit_fragment_into_current_scope(self, frag: str):
            if not frag:
                return
            if self.p_depth > 0:
                self.cur.append(frag)
            else:
                self.outside.append(frag)

        def _emit_void(self, name: str, attrs: dict):
            # 规范化生成自闭合标签（字符串）
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

        def start(self, tag: str, attrs: dict):
            if tag == "root":
                return

            if self.in_code:
                # 在 code 中：把起始标签按文本写入
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
                    # 即使无法规范化，也进入 skip，屏蔽其内部脏文本
                    self.skip_stack.append(tag)
                    return

                if tag == "reply":
                    # —— 核心逻辑：一个 <p> 只能有一个 reply ——
                    if self.p_depth > 0:
                        if self.reply_seen_in_p:
                            # 已经出现过 reply：切段
                            self._flush_p()
                        # 在新/当前段开头放 reply
                        self._emit_fragment_into_current_scope(frag)
                        self.reply_seen_in_p = True
                    else:
                        # 不在 <p> 内：按顺序落在 outside，最终会被包成自己的 <p>
                        self._emit_fragment_into_current_scope(frag)
                    # 屏蔽其内部文本
                    self.skip_stack.append(tag)
                    return

                # 其它 VOID 正常放入当前位置
                self._emit_fragment_into_current_scope(frag)
                # 为兼容错误成对写法，进入 skip 直至 end
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
                    # 先把 p 外的内容按顺序打包成一个 <p>
                    self.out_ps.append("<p>" + "".join(self.outside) + "</p>")
                    self.outside.clear()
                self.p_depth += 1
                # 进入一个新逻辑段（或嵌套 p 继续同段），只有最外层 p_depth==1 才需要 reset
                if self.p_depth == 1:
                    self.reply_seen_in_p = False
                return

            # 未知标签：仅当容器，不输出标签自身
            self.skip_stack.append("")  # 占位

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
            # 未闭合 code：自动补闭
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
            # 未闭合 p：结束当前段
            if self.p_depth > 0:
                self.p_depth = 0
                self._flush_p()
            # 还有 p 外的内容：按顺序包成一条 <p>
            if self.outside:
                self.out_ps.append("<p>" + "".join(self.outside) + "</p>")
                self.outside.clear()
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
