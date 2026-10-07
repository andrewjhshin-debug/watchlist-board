# -*- coding: utf-8 -*-
"""
관심종목 차트 보드 + 목표가 알림.

    python watch.py          한 번 갱신 → index.html 생성
    python watch.py --loop   refresh_min 분마다 계속 갱신
    python watch.py --test   자체 점검
    python watch.py --ping   텔레그램 테스트 메시지 1건

시세: 야후 파이낸스, 비트코인은 업비트 원화. 60분/일/주/월 보기.
현재가가 목표가 이하로 내려가면 텔레그램 알림(종목당 하루 1번) + 보드에 '목표 도달' 표시.
"""
from __future__ import annotations

import html
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
STATE = ROOT / "state.json"
UA = {"User-Agent": "Mozilla/5.0"}
KST = timezone(timedelta(hours=9))  # GitHub 서버는 UTC


def get_json(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.load(r)


# 보기: (야후 기간, 야후 간격, 업비트 단위, 업비트 개수, 설명)
VIEWS = {"60": ("1mo", "60m", "minutes/60", 170, "60분봉 1개월"),
         "일": ("6mo", "1d", "days", 130, "일봉 6개월"),
         "주": ("2y", "1wk", "weeks", 104, "주봉 2년"),
         "월": ("10y", "1mo", "months", 120, "월봉 10년")}


def fetch(sym: str, view: str = "일") -> dict:
    """{'closes': [...], 'currency': str} — 오래된 것부터, 마지막 봉 = 현재가."""
    rng, itv, unit, cnt, _ = VIEWS[view]
    if sym.startswith("upbit:"):
        rows = get_json(f"https://api.upbit.com/v1/candles/{unit}?market={sym[6:]}&count={cnt}")[::-1]
        return {"closes": [r["trade_price"] for r in rows], "currency": "KRW"}
    d = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?range={rng}&interval={itv}")
    d = d["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    closes = [c for c in q["close"] if c is not None]
    closes[-1] = d["meta"].get("regularMarketPrice") or closes[-1]
    return {"closes": closes, "currency": d["meta"].get("currency", "USD")}


# ---------------------------------------------------------------- 알림
def send_telegram(text: str) -> None:
    # GitHub 에서는 비밀값(TG_TOKEN, TG_CHAT_ID), PC 에서는 출자공고 알림 설정 파일
    tg = {"bot_token": os.environ.get("TG_TOKEN"), "chat_id": os.environ.get("TG_CHAT_ID"), "enabled": True}
    p = (ROOT / CFG.get("telegram_config", "")).resolve()
    if not tg["bot_token"] and p.is_file():
        tg = json.loads(p.read_text(encoding="utf-8")).get("telegram", {})
    if not (tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id")):
        print("  (텔레그램 설정 없음 — 알림 생략)")
        return
    body = json.dumps({"chat_id": tg["chat_id"], "text": text, "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{tg['bot_token']}/sendMessage", data=body,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).read()


# ---------------------------------------------------------------- 화면
def fmt(v: float, cur: str) -> str:
    return f"{v:,.0f}" if cur == "KRW" else f"{v:,.2f}"


COLS, ROWS, CELL = 75, 32, 4  # 러프함이 핵심: 작은 사각형을 이어붙인 느낌(아이밧 차트)


def chart_svg(d: dict) -> str:
    W, H = COLS * CELL, ROWS * CELL
    closes, tgt = d["closes"], d.get("target")
    n = len(closes)
    cols = [closes[round(c * (n - 1) / (COLS - 1))] for c in range(COLS)]  # 봉을 30칸으로 뭉갬(마지막 칸=현재가)
    vals = cols + ([tgt] if tgt else [])  # 목표가는 멀어도 항상 화면 안에
    vmin, vmax = min(vals), max(vals)
    span = (vmax - vmin) or 1
    y = lambda v: H - CELL / 2 - round((v - vmin) / span * (ROWS - 1)) * CELL  # 칸 단위로 스냅
    pts = " ".join(f"{c * CELL},{y(v)} {(c + 1) * CELL},{y(v)}" for c, v in enumerate(cols))
    grid = "".join(f'<line x1="0" y1="{g}" x2="{W}" y2="{g}"/>' for g in range(0, H, CELL * 2)) + \
           "".join(f'<line x1="{g}" y1="0" x2="{g}" y2="{H}"/>' for g in range(0, W, CELL * 2))
    cur = d["currency"]
    return f'''<span class="ax top">{fmt(vmax, cur)}</span><span class="ax bot">{fmt(vmin, cur)}</span><svg viewBox="0 0 {W} {H}" preserveAspectRatio="none">
<g class="grid">{grid}</g>
<polygon class="area" points="0,{H} {pts} {W},{H}"/>
<polyline class="line" points="{pts}"/>
{f'<line class="tgt" x1="0" y1="{y(tgt)}" x2="{W}" y2="{y(tgt)}"/>' if tgt else ''}
</svg>'''


def tile(d: dict) -> str:
    """d = {'name','target','currency','views': {'일': {...}, '주': ..., '월': ...}}. 시세·알림은 일봉 기준."""
    day = d["views"]["일"]
    cur, price, prev = d["currency"], day["closes"][-1], day["closes"][-2]
    chg = price - prev
    pct = chg / prev * 100
    cls = "up" if chg >= 0 else "down"
    thit = bool(d.get("target")) and price <= d["target"]
    views = ""
    for k, v in d["views"].items():
        v = v | {"target": d.get("target"), "currency": cur}
        views += f'<div class="view" data-v="{k}"><div class="chart">{chart_svg(v)}</div></div>'
    badges = '<span class="badge t">목표 도달</span>' if thit else ''
    tgt = (f'<div class="tgttxt">목표 {fmt(d["target"], cur)} <b>{(price / d["target"] - 1) * 100:+.1f}%</b></div>'
           if d.get("target") else '')
    return (f'<div class="tile {cls}{" hit" if thit else ""}" onclick="this.classList.toggle(\'zoom\')">'
            f'<div class="name">{html.escape(d["name"])}{badges}<span class="x">✕</span></div>'
            f'<div class="price">{fmt(price, cur)}</div>'
            f'<div class="chg">{"▲" if chg >= 0 else "▼"} {fmt(abs(chg), cur)} ({pct:+.2f}%)</div>'
            f'{views}{tgt}</div>')


def render(items: list[dict], errors: list[str]) -> None:
    now = datetime.now(KST).strftime("%Y년 %m월 %d일 %H:%M")
    err = "".join(f'<div class="err">{html.escape(e)}</div>' for e in errors)
    page = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{CFG["refresh_min"] * 60}">
<title>관심종목 보드</title>
<link rel="manifest" href="manifest.json"><link rel="icon" href="icon.png"><link rel="apple-touch-icon" href="icon.png"><meta name="theme-color" content="#0d1424">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/galmuri@latest/dist/galmuri.css">
<style>
:root{{--bg:#0d1424;--tile:#121b30;--edge:#26355a;--grid:#1d2a48;--txt:#e6ecff;--sub:#8a96b8;
--up:#ff4d6d;--upf:#3a1424;--dn:#3d8bff;--dnf:#0f2650;--low:#ffd23f;--tgt:#3ef0b0}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--txt);font-family:'Galmuri11','Malgun Gothic',monospace}}
header{{display:flex;gap:12px;justify-content:space-between;align-items:center;padding:14px 16px;border-bottom:1px solid var(--edge)}}
h1{{margin:0;font-size:22px;white-space:nowrap}}.note{{color:var(--sub);font-size:12px;padding:8px 16px 0}}
.grid-wrap{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px;padding:12px 16px}}
@media(max-width:600px){{.grid-wrap{{grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px;padding:10px}}.price{{font-size:18px!important}}h1{{font-size:18px!important}}.tabs button{{font-size:13px!important;padding:3px 7px!important}}.tile{{padding:8px}}}}
.tile{{background:var(--tile);border:3px solid var(--edge);padding:10px}}
.name{{font-size:15px}}.price{{font-size:22px;margin:4px 0 2px}}.chg{{font-size:12px}}
.up .chg{{color:var(--up)}}.down .chg{{color:var(--dn)}}
.chart{{position:relative;margin-top:8px;border:3px solid var(--edge);background:#0a1020;aspect-ratio:30/13}}
.ax{{position:absolute;left:3px;font-size:9px;color:var(--sub);pointer-events:none}}.ax.top{{top:2px}}.ax.bot{{bottom:2px}}
.view{{display:none}}body[data-v="60"] .view[data-v="60"],body[data-v="일"] .view[data-v="일"],body[data-v="주"] .view[data-v="주"],body[data-v="월"] .view[data-v="월"]{{display:block}}
.tabs{{display:flex;gap:6px}}.tabs button{{font:inherit;font-size:15px;color:var(--txt);background:var(--tile);border:3px solid var(--edge);padding:4px 10px;cursor:pointer}}
body[data-v="60"] .tabs [data-v="60"],body[data-v="일"] .tabs [data-v="일"],body[data-v="주"] .tabs [data-v="주"],body[data-v="월"] .tabs [data-v="월"]{{color:var(--low);border-color:var(--low)}}
.tile{{cursor:zoom-in}}.x{{display:none;float:right;color:var(--sub)}}
.tile.zoom{{position:fixed;inset:0;z-index:9;overflow:auto;cursor:zoom-out;padding:16px}}.tile.zoom .x{{display:inline}}
.tile.zoom .chart{{aspect-ratio:auto;height:62vh}}.tile.zoom .name{{font-size:20px}}.tile.zoom .price{{font-size:30px}}
.tile.zoom .tgttxt{{font-size:14px}}.tile.zoom .ax{{font-size:12px}}
svg{{width:100%;height:100%;display:block}}
.grid line{{stroke:var(--grid);stroke-width:1}}
.line{{fill:none;stroke-width:4;shape-rendering:crispEdges;vector-effect:non-scaling-stroke}}
.up .line{{stroke:var(--up)}}.down .line{{stroke:var(--dn)}}.up .area{{fill:var(--upf)}}.down .area{{fill:var(--dnf)}}
.tgt{{stroke:var(--tgt);stroke-width:1.5;stroke-dasharray:2 3;vector-effect:non-scaling-stroke}}
.tgttxt{{margin-top:6px;font-size:11px;color:var(--tgt)}}.tgttxt b{{font-weight:normal;color:var(--sub)}}
.badge.t{{background:var(--tgt)}}
.badge{{margin-left:6px;font-size:10px;background:var(--low);color:#000;padding:1px 4px}}
.hit{{animation:blink 1s steps(2) infinite}}@keyframes blink{{50%{{border-color:var(--tgt)}}}}
.err{{color:var(--up);font-size:12px;padding:0 16px}}
</style></head><body>
<header><h1>📈 관심종목</h1><div class="tabs">{"".join(f'<button data-v="{k}">{k}</button>' for k in VIEWS)}</div></header>
<div class="note">{now} 기준 · <span id="vdesc"></span> · <i style="color:var(--tgt)">┈ 목표가</i> · 카드를 누르면 크게</div>
{err}<div class="grid-wrap">{"".join(tile(d) for d in items)}</div>
<script>
const D={json.dumps({k: v[4] for k, v in VIEWS.items()}, ensure_ascii=False)};
function setV(v){{document.body.dataset.v=v;document.getElementById('vdesc').textContent=D[v];try{{localStorage.v=v}}catch(e){{}}}}
let saved;try{{saved=localStorage.v}}catch(e){{}}
setV(D[saved]?saved:'일');
document.querySelectorAll('.tabs button').forEach(b=>b.onclick=()=>setV(b.dataset.v));
if('serviceWorker' in navigator)navigator.serviceWorker.register('sw.js');
</script></body></html>'''
    (ROOT / "index.html").write_text(page, encoding="utf-8")


# ---------------------------------------------------------------- 실행
def run_once() -> None:
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    today = datetime.now(KST).strftime("%Y-%m-%d")
    items, errors, alerts = [], [], []
    for s in CFG["symbols"]:
        try:
            views = {}
            for k in VIEWS:
                try:
                    v = fetch(s["sym"], k)
                except Exception:
                    if k == "일":
                        raise
                    continue  # 주·월 실패는 그 보기만 생략
                if len(v["closes"]) >= 3:
                    views[k] = v
            cur = views["일"]["currency"]
            items.append({"name": s["name"], "target": s.get("target"), "currency": cur, "views": views})
            price = views["일"]["closes"][-1]
            tgt = s.get("target")
            if tgt and price <= tgt and state.get(s["sym"] + ":목표") != today:
                alerts.append(f"🎯 <b>{html.escape(s['name'])}</b> 목표가 도달\n"
                              f"현재 {fmt(price, cur)} / 목표 {fmt(tgt, cur)}")
                state[s["sym"] + ":목표"] = today
        except Exception as e:  # 한 종목 실패가 전체를 막지 않게
            errors.append(f"{s['name']} 불러오기 실패: {e}")
    render(items, errors)
    if alerts:
        try:
            send_telegram("\n\n".join(alerts))
        except Exception as e:
            print("  텔레그램 실패:", e)
        STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"{datetime.now(KST):%H:%M} 갱신 {len(items)}종목, 알림 {len(alerts)}건" + (f", 오류 {len(errors)}" if errors else ""))


def self_test() -> None:
    d = {"closes": [10, 9, 12, 11], "currency": "USD"}
    t = tile({"name": "T", "target": 5, "currency": "USD", "views": {"일": d, "주": d}})
    assert t.count('class="view"') == 2 and "목표 5.00" in t and "목표 도달" not in t
    assert "목표 도달" in tile({"name": "T", "target": 12, "currency": "USD", "views": {"일": d}})
    assert "<svg" in chart_svg(d) and "class=\"tgt\"" not in chart_svg(d)
    assert "class=\"tgt\"" in chart_svg(d | {"target": 1})   # 멀리 있는 목표가도 항상 표시
    print("OK")


if __name__ == "__main__":
    if "--ping" in sys.argv:
        send_telegram("✅ 관심종목 보드 알림 연결 테스트")
    elif "--test" in sys.argv:
        self_test()
    elif "--loop" in sys.argv:
        while True:
            run_once()
            time.sleep(CFG["refresh_min"] * 60)
    else:
        run_once()
