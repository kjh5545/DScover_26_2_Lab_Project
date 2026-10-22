"""데모(app.py) 디자인 모듈 — 로직 없음, 표현만.

레퍼런스 (10/20 해준·팀 합의):
- 색감·전반 톤: ada.com — 흰 바탕, 딥 네이비 텍스트(#293754), 파랑 포인트(#1266C7),
  부드러운 블루그레이 보더(#D3DDE8), 둥근 모서리
- 아이콘: abridge.com — 선(stroke) 기반 라인 아이콘 (fill 없음, 둥근 끝)

판정 4색은 의미 고정(통과=초록/탈락=빨강/모름=호박/등록 후 확인=회청)이고,
색만으로 뜻을 전하지 않도록 항상 아이콘+한국어 라벨과 함께 쓴다.
"""

import html

import streamlit as st

# ── 디자인 토큰 (Ada 톤) ────────────────────────────────────
T = {
    "bg": "#FFFFFF", "tint": "#F4F7FA", "border": "#D3DDE8",
    "ink": "#293754", "muted": "#64748F", "accent": "#1266C7", "accent_soft": "#E7F0FB",
}
STATUS = {  # verdict/final → (텍스트색, 배경색)  — 흰 바탕에서 텍스트 대비 4.5:1 이상
    "pass": ("#1E7A55", "#E3F2EB"),
    "fail": ("#C0452F", "#FBE9E4"),
    "unknown": ("#8A5E07", "#FAF0D7"),
    "post_enrollment": ("#51627E", "#EBF0F7"),
    "eligible": ("#1E7A55", "#E3F2EB"),
    "probably_eligible": ("#1E7A55", "#EFF7F0"),
    "insufficient_info": ("#8A5E07", "#FAF0D7"),
    "ineligible": ("#C0452F", "#FBE9E4"),
}
LABEL = {
    "pass": "통과", "fail": "탈락", "unknown": "모름", "post_enrollment": "등록 후 확인",
    "eligible": "적격", "probably_eligible": "적격 가능 (등록 후 확인 필요)",
    "insufficient_info": "정보 부족 (확인 질문 필요)", "ineligible": "부적격",
}

# ── Abridge풍 라인 아이콘 (stroke, fill 없음, 둥근 끝) ──────
_PATHS = {
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "x": '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "help": ('<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3"/>'
             '<line x1="12" y1="17" x2="12.01" y2="17"/>'),
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "pulse": '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    "doc": ('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
            '<polyline points="14 2 14 8 20 8"/>'),
    "chat": '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
}
_VERDICT_ICON = {
    "pass": "check", "fail": "x", "unknown": "help", "post_enrollment": "clock",
    "eligible": "check", "probably_eligible": "check", "insufficient_info": "help", "ineligible": "x",
}


def icon(name: str, size: int = 14) -> str:
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
            f'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{_PATHS[name]}</svg>')


def badge(verdict: str, large: bool = False) -> str:
    """판정 배지 — 아이콘 + 라벨 (색만으로 의미를 전하지 않음)."""
    fg, bg = STATUS.get(verdict, (T["muted"], T["tint"]))
    cls = "vb vb-lg" if large else "vb"
    label = LABEL.get(verdict, verdict)
    return (f'<span class="{cls}" style="color:{fg};background:{bg};">'
            f'{icon(_VERDICT_ICON.get(verdict, "help"), 15 if large else 13)}{label}</span>')


def change(prev: str, now: str) -> str:
    """재평가로 바뀐 판정: 이전 → 이후."""
    return f'{badge(prev)}<span class="arrow">→</span>{badge(now)}'


def rank_card(rank: str, nct_id: str, title: str, final: str, counts: dict) -> str:
    """추천 순위 카드."""
    chips = "".join(
        f'<span class="chip" style="color:{STATUS[v][0]};background:{STATUS[v][1]};">'
        f'{icon(_VERDICT_ICON[v], 12)}{LABEL[v]} {counts.get(v, 0)}</span>'
        for v in ("pass", "unknown", "post_enrollment") if counts.get(v)
    ) or ""
    fails = counts.get("fail_ids")
    if fails:
        chips += (f'<span class="chip" style="color:{STATUS["fail"][0]};background:{STATUS["fail"][1]};">'
                  f'{icon("x", 12)}탈락 기준 {html.escape(", ".join(fails))}</span>')
    return (f'<div class="card"><div class="card-top"><span class="rank">{html.escape(rank)}</span>'
            f'<span class="nct">{html.escape(nct_id)}</span>{badge(final, large=True)}</div>'
            f'<div class="card-title">{html.escape(title)}</div>'
            f'<div class="chips">{chips}</div></div>')


