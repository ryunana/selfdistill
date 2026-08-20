#!/usr/bin/env python3
"""selfdistill build：读本地工作区档案并生成 dist/。

用法：
    python3 build.py               # 正常构建（私密 L3 默认排除）
    python3 build.py --include-private   # 额外包含 03-l3-private.md

读取 workspace/canonical/；本地工作区尚未建立时，
使用 examples/demo-profile/canonical/ 构建虚构 Demo。
"""
import html
import json
import re
import shutil
import sys
from pathlib import Path
from typing import NoReturn, Optional

ROOT = Path(__file__).resolve().parent
WORKSPACE_CANON = ROOT / "workspace" / "canonical"
DEMO_CANON = ROOT / "examples" / "demo-profile" / "canonical"
DIST = ROOT / "dist"
TEMPLATES = ROOT / "templates" / "showcase-html"


def _contains_profile_data(path: Path) -> bool:
    """Distinguish an empty tracked workspace placeholder from real profile data."""
    if path.is_symlink() or not path.is_dir():
        return False
    if any(path.glob("*.md")):
        return True
    domains = path / "04-domain-playbooks"
    return domains.is_dir() and any(domains.glob("*.md"))


def _select_canonical_root() -> tuple[Path, str]:
    if _contains_profile_data(WORKSPACE_CANON):
        return WORKSPACE_CANON, "workspace"
    return DEMO_CANON, "demo"


CANON, SOURCE_MODE = _select_canonical_root()

L1 = CANON / "01-l1-contract.md"
L2 = CANON / "02-l2-decision-logic.md"
L3 = CANON / "03-l3-user-profile.md"
L3_PRIVATE = CANON / "03-l3-private.md"
L4_DIR = CANON / "04-domain-playbooks"

BEGIN = "<!-- distill:begin -->"
END = "<!-- distill:end -->"


def fail(msg: str) -> NoReturn:
    print(f"错误：{msg}", file=sys.stderr)
    sys.exit(1)


def require_directory(path: Path, label: str, missing_ok: bool = False) -> None:
    if not path.exists():
        if missing_ok:
            return
        fail(f"缺少{label}：{path.relative_to(ROOT)}")
    if path.is_symlink() or not path.is_dir():
        fail(f"{label}无效或不允许是符号链接：{path.relative_to(ROOT)}")


