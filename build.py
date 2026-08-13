#!/usr/bin/env python3
"""selfstill build：读 canonical/ 生成 dist/（主页 + 内页，视觉层复用 showcase 模板）。

用法：
    python3 build.py               # 正常构建（私密 L3 默认排除）
    python3 build.py --include-private   # 额外包含 03-l3-private.md
"""
import html
import re
import shutil
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent
CANON = ROOT / "canonical"
DIST = ROOT / "dist"
TEMPLATES = ROOT / "templates" / "showcase-html"

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
             f"请先在 canonical/ 下填好 L1–L4（可参考 templates/ 的空白模板）。")
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


def page(title: str, body: str, css: str, js: str) -> str:
    body = hide_simulated_markers(body)
    return (f'<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
            f'<title>{html.escape(title)}</title>\n<style>{css}\n{SIMULATED_CSS}</style>\n</head>\n'
            f'<body>\n{body}\n<script>{js}</script>\n</body>\n</html>\n')


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


def build_home(domains: list, sizes: dict, assets: dict) -> str:
    total = sum(sizes.values()) or 1
    l1_pct = round(sizes["l1"] / total * 100)
    l2_pct = round(sizes["l2"] / total * 100)
    l3_pct = round(sizes["l3"] / total * 100)
    l4_pct = 100 - l1_pct - l2_pct - l3_pct

    hero = (
        '<header class="hero animate">'
        '<span class="eyebrow">selfstill · 蒸馏我</span>'
        '<h1>selfstill · 蒸馏我<br>4 层蒸馏架构可视化</h1>'
        '<p class="sub">把和 AI 的聊天记录，蒸馏成看得见、带来源、AI 也用得上的个人档案。<br>'
        'L1 管行为 · L2 管判断 · L3 管事实 · L4 管方法 — 每一条都有来源，每一条都要经你确认。</p>'
        '<p class="simulated-banner">以下内容为虚构示例，不代表真实个人身份。</p>'
        '<div class="hero-meta">'
        '<span>📁 canonical：<code>canonical/</code></span>'
        '<span>🔗 双载体：Hermes Skill + Codex Profile</span>'
        '<span>🔒 L3 含敏感块，默认不加载</span>'
        '</div></header>'
    )

    kb = round(total / 1024)
    kpis = (
        '<section data-reveal class="reveal"><div class="kpis">'
        f'<div class="kpi animate delay-1"><div class="num" data-count="4" data-suffix="">4</div><div class="label">核心层</div><div class="hint">行为 / 判断 / 事实 / 方法</div></div>'
        f'<div class="kpi animate delay-2"><div class="num" data-count="{kb}" data-suffix="K">{kb}K</div><div class="label">canonical 总字节</div><div class="hint">含 {len(domains)} 个领域手册</div></div>'
        f'<div class="kpi animate delay-3"><div class="num" data-count="{len(domains)}" data-suffix="">{len(domains)}</div><div class="label">领域手册</div><div class="hint">按任务加载，不全量常驻</div></div>'
        f'<div class="kpi animate delay-4"><div class="num" data-count="2" data-suffix="">2</div><div class="label">部署载体</div><div class="hint">Hermes + Codex 同步</div></div>'
        '</div></section>'
    )

    domain_cn = {"agent-work": "智能体协作", "product-work": "产品规划", "writing-style": "写作风格"}
    domain_names = [domain_cn.get(fid, fid) for fid, _t, _d in domains]
    cards = []
    for i, L in enumerate(LAYERS):
        chips = domain_names if L["chips"] == ["__DOMAINS__"] else L["chips"]
        chip_html = "".join(f"<i>{c}</i>" for c in chips)
        size = sizes.get(L["cls"], 0)
        cards.append(
            f'<div class="file-card fc-{CSS_CLS[L["cls"]]} animate delay-{i + 1}">'
            f'<span class="tag">{L["tag"]}</span>'
            f'<h3>{L["name"]}</h3>'
            f'<p class="role">{L["role"]}</p>'
            f'<p class="desc">{L["desc"]}</p>'
            f'<div class="chips">{chip_html}</div>'
            f'<div class="stats"><span>canonical 字节</span><b>{fmt_size(size)}</b></div>'
            f'<div class="links">'
            f'<a href="{L["cls"]}.html" class="primary">📊 可视化版</a>'
            f'<a href="{L["cls"]}-raw.html">📄 原始报告</a>'
            f'</div></div>'
        )
    files = (
        '<section data-reveal class="reveal">'
        '<div class="section-head"><span class="num">1</span><h2>4 个核心文件</h2>'
        '<span class="hint">职责分离 · 互不重叠 · 冲突时按优先级裁决</span></div>'
        f'<div class="file-grid">{"".join(cards)}</div></section>'
    )

    arch_layers = ""
    for L in LAYERS:
        arch_layers += (
            f'<div class="layer layer-{CSS_CLS[L["cls"]]}">'
            f'<span class="name">{L["name"]}</span>'
            f'<span class="role">{L["role"].split("—")[0].strip()}</span>'
            f'<span class="question">{L["role"].split("—")[-1].strip()}</span>'
            f'</div>'
        )
    arch = (
        '<section data-reveal class="reveal">'
        '<div class="section-head"><span class="num">2</span><h2>分层架构 — 职责清晰，互不重叠</h2></div>'
        f'<div class="arch animate">{arch_layers}</div>'
        '<p style="color:var(--text-secondary);font-size:.9rem;text-align:center;margin-top:.5rem">'
        '💡 冲突时按优先级裁决：平台安全 &gt; 用户当前指令 &gt; 任务上下文 &gt; L1 &gt; L2 &gt; L3 — <strong>用户当前明确要求永远高于历史画像</strong>。</p>'
        '</section>'
    )

    ratio = (
        '<section data-reveal class="reveal">'
        f'<div class="section-head"><span class="num">3</span><h2>canonical 内容分布 ≈ {l1_pct} : {l2_pct} : {l3_pct} : {l4_pct}</h2>'
        '<span class="hint">越往下越重 · 按需加载</span></div>'
        f'<div class="ratio-section card animate">'
        f'<div class="ratio-bar" role="img" aria-label="canonical 内容分布 {l1_pct}:{l2_pct}:{l3_pct}:{l4_pct}">'
        f'<div class="seg seg-l1" style="flex:{l1_pct}">L1 {l1_pct}%</div><div class="seg seg-l2" style="flex:{l2_pct}" title="{l2_pct}%">L2 {l2_pct}%</div>'
        f'<div class="seg seg-l3" style="flex:{l3_pct}" title="{l3_pct}%">L3 {l3_pct}%</div><div class="seg seg-pb" style="flex:{l4_pct}" title="{l4_pct}%">L4 {l4_pct}%</div>'
        '</div>'
        '<div class="ratio-legend">'
        '<span><i style="background:#3b82f6"></i>L1 最薄 — 行为规则必须精炼，常驻不耗 token</span>'
        '<span><i style="background:#8b5cf6"></i>L2 中等 — 判断逻辑要覆盖但不啰嗦</span>'
        '<span><i style="background:#10b981"></i>L3 分块 — 按领域切分，只加载需要的块</span>'
        '<span><i style="background:#f59e0b"></i>L4 最重 — 领域深度只在对应任务加载</span>'
        '</div></div></section>'
    )

    example_rows = [
        ("[SIMULATED] ① 捕捉修正信号", "[SIMULATED] L1 · 协作契约", "[SIMULATED] 「看不懂」是修正信号 → 当场照做调整"),
        ("[SIMULATED] ② 表达适配", "[SIMULATED] L1 · 协作契约", "[SIMULATED] 技术内容翻译成业务语言：这是什么 / 为什么 / 影响什么"),
        ("[SIMULATED] ③ 判断路径", "[SIMULATED] L2 · 决策逻辑", "[SIMULATED] 先想明白再动手 — 没听懂可能是方案本身没想清楚"),
        ("[SIMULATED] ④ 背景召回", "[SIMULATED] L3 · 用户画像", "[SIMULATED] 只加载相关块，不碰敏感信息"),
        ("[SIMULATED] ⑤ 汇报方式", "[SIMULATED] L1 · 协作契约", "[SIMULATED] 结论先行、说人话、改动说明 before/after"),
        ("[SIMULATED] ⑥ 沉淀闭环", "[SIMULATED] 蒸馏流程", "[SIMULATED] 新偏好 → 确认后进 canonical，不自动改"),
    ]
    rows = "".join(
        f"<tr><td>{s}</td><td><code>{f}</code></td><td>{d}</td></tr>" for s, f, d in example_rows
    )
    example = (
        '<section data-reveal class="reveal">'
        '<div class="section-head"><span class="num">4</span><h2>协同示例 — 一条反馈从进入到响应 <small>[SIMULATED] 虚构演示</small></h2>'
        '<span class="hint">[SIMULATED] 用户说「这个方案我看不懂」</span></div>'
        '<div class="example animate">'
        '<p class="quote">[SIMULATED] 每个步骤都有明确的文件来源，没有「AI 自己看着办」的模糊地带。</p>'
        f'<table><thead><tr><th>步骤</th><th>文件</th><th>决策</th></tr></thead><tbody>{rows}</tbody></table>'
        '</div></section>'
    )

    principles = [
        ("[SIMULATED] 分层架构", "[SIMULATED] L1 行为 / L2 判断 / L3 事实 / L4 领域，职责互不重叠", "[SIMULATED] canonical/"),
        ("[SIMULATED] L3 不发命令", "[SIMULATED] 用户画像只提供事实和默认偏好，不能发出行为命令", "[SIMULATED] L1 · 优先级"),
        ("[SIMULATED] 用户指令最高", "[SIMULATED] 当前明确要求 &gt; 历史画像；画像不锁定用户", "[SIMULATED] L1 · 硬规则"),
        ("[SIMULATED] 动态事实先查询", "[SIMULATED] 价格 / 时间 / 距离 / 开放状态先真实查询，严禁脑补", "[SIMULATED] L1 · 怎么配合"),
        ("[SIMULATED] 修正即素材", "[SIMULATED] 「看不懂 / 不对」当场调整并记录候选，不靠事后回忆", "[SIMULATED] L1 · 捕捉修正"),
        ("[SIMULATED] 弱信号不采集", "[SIMULATED] 回复变短 / 换话题不记录不归因——无法区分不满与忙碌", "[SIMULATED] L1 · 反馈信号"),
        ("[SIMULATED] 分块加载", "[SIMULATED] L3 按领域分块、L4 按任务加载，不整篇装入上下文", "[SIMULATED] 加载规则"),
        ("[SIMULATED] 可信度标记", "[SIMULATED] 每条带 as_of 时间戳 + confirmed / 待确认", "[SIMULATED] 元数据"),
        ("[SIMULATED] 确认后才写入", "[SIMULATED] 候选经确认后才进 canonical，不自动改", "[SIMULATED] 蒸馏流程"),
    ]
    prin_rows = "".join(
        f"<tr><td>{p}</td><td>{e}</td><td><code>{s}</code></td></tr>" for p, e, s in principles
    )
    prin = (
        '<section data-reveal class="reveal">'
        '<div class="section-head"><span class="num">5</span><h2>核心设计原则</h2></div>'
        f'<div class="principles animate"><table><thead><tr><th>原则</th><th>体现</th><th>出处</th></tr></thead><tbody>{prin_rows}</tbody></table></div>'
        '</section>'
    )

    maintain = (
        '<section data-reveal class="reveal">'
        '<div class="section-head"><span class="num">6</span><h2>维护闭环 — 蒸馏不是一次性的</h2>'
        '<span class="hint">手动更新 · 用户把关</span></div>'
        '<div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(180px,1fr))">'
        '<div class="kpi animate delay-1"><div class="num">①</div><div class="label">追加</div><div class="hint">新对话整理成统一 Markdown，放进 input/</div></div>'
        '<div class="kpi animate delay-2"><div class="num">②</div><div class="label">蒸馏</div><div class="hint">重跑 prompts/distill.md 的蒸馏 prompt</div></div>'
        '<div class="kpi animate delay-3"><div class="num">③</div><div class="label">确认</div><div class="hint">diff 逐条确认后进 canonical</div></div>'
        '<div class="kpi animate delay-4"><div class="num">④</div><div class="label">构建</div><div class="hint">python3 build.py + install.py 写回 AI 工具</div></div>'
        '</div></section>'
    )

    footer = (
        '<footer>'
        '<p>canonical/ · selfstill 蒸馏我 — 让 AI 按使用者的思维方式配合</p>'
        '<p style="margin-top:.5rem">L3 画像含 <code>[SENSITIVE]</code> 健康 / 财务 / 家庭细节，本页只展示结构与标签，不展示敏感原文；本页为示例数据</p>'
        '</footer>'
    )

    body = f'<main id="main-content" class="wrap" role="main">{hero}{kpis}{files}{arch}{ratio}{example}{prin}{maintain}</main>{footer}'
    return page("selfstill · 蒸馏我", VIZ_MENU + body, assets["index_css"], assets["index_js"])


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
        f'<span class="eyebrow">selfstill · 蒸馏我</span>'
        f'<h1>{html.escape(title)}</h1>'
        f'<p class="sub">{sub}</p>'
        '<p class="simulated-banner">以下内容为虚构示例，不代表真实个人身份。</p>'
        f'</header>'
    )
    body = f'<main class="wrap">{hero}{render_visual(content)}</main>'
    return page(title, VIZ_MENU + nav + body, assets["layer_css"], assets["layer_js"])