def screening_table(rows: list[dict]) -> str:
    """스크리닝 시트 표. rows: {id, kind, text, verdict_html, evidence}"""
    body = "".join(
        f'<tr><td class="cid">{html.escape(r["id"])}</td>'
        f'<td class="kind">{html.escape(r["kind"])}</td>'
        f'<td class="crit">{html.escape(r["text"])}</td>'
        f'<td class="verd">{r["verdict_html"]}</td>'
        f'<td class="ev">{html.escape(r["evidence"])}</td></tr>'
        for r in rows
    )
    return ('<table class="sheet"><thead><tr><th>ID</th><th>구분</th><th>기준</th>'
            '<th>판정</th><th>근거</th></tr></thead><tbody>' + body + "</tbody></table>")


def detail_group(verdict: str, heading: str, items: list[dict]) -> str:
    """추천 근거 패널의 판정 그룹: 배지 헤더 + (기준 ID·원문·근거 인용) 행들.

    items: [{"id", "text", "evidence"}]
    """
    if not items:
        return ""
    fg, _bg = STATUS.get(verdict, (T["muted"], T["tint"]))
    rows = "".join(
        f'<div class="ev-row"><div class="ev-head"><span class="ev-id" style="color:{fg};">'
        f'{html.escape(it["id"])}</span><span class="ev-text">{html.escape(it["text"])}</span></div>'
        + (f'<div class="ev-quote">{html.escape(it["evidence"])}</div>' if it.get("evidence") else "")
        for it in items
    )
    return (f'<div class="ev-group"><div class="ev-group-h">{badge(verdict)}'
            f'<span class="ev-count">{len(items)}개</span>'
            f'<span class="ev-why">{html.escape(heading)}</span></div>{rows}</div>')


def rank_reason(pos: int, final: str, n_pass: int, n_total: int, n_unknown: int) -> str:
    """이 순위가 나온 코드 규칙 설명 한 줄."""
    return (f'<div class="why-line">{icon("pulse", 13)} <b>{pos}위인 이유</b> — '
            f'최종 판단 <b>{LABEL.get(final, final)}</b> · 통과 <b>{n_pass}/{n_total}</b> · '
            f'모름 <b>{n_unknown}</b>개. 순위는 판단 등급 → 통과 비율 → 모름 적은 순의 '
            f'<b>코드 규칙</b>으로 정해져 같은 입력이면 항상 같습니다.</div>')


def header() -> None:
    st.markdown(
        f'<div class="hero"><div class="hero-icon">{icon("pulse", 26)}</div>'
        '<div><div class="hero-title">인터랙티브 임상시험 추천</div>'
        '<div class="hero-sub">환자 설명을 넣으면 임상시험을 찾아 조건을 대조하고, '
        '모자란 정보는 질문으로 채워 근거와 함께 추천합니다</div></div></div>'
        '<div class="disclaimer">본 시스템의 출력은 의학적 자문이 아닌 연구·참고용입니다. '
        '실제 임상시험 참여는 반드시 의료진과 상의하세요.</div>',
        unsafe_allow_html=True,
    )


def section(label: str, icon_name: str = "doc") -> None:
    st.markdown(f'<div class="sec-h">{icon(icon_name, 17)}<span>{html.escape(label)}</span></div>',
                unsafe_allow_html=True)