def read_md(path: Path) -> str:
    if not path.exists():
        fail(f"缺少文件 {path.relative_to(ROOT)}。"
             f"请先在 workspace/canonical/ 下填好 L1–L4"
             f"（可参考 templates/profile/ 的空白模板）。")
    if path.is_symlink() or not path.is_file():
        fail(f"输入文件无效或不允许是符号链接：{path.relative_to(ROOT)}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError:
        fail(f"文件不是 UTF-8 文本：{path.relative_to(ROOT)}")
    except OSError as e:
        fail(f"读取 {path.relative_to(ROOT)} 失败：{e}")
    if not text.strip():
        fail(f"文件为空：{path.relative_to(ROOT)}")
    return text


def wrap(text: str) -> str:
    return f"{BEGIN}\n{text.rstrip()}\n{END}\n"


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    return f"{n / 1024:.1f}K"


def parse_frontmatter(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        fail(f"L4 输入文件无效或不允许是符号链接：{path.relative_to(ROOT)}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError:
        fail(f"文件不是 UTF-8 文本：{path.relative_to(ROOT)}")
    fm: dict = {}
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                m = re.match(r"^(id|description|schema_version)\s*:\s*(.*)$", line.strip())
                if m:
                    fm[m.group(1)] = m.group(2).strip().strip('"\'')
    return fm


def valid_domain_id(value: str, path: Path) -> str:
    """Keep generated skill paths inside dist/ with simple portable IDs."""
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", value):
        fail(f"L4 文件 {path.relative_to(ROOT)} 的 id 无效：只能使用小写字母、数字和连字符。")
    return value


# ---------- markdown → HTML ----------

def inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def md_to_html(text: str) -> str:
    out: list = []
    in_list = False
    in_fm = False
    fm_closed = False
    for line in text.split("\n"):
        if not fm_closed and line.strip() == "---":
            if not in_fm:
                in_fm = True
                continue
            in_fm = False
            fm_closed = True
            continue
        if in_fm:
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            if in_list:
                out.append("</ul>")
                in_list = False
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            continue
        m = re.match(r"^\s*[-*]\s+(.*)$", line)
        if m:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(m.group(1))}</li>")
            continue
        if line.strip() == "":
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p>{inline(line)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def classify_card(text: str) -> str:
    purple = ["身份", "锚定", "是程序", "不是人类", "核心资产", "固定身份", "铁律"]
    danger = ["禁止", "不能", "不行", "绝不", "必须确认", "红线", "硬性", "一律",
              "不采集", "不自动", "只作为数据", "永远高于", "不写"]
    warn = ["注意", "避免", "小心", "谨慎", "慎", "弱信号", "待确认", "边界", "需复核", "评估"]
    ok = ["可以", "允许", "放手", "主动", "优先", "先真实查询", "结论先行", "直接", "明说", "当场"]
    if any(k in text for k in purple):
        return "purple"
    if any(k in text for k in danger):
        return "danger"
    if any(k in text for k in warn):
        return "warn"
    if any(k in text for k in ok):
        return "ok"
    return "ok-2"


TCON = {"ok": "🟢", "ok-2": "🔵", "warn": "🟡", "danger": "🔴", "purple": "🟣"}


def render_visual(text: str) -> str:
    """把 canonical markdown 渲染成 showcase 风格内页：编号 section + 语义卡片网格。"""
    parts: list = []
    cur_head = None
    cur_body: list = []
    card_buf: list = []
    table_buf: list = []
    quote_buf: list = []
    sec_no = 0
    in_fm = False
    fm_closed = False

    def close_section():
        nonlocal cur_head, cur_body
        if cur_head is not None:
            parts.append(
                f'<section class="section" data-reveal><div class="section-head">{cur_head}</div>'
                f'{"".join(cur_body)}</section>'
            )
        cur_head = None
        cur_body = []

    def flush_cards():
        nonlocal card_buf
        if not card_buf:
            return
        cards = []
        for i, item in enumerate(card_buf):
            m = re.match(r"^\s*[-*]\s+(.*)$", item)
            if not m:
                continue
            content = m.group(1)
            lm = re.match(r"\*\*(.+?)\*\*\s*[：:]\s*(.*)", content)
            if lm:
                label, desc = lm.group(1), lm.group(2)
            else:
                label, desc = "", content
            cls = classify_card(content)
            h3 = f"<h3>{inline(label)}</h3>" if label else ""
            cards.append(
                f'<div class="tcard {cls} animate delay-{i + 1}"><span class="ticon">{TCON[cls]}</span>'
                f'{h3}<ul><li>{inline(desc)}</li></ul></div>'
            )
        if cards:
            cur_body.append(f'<div class="grid">{"".join(cards)}</div>')
        card_buf = []

    def flush_table():
        nonlocal table_buf
        if not table_buf:
            return
        rows = []
        for line in table_buf:
            s = line.strip()
            if s.startswith("|") and s.endswith("|"):
                s = s[1:-1]
            rows.append([c.strip() for c in s.split("|")])
        html_rows = []
        for i, cells in enumerate(rows):
            tag = "th" if i == 0 else "td"
            html_rows.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
        cur_body.append(f'<div class="plain-table animate"><table>{"".join(html_rows)}</table></div>')
        table_buf = []

    def flush_quote():
        nonlocal quote_buf
        if not quote_buf:
            return
        paras = []
        for line in quote_buf:
            s = line.strip()
            if s.startswith(">"):
                s = s.lstrip(">").strip()
            if s:
                paras.append(s)
        cur_body.append(f'<div class="banner">{"<br>".join(inline(p) for p in paras)}</div>')
        quote_buf = []

    quote_buf: list = []
    for line in text.split("\n"):
        if not fm_closed and line.strip() == "---":
            if not in_fm:
                in_fm = True
                continue
            in_fm = False
            fm_closed = True
            continue
        if in_fm:
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            flush_cards()
            flush_table()
            flush_quote()
            close_section()
            sec_no += 1
            cur_head = f'<span class="num">{sec_no}</span><h2>{inline(m.group(2))}</h2>'
            continue
        if re.match(r"^\s*[-*]\s+", line):
            flush_table()
            flush_quote()
            card_buf.append(line)
            continue
        if line.strip().startswith("|"):
            flush_cards()
            flush_quote()
            table_buf.append(line)
            continue
        if line.strip().startswith(">"):
            flush_cards()
            flush_table()
            quote_buf.append(line)
            continue
        if line.strip() == "":
            flush_cards()
            flush_table()
            flush_quote()
            continue
        flush_cards()
        flush_table()
        flush_quote()
        cls = classify_card(line)
        cur_body.append(
            f'<div class="tcard {cls} full animate"><span class="ticon">{TCON[cls]}</span>'
            f'<ul><li>{inline(line)}</li></ul></div>'
        )
    flush_cards()
    flush_table()
    flush_quote()
    close_section()
    return "".join(parts)


# ---------- showcase 视觉资产（原样提取）----------

def load_assets() -> dict:
    for path in (TEMPLATES / "index.html", TEMPLATES / "l1.html"):
        if path.is_symlink() or not path.is_file():
            fail(f"模板文件无效或不允许是符号链接：{path.relative_to(ROOT)}")
    try:
        idx = (TEMPLATES / "index.html").read_text(encoding="utf-8")
        lyr = (TEMPLATES / "l1.html").read_text(encoding="utf-8")
    except UnicodeError:
        fail("showcase 模板不是 UTF-8 文本")
    return {
        "index_css": re.search(r"<style[^>]*>(.*?)</style>", idx, flags=re.S).group(1),
        "index_js": re.search(r"<script[^>]*>(.*?)</script>", idx, flags=re.S).group(1),
        "layer_css": re.search(r"<style[^>]*>(.*?)</style>", lyr, flags=re.S).group(1),
        "layer_js": re.search(r"<script[^>]*>(.*?)</script>", lyr, flags=re.S).group(1),
    }


VIZ_MENU = """
<div class="viz-menu">
  <button class="viz-menu-toggle" onclick="toggleMenu()" aria-label="Menu">
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="5" x2="17" y2="5"/><line x1="3" y1="10" x2="17" y2="10"/><line x1="3" y1="15" x2="17" y2="15"/></svg>
  </button>
  <div class="viz-menu-dropdown" id="vizMenuDropdown">
    <button onclick="cycleTheme()"><span id="themeIcon">🌙</span><span id="themeLabel">Dark</span></button>
    <button onclick="cycleLang()"><span>🌐</span><span id="langLabel">EN</span></button>
    <button onclick="window.print()"><span>🖨️</span><span>Print / PDF</span></button>
  </div>
</div>
"""


SIMULATED_CSS = (
    '.simulated-marker{position:absolute!important;width:1px!important;height:1px!important;'
    'padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;'
    'white-space:nowrap!important;border:0!important;}\n'
    '.simulated-banner{margin:.7rem 0 0;color:var(--text-secondary);font-size:.78rem;'
    'letter-spacing:.02em;}\n'
)

def hide_simulated_markers(markup: str) -> str:
    return markup.replace('[SIMULATED]', '<span class="simulated-marker" aria-label="虚构示例">[SIMULATED]</span>')


def page(title: str, body: str, css: str, js: str, i18n_data: Optional[dict] = None) -> str:
    body = hide_simulated_markers(body)
    return (f'<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            f'<title>{html.escape(title)}</title>\n<style>{css}\n{SIMULATED_CSS}</style>\n</head>\n'
            f'<body>\n{body}\n<script>{i18n_script(i18n_data)}</script>\n<script>{js}</script>\n</body>\n</html>\n')


# ---------- i18n（Demo 中 / EN 切换） ----------
# 界面文案走 data-i18n / data-i18n-html 属性，由页面底部 JS 字典切换；
# {var} 占位符由 I18N_DATA（构建期数字）填充。样例正文内容保持中文（那是数据，不是界面）。

I18N: dict[str, dict[str, str]] = {
    "page.title": {"zh": "selfdistill · 蒸馏我", "en": "selfdistill · Distill Yourself"},
    "brand.eyebrow": {"zh": "selfdistill · 蒸馏我", "en": "selfdistill · Distill Yourself"},
    "hero.h1": {"zh": "selfdistill · 蒸馏我<br>4 层蒸馏架构可视化",
                "en": "selfdistill · Distill Yourself<br>4-layer Distillation Architecture"},
    "hero.sub": {"zh": "把和 AI 的聊天记录，蒸馏成看得见、带来源、AI 也用得上的个人档案。<br>"
                       "L1 管行为 · L2 管判断 · L3 管事实 · L4 管方法 — 每一条都有来源，每一条都要经你确认。",
                 "en": "Distill your AI chat history into a visible, sourced, AI-usable personal profile.<br>"
                       "L1 behavior · L2 judgment · L3 facts · L4 methods — every item has a source, every item is confirmed by you."},
    "hero.simulated": {"zh": "以下内容为虚构示例，不代表真实个人身份。",
                       "en": "All content below is fictional sample data; it does not represent a real person."},
    "hero.meta.canonical": {"zh": "📁 档案目录：<code>workspace/canonical/</code>",
                            "en": "📁 Profile dir: <code>workspace/canonical/</code>"},
    "hero.meta.writeback": {"zh": "🔗 写回：Codex / Hermes / DSH",
                            "en": "🔗 Write-back: Codex / Hermes / DSH"},
    "hero.meta.l3": {"zh": "🔒 L3 含敏感块，默认不加载",
                     "en": "🔒 L3 has private blocks, not loaded by default"},
    "kpi.layers.label": {"zh": "核心层", "en": "Core layers"},
    "kpi.layers.hint": {"zh": "行为 / 判断 / 事实 / 方法", "en": "Behavior / Judgment / Facts / Methods"},
    "kpi.bytes.label": {"zh": "canonical 总字节", "en": "canonical bytes"},
    "kpi.bytes.hint": {"zh": "含 {domains} 个领域手册", "en": "{domains} domain playbooks"},
    "kpi.domains.label": {"zh": "领域手册", "en": "Domain playbooks"},
    "kpi.domains.hint": {"zh": "按任务加载，不全量常驻", "en": "Loaded per task, not always resident"},
    "kpi.targets.label": {"zh": "写回目标", "en": "Write-back targets"},
    "kpi.targets.hint": {"zh": "Codex / Hermes / DSH", "en": "Codex / Hermes / DSH"},
    "files.head": {"zh": "4 个核心文件", "en": "4 core files"},
    "files.hint": {"zh": "职责分离 · 互不重叠 · 冲突时按优先级裁决",
                   "en": "Separate concerns · non-overlapping · conflicts resolved by priority"},
    "files.stats": {"zh": "canonical 字节", "en": "canonical bytes"},
    "files.link.visual": {"zh": "📊 可视化版", "en": "📊 Visualized"},
    "files.link.raw": {"zh": "📄 原始报告", "en": "📄 Raw report"},
    "arch.head": {"zh": "分层架构 — 职责清晰，互不重叠",
                  "en": "Layered architecture — clear, non-overlapping responsibilities"},
    "arch.priority": {"zh": "💡 冲突时按优先级裁决：平台安全 &gt; 用户当前指令 &gt; 任务上下文 &gt; L1 &gt; L2 &gt; L3 — "
                            "<strong>用户当前明确要求永远高于历史画像</strong>。",
                      "en": "💡 Conflicts resolve by priority: platform safety &gt; current user instruction &gt; task context "
                            "&gt; L1 &gt; L2 &gt; L3 — <strong>the user's current explicit request always outranks the historical profile</strong>."},
    "ratio.head": {"zh": "canonical 内容分布 ≈ {l1} : {l2} : {l3} : {l4}",
                   "en": "canonical content distribution ≈ {l1} : {l2} : {l3} : {l4}"},
    "ratio.hint": {"zh": "越往下越重 · 按需加载", "en": "Heavier downward · loaded on demand"},
    "ratio.legend.l1": {"zh": "L1 最薄 — 行为规则必须精炼，常驻不耗 token",
                        "en": "L1 thinnest — behavior rules stay lean, always-on without token bloat"},
    "ratio.legend.l2": {"zh": "L2 中等 — 判断逻辑要覆盖但不啰嗦",
                        "en": "L2 medium — judgment logic covers but stays concise"},
    "ratio.legend.l3": {"zh": "L3 分块 — 按领域切分，只加载需要的块",
                        "en": "L3 chunked — split by domain, load only what's needed"},
    "ratio.legend.l4": {"zh": "L4 最重 — 领域深度只在对应任务加载",
                        "en": "L4 heaviest — domain depth loads only for matching tasks"},
    "example.head": {"zh": "协同示例 — 一条反馈从进入到响应 <small>[SIMULATED] 虚构演示</small>",
                     "en": "Collaboration example — a feedback from input to response <small>[SIMULATED] demo</small>"},
    "example.hint": {"zh": "[SIMULATED] 用户说「这个方案我看不懂」",
                     "en": "[SIMULATED] User says: \"I don't understand this proposal\""},
    "example.quote": {"zh": "[SIMULATED] 每个步骤都有明确的文件来源，没有「AI 自己看着办」的模糊地带。",
                      "en": "[SIMULATED] Every step has an explicit file source — no \"the AI just figures it out\" gray zone."},
    "example.th.step": {"zh": "步骤", "en": "Step"},
    "example.th.file": {"zh": "文件", "en": "File"},
    "example.th.decision": {"zh": "决策", "en": "Decision"},
    "prin.head": {"zh": "核心设计原则", "en": "Core design principles"},
    "prin.th.principle": {"zh": "原则", "en": "Principle"},
    "prin.th.how": {"zh": "体现", "en": "How it shows"},
    "prin.th.source": {"zh": "出处", "en": "Source"},
    "maintain.head": {"zh": "维护闭环 — 蒸馏不是一次性的",
                      "en": "Maintenance loop — distillation isn't one-off"},
    "maintain.hint": {"zh": "手动更新 · 用户把关", "en": "Manual updates · user-gated"},
    "maintain.1.label": {"zh": "追加", "en": "Append"},
    "maintain.1.hint": {"zh": "新对话整理成统一 Markdown，放进 workspace/input/",
                        "en": "New chats normalized into unified Markdown, into workspace/input/"},
    "maintain.2.label": {"zh": "蒸馏", "en": "Distill"},
    "maintain.2.hint": {"zh": "重跑 prompts/distill.md 的蒸馏 prompt",
                        "en": "Re-run the prompts/distill.md distillation prompt"},
    "maintain.3.label": {"zh": "确认", "en": "Confirm"},
    "maintain.3.hint": {"zh": "diff 逐条确认后进 workspace/canonical/",
                        "en": "Approve each diff line, then into workspace/canonical/"},
    "maintain.4.label": {"zh": "构建", "en": "Build"},
    "maintain.4.hint": {"zh": "python3 build.py + install.py 写回 AI 工具",
                        "en": "python3 build.py + install.py write back to AI tools"},
    "footer.1": {"zh": "workspace/canonical/ · selfdistill 蒸馏我 — 让 AI 按使用者的思维方式配合",
                 "en": "workspace/canonical/ · selfdistill — make AI work the way you think"},
    "footer.template": {"zh": "workspace/canonical/ · selfdistill 蒸馏我 — 脱敏后的本地蒸馏示例",
                        "en": "workspace/canonical/ · selfdistill — de-identified local distillation sample"},
    "footer.2": {"zh": "L3 画像含 <code>[SENSITIVE]</code> 健康 / 财务 / 家庭细节，本页只展示结构与标签，不展示敏感原文；本页为示例数据",
                 "en": "L3 profile contains <code>[SENSITIVE]</code> health / finance / family details; this page shows structure "
                       "and labels only, never the sensitive text; sample data"},
    "nav.home": {"zh": "← 主目录", "en": "← Home"},
    "nav.raw": {"zh": "📄 原始版", "en": "📄 Raw"},
    "raw.back": {"zh": "← 返回主页", "en": "← Back to home"},
    "raw.suffix": {"zh": " · 原始报告", "en": " · Raw report"},
    "eyebrow.file": {"zh": "selfdistill · 蒸馏我 · 第 {n}/4 文件", "en": "selfdistill · Distill Yourself · File {n}/4"},
}


def i18n_script(i18n_data: Optional[dict] = None) -> str:
    """生成页面底部的中/EN 切换脚本（字典 + 数据 + applyLang/cycleLang）。"""
    data_json = json.dumps(i18n_data or {}, ensure_ascii=False)
    # JS 侧按语言索引：I18N[lang][key]
    by_lang: dict[str, dict[str, str]] = {"zh": {}, "en": {}}
    for _key, _pair in I18N.items():
        by_lang["zh"][_key] = _pair["zh"]
        by_lang["en"][_key] = _pair["en"]
    dict_json = json.dumps(by_lang, ensure_ascii=False)
    return (
        "window.I18N=" + dict_json + ";"
        "window.I18N_DATA=" + data_json + ";"
        "var savedLang=null;try{savedLang=localStorage.getItem('viz-lang')}catch(e){}"
        "var currentLang=savedLang||((navigator.language||'').toLowerCase().indexOf('zh')===0?'zh':'en');"
        "function i18nFill(s){return s.replace(/\\{(\\w+)\\}/g,function(m,v){return (window.I18N_DATA&&window.I18N_DATA[v]!==undefined)?window.I18N_DATA[v]:m})}"
        "function applyLang(lang){"
        "var dict=window.I18N[lang]||window.I18N.zh;currentLang=lang;"
        "document.documentElement.lang=(lang==='zh'?'zh-CN':'en');"
        "var a=document.querySelectorAll('[data-i18n]');for(var i=0;i<a.length;i++){var k=a[i].getAttribute('data-i18n');if(dict[k]!==undefined)a[i].textContent=i18nFill(dict[k])}"
        "var b=document.querySelectorAll('[data-i18n-html]');for(var j=0;j<b.length;j++){var k2=b[j].getAttribute('data-i18n-html');if(dict[k2]!==undefined)b[j].innerHTML=i18nFill(dict[k2])}"
        "var t=document.querySelector('title');if(t&&dict['page.title']!==undefined)t.textContent=dict['page.title'];"
        "var lb=document.getElementById('langLabel');if(lb)lb.textContent=(lang==='zh'?'EN':'中文');"
        "try{localStorage.setItem('viz-lang',lang)}catch(e){}"
        "}"
        "function cycleLang(){applyLang(currentLang==='zh'?'en':'zh')}"
        "applyLang(currentLang);"
    )


def inject_i18n_template(markup: str, i18n_data: Optional[dict] = None) -> str:
    """给静态模板（l1-l4.html）注入语言切换按钮与 i18n 脚本；模板文案自带 data-i18n 属性。"""
    button = '<button onclick="cycleLang()"><span>🌐</span><span id="langLabel">EN</span></button>'
    if '<button onclick="window.print()">' in markup:
        markup = markup.replace('<button onclick="window.print()">',
                                '<button onclick="window.print()">' + button, 1)
    if "</body>" in markup:
        markup = markup.replace("</body>", f"<script>{i18n_script(i18n_data)}</script></body>", 1)
    return markup


# ---- 按 LAYERS/示例/原则 数据生成 i18n 键（zh 来自现有中文，en 为翻译） ----

LAYER_EN = {
    "l1": {
        "tag": "🛡️ Contract", "name": "L1 · Collaboration Contract",
        "role": "How to work — boundaries + feedback + reporting + priorities",
        "desc": "The user's core asset. Defines <strong>how to work together</strong>: lead with conclusions, plain language, "
                "verify dynamic facts first, own mistakes, transparent change reports.<br><br>"
                "<b>Key design:</b> three authorization tiers (analyze-only → don't touch / implement → go ahead / external → confirm first), "
                "strong vs weak feedback signals, 6-level priority resolution; L3 can never issue behavior commands.",
        "chips": ["Identity", "Authorization", "Feedback", "Reporting", "Priorities 1-6"],
    },
    "l2": {
        "tag": "🧭 Decision Logic", "name": "L2 · Decision Logic",
        "role": "How to decide — trade-offs + priorities + red lines + stability flags",
        "desc": "[SIMULATED] Describes <strong>how a fictional sample user thinks when facing a decision</strong>, so AI can "
                "advise and write with that mindset.<br><br>"
                "<b>Key design:</b> core modules (product judgment / AI scenarios / problem framing / project governance) load "
                "with judgment-heavy tasks; domain modules (design portfolio / copywriting / photo &amp; travel) load only for "
                "matching tasks; every principle carries a stability flag, temporary entries re-enter review automatically.",
        "chips": ["Product &amp; needs", "AI scenarios", "Problem framing", "Project governance", "Design portfolio", "Copywriting", "Photo &amp; travel"],
    },
    "l3": {
        "tag": "👤 User Profile", "name": "L3 · User Profile",
        "role": "Who the user is — domain chunks + sensitivity tiers",
        "desc": "Treats the user as a specific person: design career, family, health, travel, interests, content experiments, "
                "AI usage background.<br><br>"
                "<b>Key design:</b> chunked by domain, load only the chunks the current task needs; real sensitive chunks are "
                "not loaded by default; demo data carries <code>as_of</code> and <code>simulated</code> states.",
        "chips": ["Basics", "Design portfolio", "Working skills", "Family 🔒", "Health &amp; finance 🔒", "Travel", "Interests", "Content experiments", "AI background"],
    },
    "l4": {
        "tag": "📚 Domain Playbooks", "name": "L4 · Domain Playbooks",
        "role": "By task type — deep domain playbooks",
        "desc": "A third loading level above L1/L2/L3: how to do specific domains. Several playbooks are already distilled "
                "and keep growing with the project.<br><br>"
                "<b>Key design:</b> each playbook binds to a skill/domain and loads only when a task enters that domain — "
                "no dilution of the always-on context.",
        "chips": [],  # __DOMAINS__：en 沿用中文领域名（专有名词），见 build_home
    },
}

EXAMPLE_EN = {
    0: ("[SIMULATED] ① Capture correction signals", "[SIMULATED] L1 · Contract", "[SIMULATED] \"I don't get it\" is a correction signal → adjust immediately"),
    1: ("[SIMULATED] ② Adapt expression", "[SIMULATED] L1 · Contract", "[SIMULATED] Translate technical content into business language: what / why / impact"),
    2: ("[SIMULATED] ③ Judgment path", "[SIMULATED] L2 · Decision Logic", "[SIMULATED] Think it through first — confusion may mean the plan itself is unclear"),
    3: ("[SIMULATED] ④ Recall background", "[SIMULATED] L3 · Profile", "[SIMULATED] Load only relevant chunks, never touch sensitive info"),
    4: ("[SIMULATED] ⑤ Reporting style", "[SIMULATED] L1 · Contract", "[SIMULATED] Lead with conclusions, plain language, before/after change notes"),
    5: ("[SIMULATED] ⑥ Closing the loop", "[SIMULATED] Distillation flow", "[SIMULATED] New preferences → confirmed, then into workspace/canonical/; never auto-edited"),
}

PRINCIPLES_EN = [
    ("[SIMULATED] Layered architecture", "[SIMULATED] L1 behavior / L2 judgment / L3 facts / L4 domains, non-overlapping", "[SIMULATED] workspace/canonical/"),
    ("[SIMULATED] L3 never commands", "[SIMULATED] Profile provides facts and defaults only, never behavior commands", "[SIMULATED] L1 · Priority"),
    ("[SIMULATED] User instruction wins", "[SIMULATED] Current explicit request &gt; historical profile; profile never locks the user in", "[SIMULATED] L1 · Hard rule"),
    ("[SIMULATED] Verify dynamic facts first", "[SIMULATED] Price / time / distance / availability: query first, never guess", "[SIMULATED] L1 · How to work"),
    ("[SIMULATED] Corrections are raw material", "[SIMULATED] Adjust on the spot and record candidates; no after-the-fact recall", "[SIMULATED] L1 · Capture corrections"),
    ("[SIMULATED] Weak signals not collected", "[SIMULATED] Shorter replies / topic changes: not recorded, not attributed — can't tell dissatisfaction from busyness", "[SIMULATED] L1 · Feedback"),
    ("[SIMULATED] Chunked loading", "[SIMULATED] L3 by domain, L4 by task — never load whole documents into context", "[SIMULATED] Loading rules"),
    ("[SIMULATED] Credibility markers", "[SIMULATED] Every item carries as_of timestamp + confirmed / pending", "[SIMULATED] Metadata"),
    ("[SIMULATED] Write only after confirmation", "[SIMULATED] Candidates enter canonical only after confirmation, never auto-edited", "[SIMULATED] Distillation flow"),
]


# ---------- 主页 ----------

LAYERS = [
    {
        "cls": "l1", "tag": "🛡️ 协作契约", "name": "L1 · 协作契约",
        "role": "怎么配合 — 授权边界 + 反馈信号 + 汇报规则 + 优先级",
        "desc": "用户核心资产。定义<strong>与用户配合的方式</strong>：结论先行、说人话、动态事实先查询、错了就认、变动透明汇报。<br><br>"
                "<b>关键设计：</b>授权三档（只分析→不动 / 实现→放手 / 对外→先确认）、强反馈信号与弱信号分流、冲突时按 6 级优先级裁决，L3 永远不能发出行为命令。",
        "chips": ["身份锚定", "授权边界", "反馈信号", "汇报规则", "优先级 1-6"],
    },
    {
        "cls": "l2", "tag": "🧭 决策逻辑", "name": "L2 · 决策逻辑",
        "role": "怎么判断 — 取舍原则 + 优先级 + 红线 + 稳定性标记",
        "desc": "[SIMULATED] 描述<strong>面对一个决策时虚构示例使用者通常怎么想</strong>，让 AI 按这套示例思路给建议、写方案。<br><br>"
                "<b>关键设计：</b>核心模块（产品判断 / AI 场景 / 问题框架 / 项目治理）随涉及判断的任务加载；领域模块（设计作品集 / 文案 / 摄影旅行）只在对口任务加载；每条原则标注稳定性，temporary 条目自动进入复核。",
        "chips": ["产品与需求", "AI 场景", "问题框架", "项目治理", "设计作品集", "文案内容", "摄影旅行"],
    },
    {
        "cls": "l3", "tag": "👤 用户画像", "name": "L3 · 用户画像",
        "role": "用户是谁 — 领域分块 + 敏感分级",
        "desc": "把使用者当成具体的人：设计职业、家庭、健康、旅行、兴趣、内容实验、AI 使用背景。<br><br>"
                "<b>关键设计：</b>按领域分块、只加载当前任务需要的块；真实敏感块默认不加载；演示数据标注 <code>as_of</code> 和 <code>simulated</code> 状态。",
        "chips": ["基本信息", "设计作品集", "工作能力", "家庭关系 🔒", "健康财务 🔒", "旅行", "兴趣生活", "内容实验", "AI 背景"],
    },
    {
        "cls": "l4", "tag": "📚 领域打法", "name": "L4 · 领域打法",
        "role": "按任务类型 — 深度领域操作手册",
        "desc": "L1/L2/L3 之上的第三级加载：具体领域怎么做。已沉淀多个手册，随项目沉淀持续扩充。<br><br>"
                "<b>关键设计：</b>每个 playbook 绑定一个技能/领域，任务进入该领域时才加载——不稀释常驻上下文。",
        "chips": ["__DOMAINS__"],
    },
]

# showcase CSS 用 fc-pb/layer-pb/seg-pb 表示 L4（playbooks 橙色），映射 class
CSS_CLS = {"l1": "l1", "l2": "l2", "l3": "l3", "l4": "pb"}

# 协同示例行（zh 为默认文案，en 见 EXAMPLE_EN；键 example.r{i}.{col}）
EXAMPLE_ROWS = [
    ("[SIMULATED] ① 捕捉修正信号", "[SIMULATED] L1 · 协作契约", "[SIMULATED] 「看不懂」是修正信号 → 当场照做调整"),
    ("[SIMULATED] ② 表达适配", "[SIMULATED] L1 · 协作契约", "[SIMULATED] 技术内容翻译成业务语言：这是什么 / 为什么 / 影响什么"),
    ("[SIMULATED] ③ 判断路径", "[SIMULATED] L2 · 决策逻辑", "[SIMULATED] 先想明白再动手 — 没听懂可能是方案本身没想清楚"),
    ("[SIMULATED] ④ 背景召回", "[SIMULATED] L3 · 用户画像", "[SIMULATED] 只加载相关块，不碰敏感信息"),
    ("[SIMULATED] ⑤ 汇报方式", "[SIMULATED] L1 · 协作契约", "[SIMULATED] 结论先行、说人话、改动说明 before/after"),
    ("[SIMULATED] ⑥ 沉淀闭环", "[SIMULATED] 蒸馏流程", "[SIMULATED] 新偏好 → 确认后进 workspace/canonical/，不自动改"),
]

# 核心设计原则行（zh 默认，en 见 PRINCIPLES_EN；键 prin.row.{i}.{col}）
PRINCIPLES = [
    ("[SIMULATED] 分层架构", "[SIMULATED] L1 行为 / L2 判断 / L3 事实 / L4 领域，职责互不重叠", "[SIMULATED] workspace/canonical/"),
    ("[SIMULATED] L3 不发命令", "[SIMULATED] 用户画像只提供事实和默认偏好，不能发出行为命令", "[SIMULATED] L1 · 优先级"),
    ("[SIMULATED] 用户指令最高", "[SIMULATED] 当前明确要求 &gt; 历史画像；画像不锁定用户", "[SIMULATED] L1 · 硬规则"),
    ("[SIMULATED] 动态事实先查询", "[SIMULATED] 价格 / 时间 / 距离 / 开放状态先真实查询，严禁脑补", "[SIMULATED] L1 · 怎么配合"),
    ("[SIMULATED] 修正即素材", "[SIMULATED] 「看不懂 / 不对」当场调整并记录候选，不靠事后回忆", "[SIMULATED] L1 · 捕捉修正"),
    ("[SIMULATED] 弱信号不采集", "[SIMULATED] 回复变短 / 换话题不记录不归因——无法区分不满与忙碌", "[SIMULATED] L1 · 反馈信号"),
    ("[SIMULATED] 分块加载", "[SIMULATED] L3 按领域分块、L4 按任务加载，不整篇装入上下文", "[SIMULATED] 加载规则"),
    ("[SIMULATED] 可信度标记", "[SIMULATED] 每条带 as_of 时间戳 + confirmed / 待确认", "[SIMULATED] 元数据"),
    ("[SIMULATED] 确认后才写入", "[SIMULATED] 候选经确认后才进 workspace/canonical/，不自动改", "[SIMULATED] 蒸馏流程"),
]

# 由数据生成 i18n 键（layer.* / example.r* / prin.r*）
for _L in LAYERS:
    _cls = _L["cls"]
    _en = LAYER_EN[_cls]
    I18N[f"layer.{_cls}.name"] = {"zh": _L["name"], "en": _en["name"]}
    I18N[f"layer.{_cls}.tag"] = {"zh": _L["tag"], "en": _en["tag"]}
    I18N[f"layer.{_cls}.role"] = {"zh": _L["role"], "en": _en["role"]}
    I18N[f"layer.{_cls}.desc"] = {"zh": _L["desc"], "en": _en["desc"]}
    if _L["chips"] != ["__DOMAINS__"]:
        I18N[f"layer.{_cls}.chips"] = {
            "zh": "".join(f"<i>{c}</i>" for c in _L["chips"]),
            "en": "".join(f"<i>{c}</i>" for c in _en["chips"]),
        }
for _i, (_s, _f, _d) in enumerate(EXAMPLE_ROWS, start=1):
    _en = EXAMPLE_EN[_i - 1]
    I18N[f"example.r{_i}.1"] = {"zh": _s, "en": _en[0]}
    I18N[f"example.r{_i}.2"] = {"zh": _f, "en": _en[1]}
    I18N[f"example.r{_i}.3"] = {"zh": _d, "en": _en[2]}
for _i, (_p, _e, _s) in enumerate(PRINCIPLES, start=1):
    _en = PRINCIPLES_EN[_i - 1]
    I18N[f"prin.r{_i}.1"] = {"zh": _p, "en": _en[0]}
    I18N[f"prin.r{_i}.2"] = {"zh": _e, "en": _en[1]}
    I18N[f"prin.r{_i}.3"] = {"zh": _s, "en": _en[2]}


def build_home(domains: list, sizes: dict, assets: dict) -> str:
    total = sum(sizes.values()) or 1
    l1_pct = round(sizes["l1"] / total * 100)
    l2_pct = round(sizes["l2"] / total * 100)
    l3_pct = round(sizes["l3"] / total * 100)
    l4_pct = 100 - l1_pct - l2_pct - l3_pct
    kb = round(total / 1024)
    i18n_data = {"kb": kb, "domains": len(domains), "l1": l1_pct, "l2": l2_pct, "l3": l3_pct, "l4": l4_pct}

    hero = (
        '<header class="hero animate">'
        '<span class="eyebrow" data-i18n="brand.eyebrow">selfdistill · 蒸馏我</span>'
        '<h1 data-i18n-html="hero.h1">selfdistill · 蒸馏我<br>4 层蒸馏架构可视化</h1>'
        '<p class="sub" data-i18n-html="hero.sub">把和 AI 的聊天记录，蒸馏成看得见、带来源、AI 也用得上的个人档案。<br>'
        'L1 管行为 · L2 管判断 · L3 管事实 · L4 管方法 — 每一条都有来源，每一条都要经你确认。</p>'
        '<p class="simulated-banner" data-i18n="hero.simulated">以下内容为虚构示例，不代表真实个人身份。</p>'
        '<div class="hero-meta">'
        '<span data-i18n-html="hero.meta.canonical">📁 档案目录：<code>workspace/canonical/</code></span>'
        '<span data-i18n="hero.meta.writeback">🔗 写回：Codex / Hermes / DSH</span>'
        '<span data-i18n="hero.meta.l3">🔒 L3 含敏感块，默认不加载</span>'
        '</div></header>'
    )

    kpis = (
        '<section data-reveal class="reveal"><div class="kpis">'
        f'<div class="kpi animate delay-1"><div class="num" data-count="4">4</div>'
        f'<div class="label" data-i18n="kpi.layers.label">核心层</div>'
        f'<div class="hint" data-i18n="kpi.layers.hint">行为 / 判断 / 事实 / 方法</div></div>'
        f'<div class="kpi animate delay-2"><div class="num" data-count="{kb}">{kb}K</div>'
        f'<div class="label" data-i18n="kpi.bytes.label">canonical 总字节</div>'
        f'<div class="hint" data-i18n="kpi.bytes.hint">含 {len(domains)} 个领域手册</div></div>'
        f'<div class="kpi animate delay-3"><div class="num" data-count="{len(domains)}">{len(domains)}</div>'
        f'<div class="label" data-i18n="kpi.domains.label">领域手册</div>'
        f'<div class="hint" data-i18n="kpi.domains.hint">按任务加载，不全量常驻</div></div>'
        f'<div class="kpi animate delay-4"><div class="num" data-count="3">3</div>'
        f'<div class="label" data-i18n="kpi.targets.label">写回目标</div>'
        f'<div class="hint" data-i18n="kpi.targets.hint">Codex / Hermes / DSH</div></div>'
        '</div></section>'
    )

    domain_cn = {"agent-work": "智能体协作", "product-work": "产品规划", "writing-style": "写作风格"}
    domain_names = [domain_cn.get(fid, fid) for fid, _t, _d in domains]
    if LAYERS[3]["chips"] == ["__DOMAINS__"]:
        I18N["layer.l4.chips"] = {
            "zh": "".join(f"<i>{c}</i>" for c in domain_names),
            "en": "".join(f"<i>{c}</i>" for c in domain_names),  # 领域名是内容，双语一致
        }
    cards = []
    for i, L in enumerate(LAYERS):
        cls = L["cls"]
        chips = domain_names if L["chips"] == ["__DOMAINS__"] else L["chips"]
        chip_html = "".join(f"<i>{c}</i>" for c in chips)
        size = sizes.get(L["cls"], 0)
        cards.append(
            f'<div class="file-card fc-{CSS_CLS[L["cls"]]} animate delay-{i + 1}">'
            f'<span class="tag" data-i18n="layer.{cls}.tag">{L["tag"]}</span>'
            f'<h3 data-i18n="layer.{cls}.name">{L["name"]}</h3>'
            f'<p class="role" data-i18n="layer.{cls}.role">{L["role"]}</p>'
            f'<p class="desc" data-i18n-html="layer.{cls}.desc">{L["desc"]}</p>'
            f'<div class="chips" data-i18n-html="layer.{cls}.chips">{chip_html}</div>'
            f'<div class="stats"><span data-i18n="files.stats">canonical 字节</span><b>{fmt_size(size)}</b></div>'
            f'<div class="links">'
            f'<a href="{L["cls"]}.html" class="primary" data-i18n="files.link.visual">📊 可视化版</a>'
            f'<a href="{L["cls"]}-raw.html" data-i18n="files.link.raw">📄 原始报告</a>'
            f'</div></div>'
        )
    files = (
        '<section data-reveal class="reveal">'
        '<div class="section-head"><span class="num">1</span><h2 data-i18n="files.head">4 个核心文件</h2>'
        '<span class="hint" data-i18n="files.hint">职责分离 · 互不重叠 · 冲突时按优先级裁决</span></div>'
        f'<div class="file-grid">{"".join(cards)}</div></section>'
    )

    arch_layers = ""
    for L in LAYERS:
        cls = L["cls"]
        arch_layers += (
            f'<div class="layer layer-{CSS_CLS[L["cls"]]}">'
            f'<span class="name" data-i18n="layer.{cls}.name">{L["name"]}</span>'
            f'<span class="role" data-i18n="layer.{cls}.role.short">{L["role"].split("—")[0].strip()}</span>'
            f'<span class="question" data-i18n="layer.{cls}.role.long">{L["role"].split("—")[-1].strip()}</span>'
            f'</div>'
        )
    for L in LAYERS:
        cls = L["cls"]
        en_role = LAYER_EN[cls]["role"]
        I18N[f"layer.{cls}.role.short"] = {"zh": L["role"].split("—")[0].strip(),
                                           "en": en_role.split("—")[0].strip()}
        I18N[f"layer.{cls}.role.long"] = {"zh": L["role"].split("—")[-1].strip(),
                                          "en": en_role.split("—")[-1].strip()}
    arch = (
        '<section data-reveal class="reveal">'
        '<div class="section-head"><span class="num">2</span><h2 data-i18n="arch.head">分层架构 — 职责清晰，互不重叠</h2></div>'
        f'<div class="arch animate">{arch_layers}</div>'
        '<p style="color:var(--text-secondary);font-size:.9rem;text-align:center;margin-top:.5rem" '
        'data-i18n-html="arch.priority">'
        '💡 冲突时按优先级裁决：平台安全 &gt; 用户当前指令 &gt; 任务上下文 &gt; L1 &gt; L2 &gt; L3 — '
        '<strong>用户当前明确要求永远高于历史画像</strong>。</p>'
        '</section>'
    )

    ratio = (
        '<section data-reveal class="reveal">'
        f'<div class="section-head"><span class="num">3</span><h2 data-i18n="ratio.head">canonical 内容分布 ≈ {l1_pct} : {l2_pct} : {l3_pct} : {l4_pct}</h2>'
        '<span class="hint" data-i18n="ratio.hint">越往下越重 · 按需加载</span></div>'
        f'<div class="ratio-section card animate">'
        f'<div class="ratio-bar" role="img" aria-label="canonical {l1_pct}:{l2_pct}:{l3_pct}:{l4_pct}">'
        f'<div class="seg seg-l1" style="flex:{l1_pct}">L1 {l1_pct}%</div><div class="seg seg-l2" style="flex:{l2_pct}" title="{l2_pct}%">L2 {l2_pct}%</div>'
        f'<div class="seg seg-l3" style="flex:{l3_pct}" title="{l3_pct}%">L3 {l3_pct}%</div><div class="seg seg-pb" style="flex:{l4_pct}" title="{l4_pct}%">L4 {l4_pct}%</div>'
        '</div>'
        '<div class="ratio-legend">'
        '<span data-i18n="ratio.legend.l1"><i style="background:#3b82f6"></i>L1 最薄 — 行为规则必须精炼，常驻不耗 token</span>'
        '<span data-i18n="ratio.legend.l2"><i style="background:#8b5cf6"></i>L2 中等 — 判断逻辑要覆盖但不啰嗦</span>'
        '<span data-i18n="ratio.legend.l3"><i style="background:#10b981"></i>L3 分块 — 按领域切分，只加载需要的块</span>'
        '<span data-i18n="ratio.legend.l4"><i style="background:#f59e0b"></i>L4 最重 — 领域深度只在对应任务加载</span>'
        '</div></div></section>'
    )

    rows = "".join(
        f'<tr><td data-i18n="example.r{i}.1">{s}</td><td><code data-i18n="example.r{i}.2">{f}</code></td>'
        f'<td data-i18n="example.r{i}.3">{d}</td></tr>'
        for i, (s, f, d) in enumerate(EXAMPLE_ROWS, start=1)
    )
    example = (
        '<section data-reveal class="reveal">'
        '<div class="section-head"><span class="num">4</span><h2 data-i18n-html="example.head">协同示例 — 一条反馈从进入到响应 <small>[SIMULATED] 虚构演示</small></h2>'
        '<span class="hint" data-i18n="example.hint">[SIMULATED] 用户说「这个方案我看不懂」</span></div>'
        '<div class="example animate">'
        '<p class="quote" data-i18n="example.quote">[SIMULATED] 每个步骤都有明确的文件来源，没有「AI 自己看着办」的模糊地带。</p>'
        '<table><thead><tr><th data-i18n="example.th.step">步骤</th><th data-i18n="example.th.file">文件</th>'
        '<th data-i18n="example.th.decision">决策</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
        '</div></section>'
    )

    prin_rows = "".join(
        f'<tr><td data-i18n="prin.r{i}.1">{p}</td><td data-i18n="prin.r{i}.2">{e}</td>'
        f'<td><code data-i18n="prin.r{i}.3">{s}</code></td></tr>'
        for i, (p, e, s) in enumerate(PRINCIPLES, start=1)
    )
    prin = (
        '<section data-reveal class="reveal">'
        '<div class="section-head"><span class="num">5</span><h2 data-i18n="prin.head">核心设计原则</h2></div>'
        '<div class="principles animate"><table><thead>'
        f'<tr><th data-i18n="prin.th.principle">原则</th><th data-i18n="prin.th.how">体现</th><th data-i18n="prin.th.source">出处</th></tr>'
        f'</thead><tbody>{prin_rows}</tbody></table></div>'
        '</section>'
    )

    maintain = (
        '<section data-reveal class="reveal">'
        '<div class="section-head"><span class="num">6</span><h2 data-i18n="maintain.head">维护闭环 — 蒸馏不是一次性的</h2>'
        '<span class="hint" data-i18n="maintain.hint">手动更新 · 用户把关</span></div>'
        '<div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(180px,1fr))">'
        '<div class="kpi animate delay-1"><div class="num">①</div><div class="label" data-i18n="maintain.1.label">追加</div><div class="hint" data-i18n="maintain.1.hint">新对话整理成统一 Markdown，放进 workspace/input/</div></div>'
        '<div class="kpi animate delay-2"><div class="num">②</div><div class="label" data-i18n="maintain.2.label">蒸馏</div><div class="hint" data-i18n="maintain.2.hint">重跑 prompts/distill.md 的蒸馏 prompt</div></div>'
        '<div class="kpi animate delay-3"><div class="num">③</div><div class="label" data-i18n="maintain.3.label">确认</div><div class="hint" data-i18n="maintain.3.hint">diff 逐条确认后进 workspace/canonical/</div></div>'
        '<div class="kpi animate delay-4"><div class="num">④</div><div class="label" data-i18n="maintain.4.label">构建</div><div class="hint" data-i18n="maintain.4.hint">python3 build.py + install.py 写回 AI 工具</div></div>'
        '</div></section>'
    )

    footer = (
        '<footer>'
        f'<p data-i18n="footer.1">workspace/canonical/ · selfdistill 蒸馏我 — 让 AI 按使用者的思维方式配合</p>'
        f'<p style="margin-top:.5rem" data-i18n-html="footer.2">L3 画像含 <code>[SENSITIVE]</code> 健康 / 财务 / 家庭细节，本页只展示结构与标签，不展示敏感原文；本页为示例数据</p>'
        '</footer>'
    )

    body = f'<main id="main-content" class="wrap" role="main">{hero}{kpis}{files}{arch}{ratio}{example}{prin}{maintain}</main>{footer}'
    return page("selfdistill · 蒸馏我", VIZ_MENU + body, assets["index_css"], assets["index_js"], i18n_data=i18n_data)


# ---------- 内页 ----------

def build_layer(title: str, content: str, slug: str, sub: str, assets: dict) -> str:
    nav = (
        '<nav class="sibling-nav"><div class="sibling-nav-inner wrap" style="padding:0">'
        '<a href="index.html" class="back">← 主目录</a><span class="divider">|</span>'
        f'<a href="l1.html" class="pill {"active" if slug == "l1" else ""}">L1</a>'
        f'<a href="l2.html" class="pill {"active" if slug == "l2" else ""}">L2</a>'
        f'<a href="l3.html" class="pill {"active" if slug == "l3" else ""}">L3</a>'
        f'<a href="l4.html" class="pill {"active" if slug == "l4" else ""}">L4</a>'
        f'<span class="divider">|</span><a href="{slug}-raw.html" class="pill original">📄 原始版</a>'
        '</div></nav>'
    )
    hero = (
        f'<header class="hero">'
        f'<span class="eyebrow">selfdistill · 蒸馏我</span>'
        f'<h1>{html.escape(title)}</h1>'
        f'<p class="sub">{sub}</p>'
        '<p class="simulated-banner">以下内容为虚构示例，不代表真实个人身份。</p>'
        f'</header>'
    )
    body = f'<main class="wrap">{hero}{render_visual(content)}</main>'
    return page(title, VIZ_MENU + nav + body, assets["layer_css"], assets["layer_js"])


def build_raw(title: str, text: str, assets: dict) -> str:
    body = (
        '<header class="hero"><a class="back" href="index.html" data-i18n="raw.back">← 返回主页</a>'
        f'<h1>{html.escape(title)}<span data-i18n="raw.suffix"> · 原始报告</span></h1>'
        '<p class="simulated-banner" data-i18n="hero.simulated">以下内容为虚构示例，不代表真实个人身份。</p></header>'
        f'<pre style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.3rem 1.5rem;font-family:Menlo,monospace;font-size:.84rem;line-height:1.7;white-space:pre-wrap;overflow-wrap:break-word">{html.escape(text)}</pre>'
    )
    return page(title, f'<main class="wrap">{body}</main>', assets["layer_css"], assets["layer_js"])


# ---------- target 产物 ----------

CODEX_AGENTS_HEADER = ("# AGENTS.md — 用户协作契约（selfdistill 生成）\n\n"
                       "> 本文件由 selfdistill 从 canonical 生成。L2 决策逻辑见 profile/decision-logic.md，"
                       "L3 用户画像见 profile/user-profile.md。\n\n")

HERMES_L1_FRONT = ('---\nname: personal-operating-profile\n'
                   'description: "用户 L1 协作契约：与用户配合的方向与约束。处理任何用户任务前先读本契约，按契约行事。"\n'
                   '---\n\n')


def skill_frontmatter(domain_id: str, description: str) -> str:
    return f'---\nname: {domain_id}\ndescription: "{description}"\n---\n\n'


DSH_L2_DESCRIPTION = ("用户 L2 决策逻辑：取舍原则、优先级与红线。"
                      "任务涉及权衡、排序、风险判断或红线时按需加载。")
DSH_L3_DESCRIPTION = ("用户 L3 个人事实档案：身份、经历、偏好。"
                      "任务需要了解用户背景、身份或偏好时按需加载。")

# WorkBuddy：description 说明加载时机，供 WorkBuddy 判断何时调用该 skill。
WORKBUDDY_L2_DESCRIPTION = ("用户 L2 决策逻辑：取舍原则、优先级与红线（selfdistill 蒸馏档案）。"
                            "任务涉及权衡、排序、风险判断或红线时加载本技能。")
WORKBUDDY_L3_DESCRIPTION = ("用户 L3 个人事实档案：身份、经历、偏好（selfdistill 蒸馏档案）。"
                            "任务需要了解用户背景、身份或偏好时加载本技能；私密内容不默认包含。")


def dsh_skill_content(skill_name: str, description: str, text: str) -> str:
    """DSH skill 内容：frontmatter 必须在文件顶部，distill 标记在正文内作所有权标签。"""
    return (f"---\nname: {skill_name}\ndescription: \"{description}\"\n---\n\n"
            f"{BEGIN}\n{text.rstrip()}\n{END}\n")


def build_targets(l1: str, l2: str, l3: str, domains: list) -> None:
    codex = DIST / "codex"
    (codex / "profile").mkdir(parents=True, exist_ok=True)
    (codex / "skills").mkdir(parents=True, exist_ok=True)
    (codex / "AGENTS.md").write_text(wrap(CODEX_AGENTS_HEADER + l1), encoding="utf-8")
    (codex / "profile" / "decision-logic.md").write_text(wrap(l2), encoding="utf-8")
    (codex / "profile" / "user-profile.md").write_text(wrap(l3), encoding="utf-8")
    for fid, text, desc in domains:
        (codex / "skills" / fid).mkdir(parents=True, exist_ok=True)
        (codex / "skills" / fid / "SKILL.md").write_text(
            wrap(skill_frontmatter(fid, desc) + text), encoding="utf-8")

    hermes = DIST / "hermes"
    (hermes / "skills" / "personal-operating-profile" / "references").mkdir(parents=True, exist_ok=True)
    (hermes / "skills").mkdir(parents=True, exist_ok=True)
    (hermes / "skills" / "personal-operating-profile" / "SKILL.md").write_text(
        wrap(HERMES_L1_FRONT + l1), encoding="utf-8")
    (hermes / "skills" / "personal-operating-profile" / "references" / "decision-logic.md").write_text(
        wrap(l2), encoding="utf-8")
    (hermes / "skills" / "personal-operating-profile" / "references" / "user-profile.md").write_text(
        wrap(l3), encoding="utf-8")
    for fid, text, desc in domains:
        (hermes / "skills" / fid).mkdir(parents=True, exist_ok=True)
        (hermes / "skills" / fid / "SKILL.md").write_text(
            wrap(skill_frontmatter(fid, desc) + text), encoding="utf-8")

    # DSH：persona 只放 L1（协作契约，非敏感）；L2/L3/L4 为按需加载的 skill。
    dsh = DIST / "dsh"
    dsh.mkdir(parents=True, exist_ok=True)
    (dsh / "persona.md").write_text(wrap(l1), encoding="utf-8")
    (dsh / "skills").mkdir(parents=True, exist_ok=True)
    for skill_name, description, text in [
        ("selfdistill-decision-logic", DSH_L2_DESCRIPTION, l2),
        ("selfdistill-user-profile", DSH_L3_DESCRIPTION, l3),
    ]:
        (dsh / "skills" / skill_name).mkdir(parents=True, exist_ok=True)
        (dsh / "skills" / skill_name / "SKILL.md").write_text(
            dsh_skill_content(skill_name, description, text), encoding="utf-8")
    for fid, text, desc in domains:
        skill_name = f"selfdistill-{fid}"
        (dsh / "skills" / skill_name).mkdir(parents=True, exist_ok=True)
        (dsh / "skills" / skill_name / "SKILL.md").write_text(
            dsh_skill_content(skill_name, desc, text), encoding="utf-8")

    # WorkBuddy：L1 常驻进用户级记忆 MEMORY.md（每次会话注入，短且非敏感）；
    # L2/L3/L4 写成 ~/.workbuddy/skills/ 下的 skill（按需加载，敏感内容不默认进上下文）。
    # SKILL.md 用与 DSH 相同的 frontmatter（name + description）格式，WorkBuddy 原生兼容。
    wb = DIST / "workbuddy"
    wb.mkdir(parents=True, exist_ok=True)
    (wb / "l1.md").write_text(wrap(l1), encoding="utf-8")
    (wb / "skills").mkdir(parents=True, exist_ok=True)
    for skill_name, description, text in [
        ("selfdistill-decision-logic", WORKBUDDY_L2_DESCRIPTION, l2),
        ("selfdistill-user-profile", WORKBUDDY_L3_DESCRIPTION, l3),
    ]:
        (wb / "skills" / skill_name).mkdir(parents=True, exist_ok=True)
        (wb / "skills" / skill_name / "SKILL.md").write_text(
            dsh_skill_content(skill_name, description, text), encoding="utf-8")
    for fid, text, desc in domains:
        skill_name = f"selfdistill-{fid}"
        (wb / "skills" / skill_name).mkdir(parents=True, exist_ok=True)
        (wb / "skills" / skill_name / "SKILL.md").write_text(
            dsh_skill_content(skill_name, desc, text), encoding="utf-8")


# ---------- main ----------

def main() -> int:
    include_private = "--include-private" in sys.argv

    # 先清空旧产物：任何输入校验失败都不能留下可被误用的旧 dist。
    if DIST.is_symlink() or DIST.exists():
        if DIST.is_symlink() or not DIST.is_dir():
            fail("dist/ 已存在但不是普通目录，拒绝删除或覆盖。")
        shutil.rmtree(DIST)

    canon_label = f"{CANON.relative_to(ROOT).as_posix()}/ 目录"
    require_directory(CANON, canon_label)
    require_directory(ROOT / "templates", "templates/ 目录")
    require_directory(TEMPLATES, "showcase 模板目录")
    require_directory(L4_DIR, "L4 领域目录")
    if not any(L4_DIR.glob("*.md")):
        fail("L4 领域目录为空，请至少保留一个领域手册。")

    if CANON == DEMO_CANON:
        print("提示：workspace/canonical/ 尚无档案，正在使用虚构 Demo 构建。")

    l1 = read_md(L1)
    l2 = read_md(L2)
    l3 = read_md(L3)
    if include_private and L3_PRIVATE.exists():
        l3 = l3.rstrip() + "\n\n" + read_md(L3_PRIVATE)
        print("提示：已包含 03-l3-private.md（私密 L3）。")
    elif L3_PRIVATE.exists():
        print("提示：检测到 03-l3-private.md（私密 L3），默认排除。加 --include-private 才包含。")

    domains = []
    if L4_DIR.exists():
        for p in sorted(L4_DIR.glob("*.md")):
            fm = parse_frontmatter(p)
            fid = valid_domain_id(fm.get("id", p.stem), p)
            desc = fm.get("description", "")
            try:
                domain_text = p.read_text(encoding="utf-8")
            except UnicodeError:
                fail(f"文件不是 UTF-8 文本：{p.relative_to(ROOT)}")
            if not domain_text.strip():
                fail(f"文件为空：{p.relative_to(ROOT)}")
            domains.append((fid, domain_text, desc))

    template_texts = {}
    for name in ["l1", "l2", "l3", "l4"]:
        src = TEMPLATES / f"{name}.html"
        if not src.exists():
            fail(f"缺少内页模板 templates/showcase-html/{name}.html")
        if src.is_symlink() or not src.is_file():
            fail(f"模板文件无效或不允许是符号链接：{src.relative_to(ROOT)}")
        try:
            rendered = src.read_text(encoding="utf-8")
        except UnicodeError:
            fail(f"文件不是 UTF-8 文本：{src.relative_to(ROOT)}")
        if not rendered.strip():
            fail(f"文件为空：{src.relative_to(ROOT)}")
        template_texts[name] = rendered
    assets = load_assets()

    sizes = {
        "l1": L1.stat().st_size,
        "l2": L2.stat().st_size,
        "l3": L3.stat().st_size,
        "l4": sum(p.stat().st_size for p in L4_DIR.glob("*.md")) if L4_DIR.exists() else 0,
    }

    DIST.mkdir(parents=True, exist_ok=True)
    (DIST / ".selfdistill-build.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_mode": SOURCE_MODE,
                "source_path": CANON.relative_to(ROOT).as_posix(),
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    (DIST / "index.html").write_text(build_home(domains, sizes, assets), encoding="utf-8")
    # 内页：复制 showcase 成品脱敏副本（手工编排的呈现效果，不自动生成）
    # 注入中/EN 切换按钮与 i18n 脚本（模板文案自带 data-i18n 属性）；{n} 为页序
    for name, rendered in template_texts.items():
        (DIST / f"{name}.html").write_text(
            inject_i18n_template(hide_simulated_markers(rendered), {"n": int(name[1])}),
            encoding="utf-8")
    # raw 页：从 canonical 生成
    layers = [
        ("L1 协作契约", l1, "l1"),
        ("L2 决策逻辑", l2, "l2"),
        ("L3 用户画像", l3, "l3"),
    ]
    l4_parts = [text for _fid, text, _d in domains]
    layers.append(("L4 领域打法", "\n\n".join(l4_parts), "l4"))
    for title, text, slug in layers:
        (DIST / f"{slug}-raw.html").write_text(build_raw(title, text, assets), encoding="utf-8")

    build_targets(l1, l2, l3, domains)
    print(f"完成：dist/index.html + 内页/原始报告 + codex/ + hermes/ + dsh/ + workbuddy/（L4 领域 {len(domains)} 个）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