def build_raw(title: str, text: str, assets: dict) -> str:
    body = (
        '<header class="hero"><a class="back" href="index.html">← 返回主页</a>'
        f'<h1>{html.escape(title)} · 原始报告</h1>'
        '<p class="simulated-banner">以下内容为虚构示例，不代表真实个人身份。</p></header>'
        f'<pre style="background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:1.3rem 1.5rem;font-family:Menlo,monospace;font-size:.84rem;line-height:1.7;white-space:pre-wrap;overflow-wrap:break-word">{html.escape(text)}</pre>'
    )
    return page(title, f'<main class="wrap">{body}</main>', assets["layer_css"], assets["layer_js"])


# ---------- target 产物 ----------

CODEX_AGENTS_HEADER = ("# AGENTS.md — 用户协作契约（selfstill 生成）\n\n"
                       "> 本文件由 selfstill 从 canonical 生成。L2 决策逻辑见 profile/decision-logic.md，"
                       "L3 用户画像见 profile/user-profile.md。\n\n")

HERMES_L1_FRONT = ('---\nname: personal-operating-profile\n'
                   'description: "用户 L1 协作契约：与用户配合的方向与约束。处理任何用户任务前先读本契约，按契约行事。"\n'
                   '---\n\n')


def skill_frontmatter(domain_id: str, description: str) -> str:
    return f'---\nname: {domain_id}\ndescription: "{description}"\n---\n\n'


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


# ---------- main ----------

def main() -> int:
    include_private = "--include-private" in sys.argv

    # 先清空旧产物：任何输入校验失败都不能留下可被误用的旧 dist。
    if DIST.is_symlink() or DIST.exists():
        if DIST.is_symlink() or not DIST.is_dir():
            fail("dist/ 已存在但不是普通目录，拒绝删除或覆盖。")
        shutil.rmtree(DIST)

    require_directory(CANON, "canonical/ 目录")
    require_directory(ROOT / "templates", "templates/ 目录")
    require_directory(TEMPLATES, "showcase 模板目录")
    require_directory(L4_DIR, "L4 领域目录")
    if not any(L4_DIR.glob("*.md")):
        fail("L4 领域目录为空，请至少保留一个领域手册。")

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

    (DIST / "index.html").write_text(build_home(domains, sizes, assets), encoding="utf-8")
    # 内页：复制 showcase 成品脱敏副本（手工编排的呈现效果，不自动生成）
    for name, rendered in template_texts.items():
        (DIST / f"{name}.html").write_text(hide_simulated_markers(rendered), encoding="utf-8")
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
    print(f"完成：dist/index.html + 内页/原始报告 + codex/ + hermes/（L4 领域 {len(domains)} 个）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