def inject_css() -> None:
    st.markdown(f"""<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css');

html, body, [class*="st-"], button, input, textarea {{
  font-family: "Pretendard Variable", Pretendard, -apple-system, "Apple SD Gothic Neo", sans-serif;
  font-weight: 500;
}}
/* 위 전역 폰트가 Material 아이콘 폰트까지 덮어쓰면 아이콘이 글자로 보임 → 아이콘 폰트 복원 */
[data-testid="stIconMaterial"], .material-symbols-rounded, [class*="material-symbols"] {{
  font-family: "Material Symbols Rounded" !important; font-weight: 400 !important;
}}
.stApp {{ background: {T["bg"]}; color: {T["ink"]}; }}
.stButton > button {{ font-weight: 700; }}
.stMarkdown p, .stMarkdown li {{ font-weight: 500; }}
strong, b {{ font-weight: 750; }}
[data-testid="stSidebar"] {{ background: {T["tint"]}; border-right: 1px solid {T["border"]}; }}
[data-testid="stSidebar"] * {{ color: {T["ink"]}; }}
h1,h2,h3, .stMarkdown {{ color: {T["ink"]}; }}

.hero {{ display:flex; gap:14px; align-items:center; padding: 6px 0 2px; }}
.hero-icon {{ width:46px;height:46px;border-radius:14px;background:{T["accent_soft"]};
  color:{T["accent"]}; display:flex;align-items:center;justify-content:center; }}
.hero-title {{ font-size:1.55rem; font-weight:800; letter-spacing:-0.01em; }}
.hero-sub {{ color:{T["muted"]}; font-size:0.92rem; margin-top:2px; }}
.disclaimer {{ margin:10px 0 4px; padding:8px 14px; border-left:3px solid {T["border"]};
  background:{T["tint"]}; border-radius:0 10px 10px 0; color:{T["muted"]}; font-size:0.82rem; }}

.sec-h {{ display:flex; gap:8px; align-items:center; margin:26px 0 10px;
  font-size:1.12rem; font-weight:800; color:{T["ink"]}; }}
.sec-h svg {{ color:{T["accent"]}; }}

.vb {{ display:inline-flex; align-items:center; gap:5px; padding:2px 10px; border-radius:999px;
  font-size:0.8rem; font-weight:700; white-space:nowrap; line-height:1.7; }}
.vb-lg {{ font-size:0.88rem; padding:4px 13px; }}
.arrow {{ margin:0 6px; color:{T["muted"]}; font-weight:700; }}

.card {{ border:1px solid {T["border"]}; border-radius:14px; padding:14px 18px; margin:8px 0;
  background:{T["bg"]}; box-shadow:0 1px 3px rgba(41,55,84,0.06); }}
.card-top {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
.rank {{ font-weight:800; color:{T["accent"]}; font-size:1.02rem; }}
.nct {{ font-weight:700; letter-spacing:0.01em; }}
.card-title {{ color:{T["muted"]}; font-size:0.88rem; margin:6px 0 8px; }}
.chips {{ display:flex; gap:6px; flex-wrap:wrap; }}
.chip {{ display:inline-flex; align-items:center; gap:4px; padding:1px 9px; border-radius:999px;
  font-size:0.76rem; font-weight:700; }}

table.sheet {{ width:100%; border-collapse:collapse; font-size:0.85rem; margin:4px 0 8px; }}
table.sheet th {{ text-align:left; color:{T["muted"]}; font-weight:700; font-size:0.76rem;
  padding:7px 10px; border-bottom:1px solid {T["border"]}; background:{T["tint"]}; }}
table.sheet td {{ padding:8px 10px; border-bottom:1px solid {T["tint"]}; vertical-align:top; }}
table.sheet td.cid {{ font-weight:700; white-space:nowrap; }}
table.sheet td.kind {{ color:{T["muted"]}; white-space:nowrap; }}
table.sheet td.crit {{ max-width:330px; }}
table.sheet td.verd {{ white-space:nowrap; }}
table.sheet td.ev {{ color:{T["muted"]}; max-width:340px; }}

.why-line {{ display:flex; gap:7px; align-items:baseline; padding:9px 13px; margin:2px 0 10px;
  background:{T["accent_soft"]}; border-radius:10px; font-size:0.86rem; }}
.why-line svg {{ color:{T["accent"]}; flex:none; position:relative; top:1px; }}
.ev-group {{ margin:10px 0 14px; }}
.ev-group-h {{ display:flex; align-items:center; gap:8px; margin-bottom:6px; }}
.ev-count {{ font-weight:700; font-size:0.8rem; color:{T["ink"]}; }}
.ev-why {{ color:{T["muted"]}; font-size:0.8rem; }}
.ev-row {{ border-left:2px solid {T["border"]}; padding:4px 0 6px 12px; margin:0 0 6px 4px; }}
.ev-head {{ display:flex; gap:8px; align-items:baseline; }}
.ev-id {{ font-weight:800; font-size:0.8rem; flex:none; }}
.ev-text {{ font-size:0.85rem; font-weight:600; }}
.ev-quote {{ color:{T["muted"]}; font-size:0.8rem; margin-top:3px; font-style:normal; }}
.ev-quote::before {{ content:"└ 근거 "; color:{T["accent"]}; font-weight:700; }}

.stButton > button[kind="primary"] {{ background:{T["accent"]}; border:none; border-radius:10px; }}
.stButton > button {{ border-radius:10px; border-color:{T["border"]}; }}
[data-testid="stExpander"] details {{ border:1px solid {T["border"]}; border-radius:12px; }}
</style>""", unsafe_allow_html=True)
