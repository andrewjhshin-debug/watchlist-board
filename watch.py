# -*- coding: utf-8 -*-
"""
관심종목 차트 보드. 목표가는 보드에서 직접 입력(그 폰에 저장).

    python watch.py          한 번 갱신 → index.html 생성
    python watch.py --loop   refresh_min 분마다 계속 갱신
    python watch.py --test   자체 점검
    python watch.py --live   실시간 시세만 livedir/m/ 에

시세: 야후 파이낸스, 비트코인은 업비트 원화. 60분/일/주/월 보기.
목표에 가까워질수록 이름·막대가 빨강→주황→연두→초록, 목표 아래면 진한 초록.
"""
from __future__ import annotations

import hashlib
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
UA = {"User-Agent": "Mozilla/5.0"}
KST = timezone(timedelta(hours=9))  # GitHub 서버는 UTC
# 코드 버전: 화면과 실시간 파일에 같이 넣어, 폰에 남은 옛 화면이 다르면 스스로 새로 받게 함
BUILD = hashlib.sha1((ROOT / "watch.py").read_bytes()).hexdigest()[:10]


def get_json(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.load(r)


# 보기: (야후 기간, 야후 간격, 업비트 단위, 업비트 개수, 설명)
VIEWS = {"240": ("1mo", "60m", "minutes/240", 126, "240분봉 3주"),  # 야후엔 4시간봉이 없어 60분봉 4개씩 묶음
         "일": ("6mo", "1d", "days", 130, "일봉 6개월"),
         "주": ("2y", "1wk", "weeks", 104, "주봉 2년"),
         "월": ("10y", "1mo", "months", 120, "월봉 10년")}


def fetch_ecos(code: str) -> dict:
    """한국은행 ECOS 월간 지표 10년치. code = '통계표/항목'. 월 1회 발표라 하루 한 번만 받는다."""
    cache = ROOT / "ecos.json"
    today = datetime.now(KST).strftime("%Y-%m-%d")
    saved = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    if saved.get(code, {}).get("date") != today:
        table, item = code.split("/")
        ym = datetime.now(KST).year * 12 + datetime.now(KST).month - 1  # 이번 달
        vals = []
        # ponytail: 공개 sample 키는 한 번에 10행까지라 10개월씩 12번 요청. 본인 ECOS 키 받으면 1번으로 줄일 수 있음
        for end in range(ym - 110, ym + 1, 10):
            a, b = end - 9, end
            url = (f"https://ecos.bok.or.kr/api/StatisticSearch/sample/json/kr/1/10/{table}/M/"
                   f"{a // 12}{a % 12 + 1:02d}/{b // 12}{b % 12 + 1:02d}/{item}")
            rows = get_json(url).get("StatisticSearch", {}).get("row", [])
            vals += [(r["TIME"], float(r["DATA_VALUE"])) for r in rows]
        saved[code] = {"date": today, "vals": sorted(set(vals))}
        cache.write_text(json.dumps(saved), encoding="utf-8")
    vals = saved[code]["vals"]
    return {"closes": [v for _, v in vals], "dates": [f"{t[:4]}-{t[4:]}-01" for t, _ in vals], "currency": "pt", "last": vals[-1][0]}


def fetch(sym: str, view: str = "일") -> dict:
    """{'closes': [...], 'dates': ['YYYY-MM-DD', ...], 'currency': str} — 오래된 것부터, 마지막 봉 = 현재가."""
    rng, itv, unit, cnt, _ = VIEWS[view]
    if sym.startswith("ecos:"):
        return fetch_ecos(sym[5:])  # 월간 지표라 모든 보기에서 같은 10년 차트
    if sym.startswith("upbit:"):
        rows = get_json(f"https://api.upbit.com/v1/candles/{unit}?market={sym[6:]}&count={cnt}")[::-1]
        return {"closes": [r["trade_price"] for r in rows], "highs": [r["high_price"] for r in rows],
                "opens": [r["opening_price"] for r in rows], "lows": [r["low_price"] for r in rows], "dates": [r["candle_date_time_kst"][:10] for r in rows], "currency": "KRW"}
    if view == "240" and not sym.startswith("^") and "=" not in sym:  # 미국 개별 종목은 한투 240분봉 우선
        try:
            kb = kis_240(sym)
            if kb:
                return kb
        except Exception as e:
            print("  한투 240분봉 실패:", sym, type(e).__name__)
    pp = "&includePrePost=true" if view == "240" else ""  # 240분봉은 시간외까지(증권 앱처럼)
    d = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?range={rng}&interval={itv}{pp}")
    d = d["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    bars = [(t, c, h or c, o or c, lo or c) for t, c, h, o, lo
            in zip(d["timestamp"], q["close"], q["high"], q["open"], q["low"]) if c is not None]
    if view == "240":
        # 증권 앱처럼 '장 시작'부터 4시간씩 자른다(코스피 09~13·13~15:30, 나스닥 09:30~13:30…).
        # 1시간 넘게 봉이 비면 새 장(세션)으로 본다(선물은 매일 1시간 쉬는 시간 뒤 새 장)
        four, start, prev = {}, None, None
        for t, c, h, o, lo in bars:  # 구간별: 첫 시가, 마지막 종가, 최고·최저
            if prev is None or t - prev > 3600:
                start = t
            prev = t
            k = (start, (t - start) // 14400)
            f = four.get(k)
            four[k] = (t, c, max(h, f[2]), f[3], min(lo, f[4])) if f else (t, c, h, o, lo)
        since = time.time() - 21 * 86400  # 최근 3주
        bars = [b for b in four.values() if b[0] >= since]
    closes = [b[1] for b in bars]
    if view != "240":
        closes[-1] = d["meta"].get("regularMarketPrice") or closes[-1]
    dates = [datetime.fromtimestamp(b[0], KST).strftime("%Y-%m-%d") for b in bars]
    return {"closes": closes, "highs": [b[2] for b in bars], "opens": [b[3] for b in bars], "lows": [b[4] for b in bars], "dates": dates, "currency": "pt" if sym.startswith("^") else d["meta"].get("currency", "USD")}


# ---------------------------------------------------------------- 한투 주간거래(한국 낮 시간)
# 야후에는 주간거래(블루오션) 시세가 없어 한국투자증권 Open API 로 받는다. 키는 GitHub 비밀값.
# 토큰은 발급할 때마다 한투가 알림톡을 보내므로, 실행 중에는 파일(.kis.json)에 두고 재사용한다.
# 이 파일은 커밋·캐시·화면 어디에도 안 올라간다(토큰으로 주문도 가능해서 밖에 두면 안 됨).
KIS = "https://openapi.koreainvestment.com:9443"
KIS_FILE = ROOT / ".kis.json"


def kis_state() -> dict:
    return json.loads(KIS_FILE.read_text(encoding="utf-8")) if KIS_FILE.exists() else {}


def kis_headers(tr_id: str) -> dict | None:
    key, secret = os.environ.get("KIS_APP_KEY"), os.environ.get("KIS_APP_SECRET")
    if not (key and secret):
        return None
    st = kis_state()
    if st.get("exp", "") <= datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"):
        body = json.dumps({"grant_type": "client_credentials", "appkey": key, "appsecret": secret}).encode()
        req = urllib.request.Request(KIS + "/oauth2/tokenP", data=body, headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.load(r)
        st.update(tok=j["access_token"], exp=j["access_token_token_expired"])  # 'YYYY-MM-DD HH:MM:SS' (KST)
        KIS_FILE.write_text(json.dumps(st), encoding="utf-8")
    return {"authorization": f"Bearer {st['tok']}", "appkey": key, "appsecret": secret,
            "tr_id": tr_id, "custtype": "P", "content-type": "application/json; charset=utf-8"}


def day_quote(sym: str) -> tuple[float, float] | None:
    """주간거래 (현재가, 전일 종가). 거래소 코드는 나스닥/뉴욕/아멕스 주간(BAQ/BAY/BAA) 중 값이 나오는 것."""
    h = kis_headers("HHDFS00000300")
    if not h:
        return None
    st = kis_state()
    for ex in [st.get("ex", {}).get(sym)] if st.get("ex", {}).get(sym) else ["BAQ", "BAY", "BAA"]:
        url = f"{KIS}/uapi/overseas-price/v1/quotations/price?AUTH=&EXCD={ex}&SYMB={urllib.request.quote(sym)}"
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
            out = json.load(r).get("output") or {}
        last = float(out.get("last") or 0)
        if last > 0:
            st = kis_state()
            st.setdefault("ex", {})[sym] = ex
            KIS_FILE.write_text(json.dumps(st), encoding="utf-8")
            return last, float(out.get("base") or 0)
    return None


KR_INDEX = {"^KS11": "0001", "^KQ11": "1001"}  # 한투 업종 코드: 코스피, 코스닥


def kr_index_quote(sym: str) -> tuple[float, float] | None:
    """코스피·코스닥 실시간 지수(한투). 야후는 20분 늦어서 장중엔 이걸 쓴다."""
    h = kis_headers("FHPUP02100000")
    if not h:
        return None
    url = (f"{KIS}/uapi/domestic-stock/v1/quotations/inquire-index-price"
           f"?FID_COND_MRKT_DIV_CODE=U&FID_INPUT_ISCD={KR_INDEX[sym]}")
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
        o = json.load(r).get("output") or {}
    now, chg = float(o.get("bstp_nmix_prpr") or 0), float(o.get("bstp_nmix_prdy_vrss") or 0)
    return (now, now - chg) if now > 0 else None


DAY_TO_REG = {"BAQ": "NAS", "BAY": "NYS", "BAA": "AMS"}  # 주간거래 거래소 → 정규장 거래소


def kis_240(sym: str) -> dict | None:
    """한투 240분봉(정규·시간외 + 주간거래) 최근 3주. 증권 앱과 같은 기준으로 4시간을 잘라 봉 색이 같다."""
    h = kis_headers("HHDFS76950200")
    if not h:
        return None
    ex = kis_state().get("ex", {}).get(sym)
    pairs = [(DAY_TO_REG[ex], ex)] if ex else [("NAS", "BAQ"), ("NYS", "BAY"), ("AMS", "BAA")]
    rows = []
    for reg, day in pairs:
        for code in (reg, day):
            url = (f"{KIS}/uapi/overseas-price/v1/quotations/inquire-time-itemchartprice"
                   f"?AUTH=&EXCD={code}&SYMB={urllib.request.quote(sym)}&NMIN=240&PINC=1&NEXT=&NREC=120&FILL=&KEYB=")
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=20) as r:
                rows += json.load(r).get("output2") or []
        if rows:
            break
    since = (datetime.now(KST) - timedelta(days=21)).strftime("%Y%m%d")
    bars = sorted({x["kymd"] + x["khms"]: x for x in rows if x.get("kymd", "") >= since and float(x.get("last") or 0) > 0}.items())
    if len(bars) < 3:
        return None
    f = lambda key: [float(x[key]) for _, x in bars]
    return {"closes": f("last"), "highs": f("high"), "opens": f("open"), "lows": f("low"),
            "dates": [f"{k[:4]}-{k[4:6]}-{k[6:8]}" for k, _ in bars], "currency": "USD"}


def day_market_now() -> bool:
    """한국 평일 주간거래 시간. 미국 서머타임이면 09~17시, 아니면 10~18시(11월 첫 일요일~3월)."""
    n = datetime.now(KST)
    try:
        from zoneinfo import ZoneInfo
        dst = bool(datetime.now(ZoneInfo("America/New_York")).dst())
    except Exception:  # 시간대 정보가 없는 PC 등: 3~10월을 서머타임으로
        dst = 3 <= n.month <= 10
    start = 9 if dst else 10
    return n.weekday() < 5 and start <= n.hour < start + 8


def quote(sym: str) -> tuple[float, float]:
    """(현재가, 전일 종가). 미국 종목은 시간외 거래까지 포함한 마지막 1분 가격, 한국 낮에는 한투 주간거래 가격."""
    if sym.startswith("upbit:"):
        r = get_json(f"https://api.upbit.com/v1/ticker?markets={sym[6:]}")[0]
        return r["trade_price"], r["prev_closing_price"]
    n = datetime.now(KST)
    if sym in KR_INDEX and n.weekday() < 5 and 9 <= n.hour < 16:  # 한국 장중
        try:
            kq = kr_index_quote(sym)
            if kq:
                return kq
        except Exception as e:
            print("  한투 지수 실패:", sym, type(e).__name__)
    d = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}"
                 "?range=1d&interval=1m&includePrePost=true")["chart"]["result"][0]
    closes = [c for c in d["indicators"]["quote"][0].get("close") or [] if c is not None]  # 선물은 빈 응답이 가끔 옴
    m = d["meta"]
    if day_market_now() and not sym.startswith("^") and "=" not in sym:  # 지수·선물 제외  # 지수(나스닥 종합)는 주간거래 없음
        try:
            dq = day_quote(sym)
            reg = m["regularMarketPrice"]  # 낮에는 = 직전 정규장 종가
            # 주간거래 값은 새 체결 전까지 지난 회차 값이 남는다(예: 금 낮 105.48 vs 그날 밤 종가 93.67).
            # 한투의 기준가(base)가 직전 정규장 종가와 같을 때만 '이번 회차' 값으로 보고 쓴다
            if dq and dq[1] and abs(dq[1] / reg - 1) < 0.005:
                return dq[0], dq[1]
        except Exception as e:
            print("  한투 주간거래 실패:", sym, type(e).__name__)  # 키·토큰이 로그에 찍히지 않게 종류만
    return (closes[-1] if closes else m["regularMarketPrice"]), m.get("chartPreviousClose") or m["previousClose"]


def peak(sym: str, day: dict) -> tuple[float, str, dict]:
    """gauge_since 이후 최고점(값, 날짜). 미국 종목은 프리·애프터장 포함(60분봉).
    시간외 봉은 거래량 0 인 잘못 찍힌 꼬리(예: AXTX 9/22 150.56)가 있어 시가·종가만 본다."""
    since = CFG.get("gauge_since", "")
    if sym.startswith(("upbit:", "ecos:")):
        rows = list(zip(day.get("highs", day["closes"]), day["dates"]))
    else:
        d = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}"
                     "?range=6mo&interval=60m&includePrePost=true")["chart"]["result"][0]
        q = d["indicators"]["quote"][0]
        rows = [(h if v else max(o, c), datetime.fromtimestamp(t, KST).strftime("%Y-%m-%d"))
                for t, o, h, c, v in zip(d["timestamp"], q["open"], q["high"], q["close"], q["volume"])
                if None not in (o, h, c)]
    days = {}
    for v, dt in rows:
        days[dt] = max(v, days.get(dt, v))
    v, dt = max([r for r in rows if r[1] >= since] or rows)
    return v, dt, days


def run_live() -> None:
    """1분 남짓마다: 시세만 받아 파일로 쓴다(보드가 가져가 숫자·막대 갱신)."""
    q = {}
    for s in CFG["symbols"]:
        if s["sym"].startswith("ecos:"):
            continue  # 월간 지표는 실시간 없음
        try:
            price, prev = quote(s["sym"])
            q[s["sym"]] = [price, prev]
        except Exception as e:
            print("  실시간 실패:", s["name"], e)
    # 분마다 새 파일(livedir/m/YYYYMMDDHHMM.json). 같은 주소를 덮어쓰면 GitHub raw 가 5분 캐시해서,
    # 새 이름으로 올리고 보드는 '1분 전 파일'을 받는다. 최근 10개만 남김
    now = datetime.now(KST)
    out = ROOT / "livedir" / "m"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{now:%Y%m%d%H%M}.json").write_text(json.dumps({"t": f"{now:%H:%M:%S}", "b": BUILD, "q": q}), encoding="utf-8")
    for old in sorted(out.glob("*.json"))[:-10]:
        old.unlink()


# ---------------------------------------------------------------- 화면
def fmt(v: float, cur: str) -> str:
    return f"{v:,.0f}" if cur == "KRW" else f"{v:,.2f}"


def fmt_short(v: float, cur: str) -> str:
    """목표가 줄은 한 줄에 들어가게: 원화 큰 금액은 '9,000만'."""
    return f"{v / 1e4:,.0f}만" if cur == "KRW" and v >= 1e6 else fmt(v, cur)


COLS, ROWS, CELL = 75, 32, 4  # 러프함이 핵심: 작은 사각형을 이어붙인 느낌(아이밧 차트)


def targets(t) -> list[float]:
    return t if isinstance(t, list) else [t] if t else []


MAX_CANDLES = 70  # 봉이 많으면 몇 개씩 묶어서 이 수 이하로


def chart_svg(d: dict) -> str:
    W, H = COLS * CELL, ROWS * CELL
    closes, tgts = d["closes"], targets(d.get("target"))
    n = len(closes)
    opens = d.get("opens") or [closes[0]] + closes[:-1]  # 월간 지표처럼 시가가 없으면 직전 값
    highs = d.get("highs") or [max(o, c) for o, c in zip(opens, closes)]
    lows = d.get("lows") or [min(o, c) for o, c in zip(opens, closes)]
    k = -(-n // MAX_CANDLES)  # 묶음 크기
    cs = [(opens[i], max(highs[i:i + k]), min(lows[i:i + k]), closes[min(i + k, n) - 1]) for i in range(0, n, k)]
    m = len(cs)
    vmin, vmax = min([c[2] for c in cs] + tgts), max(c[1] for c in cs)
    span = (vmax - vmin) or 1
    y = lambda v: H - CELL / 2 - round((v - vmin) / span * (ROWS - 1)) * CELL  # 칸 단위로 스냅
    cw = W / m
    body = ""
    for j, (o, hi, lo, c) in enumerate(cs):
        x, cls = j * cw, "cu" if c >= o else "cd"
        top, bot = min(y(o), y(c)), max(y(o), y(c))
        body += (f'<line class="{cls}" x1="{x + cw / 2:.1f}" y1="{y(hi)}" x2="{x + cw / 2:.1f}" y2="{y(lo)}"/>'
                 f'<rect class="{cls}" x="{x + cw * .15:.1f}" y="{top - CELL / 2}" width="{cw * .7:.1f}" height="{bot - top + CELL}"/>')
    grid = "".join(f'<line x1="0" y1="{g}" x2="{W}" y2="{g}"/>' for g in range(0, H, CELL)) + \
           "".join(f'<line x1="{g}" y1="0" x2="{g}" y2="{H}"/>' for g in range(0, W, CELL))
    cur = d["currency"]
    # 전고(막대 100% 기준) 자리에 숫자만. 펼쳤을 때만 보임. 이 보기 기간 밖이면 생략
    peak, dates = "", d.get("dates", [])
    if d.get("peak") and dates and dates[0] <= d["peak"][1]:
        pv, pd = d["peak"][:2]
        i = max(j for j, dt in enumerate(dates) if dt <= pd)
        px = (i // k + .5) / m * 100
        py = max(CELL / 2, y(pv)) / H * 100
        peak = f'<span class="peak{" r" if px > 80 else ""}" style="left:{px:.1f}%;top:{py:.1f}%">{fmt(pv, cur)}</span>'
    return f'''{peak}<span class="ax top">{fmt(vmax, cur)}</span><span class="ax bot">{fmt(vmin, cur)}</span><svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" data-vmin="{vmin}" data-vmax="{vmax}">
<g class="grid">{grid}</g>
{body}
{"".join(f'<line class="tgt" x1="0" y1="{y(t)}" x2="{W}" y2="{y(t)}"/>' for t in tgts)}
</svg>'''


def zoom_tools(views) -> str:
    buttons = "".join(f'<button type="button" data-v="{k}"{chr(32) + "disabled" if k not in views else ""} onclick="event.stopPropagation();setV(this.dataset.v)">{k}</button>' for k in VIEWS)
    return ('<div class="zoom-tools" onclick="event.stopPropagation()"><div class="tabs" role="group" aria-label="차트 주기">' + buttons +
            '</div></div>')


def tile(d: dict) -> str:
    """d = {'name','target','currency','views': {'일': {...}, '주': ..., '월': ...}}. 시세·알림은 일봉 기준."""
    day = d["views"]["일"]
    cur = d["currency"]
    price, prev = d.get("now") or (day["closes"][-1], day["closes"][-2])  # 실시간과 같은 값이라 새로고침해도 안 튐
    chg = price - prev
    pct = chg / prev * 100
    cls = "up" if chg >= 0 else "down"
    tgts = targets(d.get("target"))
    views = ""
    for k, v in d["views"].items():
        v = v | {"target": d.get("target"), "currency": cur, "peak": d.get("peak")}
        views += f'<div class="view" data-v="{k}"><div class="chart">{chart_svg(v)}</div></div>'
    tgt = "".join(f'<div class="tgttxt" data-t="{t}">목표 {fmt_short(t, cur)} <b>{(price / t - 1) * 100:+.1f}%</b></div>' for t in tgts)
    # 거리 막대: 종목마다 자기 기준. gauge_since(2026-07-31) 이후 장중 최고가 = 100%, 목표가 = 0%.
    # 다가올수록 줄어듦. 이름과 막대는 같은 4단계 색: 75%↑ 빨강, 50%↑ 주황, 25%↑ 노랑, 그 아래 흰색(임박)
    hi = d["peak"][0] if d.get("peak") else max(day["closes"])
    lv, left = "", 0.0
    bar_attr = ' data-bar-only="1"' if d.get("bar_only") else ""
    pdays = html.escape(json.dumps(d["peak"][2])) if d.get("peak") and len(d["peak"]) > 2 else ""
    live_attr = f' data-pd="{pdays}" data-hi="{hi}" data-tgts0="{json.dumps(tgts)}" data-tgts="{json.dumps(tgts)}" data-p="{price}" data-pv="{prev}"'
    if tgts:
        t = max(tgts)  # 여러 목표면 가장 가까운(높은) 목표
        left = max(0.0, min(1.0, (price - t) / (hi - t))) if hi > t else 0.0
        if price < t:  # 목표 아래: 0에서 다시 초록으로 차오름, 목표보다 30% 아래면 꽉 참·가장 진한 초록
            depth = min(1.0, (t - price) / t / 0.30)
            lv, left = f' below" style="--gp:{75 + 25 * depth:.0f}%', depth
        else:
            lv = f" lv{4 if left >= .75 else 3 if left >= .5 else 2 if left >= .25 else 1}"
    # 월간 지표: 몇 월분인지 + 언제 발표됐는지(통계청 산업활동동향은 다음 달 말에 나온다)
    if d.get("last"):
        m = int(d["last"][4:])
        when = f' <small>{m}월분·{m % 12 + 1}월말 발표</small>'  # 통계청은 다음 달 말 발표
    else:
        when = ""
    zoomtools = zoom_tools(d["views"])
    return (f'<div class="tile {cls}{" wide" if d.get("wide") else ""}{lv}" data-sym="{d.get('sym', '')}" data-cur="{cur}"{bar_attr}{live_attr} onclick="tap(this)">'
            f'<div class="name">{html.escape(d["name"])}{when}<span class="x">✕</span></div>'
            f'<div class="price">{fmt(price, cur)}</div>'
            f'<div class="chg">{"▲" if chg >= 0 else "▼"} {fmt(abs(chg), cur)} ({pct:+.2f}%)</div>'
            f'{zoomtools}{views}<div class="gauge"{"" if tgts else " hidden"}><i style="width:{left * 100:.0f}%"></i></div>'
            f'<div class="tgts" onclick="editT(event,this)">{tgt or '<div class="tgttxt">목표 설정 ✎</div>'}</div></div>')


# 하(하이먼 민스키 모델): 버블 단계 곡선 위에 종목 주봉 종가를 늘리고 줄여 겹친다. (x 0~1, y 0~1)
MINSKY = [(0, .03), (.20, .07), (.35, .13), (.42, .18), (.47, .20), (.52, .15), (.56, .18), (.60, .23), (.63, .21),
          (.66, .26), (.68, .33), (.70, .45), (.715, .62), (.728, .85), (.735, 1.0), (.745, .88), (.76, .70), (.785, .82),
          (.80, .78), (.83, .55), (.86, .25), (.885, .06), (.90, 0), (.93, .03), (.96, .12), (1, .20)]
STAGES = [(.40, "자산 가격 이륙"), (.52, "1차 현금화"), (.66, "1차 하락"), (.69, "열정"), (.705, "탐욕"), (.725, "환상"),
          (.75, "새로운 논리 탄생"), (.775, "2차 하락"), (.81, "현실 부정"), (.85, "공포"), (.885, "투매"), (.95, "좌절"), (9, "정상화")]
HA = [("^KS11", "코스피"), ("000660.KS", "하닉"), ("005930.KS", "삼전"), ("SOXL", "SOXL"), ("MU", "마이크론"),
      ("AXTI", "AXTI"), ("AXTX", "AXTX"), ("^SOX", "필라델피아")]


def mk(x: float) -> float:
    for (x0, y0), (x1, y1) in zip(MINSKY, MINSKY[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return MINSKY[-1][1]


MKT = []


def mkf(x: float) -> float:
    if not MKT:
        MKT.extend(mk(i / 2000) for i in range(2001))
    return MKT[round(x * 2000)]


def minsky_fit(c: list[float], young: bool | None = None) -> tuple[float, int, float, float]:
    """종가 끝부분 n주가 곡선 ts~te 구간과 가장 닮은 (상관계수, n, ts, te).
    1년 안 된 신규상장은 꼭대기에서 시작하니 시작점(ts)도 찾는다."""
    def corr(a, b):
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        sab = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        sa = sum((x - ma) ** 2 for x in a) ** .5
        sb = sum((y - mb) ** 2 for y in b) ** .5
        return sab / (sa * sb) if sa and sb else -1
    if young if young is not None else len(c) < 52:
        best = (-1.0, len(c), 0.0, 1.0)
        for a in range(0, 90):
            for b in range(a + 5, 101):
                ts, te = a / 100, b / 100
                r = corr(c, [mkf(ts + i / (len(c) - 1) * (te - ts)) for i in range(len(c))])
                if r > best[0]:
                    best = (r, len(c), ts, te)
        return best
    best = (-1.0, len(c), 0.0, 1.0)
    for n in range(26, len(c) + 1, 4):
        seg = c[-n:]
        for k in range(66, 101, 1):  # 다들 급등을 거쳤으니 열정 이후 구간에서만 찾음
            te = k / 100
            r = corr(seg, [mkf(i / (n - 1) * te) for i in range(n)])
            if r > best[0]:
                best = (r, n, 0.0, te)
    return best


def minsky_html() -> str:
    W, H, P = 200, 110, 6
    Y = lambda y: H - P - y * (H - 2 * P)

    def frame(x0):  # x0 부터 1 까지 확대한 곡선 (신규상장은 꼭대기 구간만)
        X = lambda x: P + (x - x0) / (1 - x0) * (W - 2 * P)
        curve = "M" + " L".join(f"{X(x0 + i / 200 * (1 - x0)):.1f},{Y(mk(x0 + i / 200 * (1 - x0))):.1f}" for i in range(201))
        return X, (f'<path d="{curve}" class="mk-c"/><line x1="{X(x0)}" y1="{Y(.05 + .17 * x0)}" x2="{X(1)}" y2="{Y(.22)}" class="mk-m"/>')
    X, base = frame(0)
    cells, now_stages = [], set()
    young = {}
    for (hv, iv, rg, per), (sym, name) in ((v, h) for v in (("주", "1wk", "5y", 7 / 30.4), ("일", "1d", "1y", 1 / 21), ("월", "1mo", "10y", 1)) for h in HA):
        try:
            q = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?interval={iv}&range={rg}")["chart"]["result"][0]
            c = [v for v in q["indicators"]["quote"][0]["close"] if v]
            if hv == "주":
                young[sym] = len(c) < 52
            if len(c) < 12:
                continue
            r, n, ts, te = minsky_fit(c, True if hv == "일" else young.get(sym))  # 일봉 1년은 버블 중간부터라 시작점도 찾음
            seg = c[-n:]
            Xc, bc = frame(min(ts, .66)) if ts else (X, base)
            lo_t = min(mk(ts + i / 100 * (te - ts)) for i in range(101))
            hi_t = max(mk(ts + i / 100 * (te - ts)) for i in range(101))
            lo, hi = min(seg), max(seg)
            f = lambda v: lo_t + (v - lo) / ((hi - lo) or 1) * (hi_t - lo_t)
            line = "M" + " L".join(f"{Xc(ts + i / (n - 1) * (te - ts)):.1f},{Y(f(v)):.1f}" for i, v in enumerate(seg))
            stage = next(t for x, t in STAGES if te < x)
            if hv == "주":
                now_stages.add(stage)
            cells.append(f'<div class="mk" data-k="{html.escape(name)}" data-hv="{hv}"><b>{html.escape(name)} <i>일치 {r * 100:.0f}%</i> <u>{stage}</u></b><small class="mk-w">{hv}봉 · {max(1, round(n * per))}개월</small>'
                         f'<svg viewBox="0 0 {W} {H}">{bc}<path d="{line}" class="mk-p"/>'
                         f'<circle cx="{Xc(te):.1f}" cy="{Y(f(seg[-1])):.1f}" r="5" class="mk-d"/></svg></div>')
        except Exception as e:
            print(f"하 {hv} {sym} 실패: {e}")
    labels = "".join(f'<text x="{X(x) + dx:.1f}" y="{Y(mk(x)) + dy:.1f}">{t}</text>' for x, t, dx, dy in
                     [(.47, "1차 현금화", 0, -7), (.70, "열정", -16, 0), (.735, "새 논리", 0, -6), (.79, "현실 부정", 16, -6),
                      (.84, "공포", 14, 2), (.90, "좌절", 0, 14)])
    # 지금 종목들이 있는 단계는 주황으로
    short = {"자산 가격 이륙": "이륙", "새로운 논리 탄생": "새 논리"}
    seq = "→".join(f'<u>{short.get(t, t)}</u>' if t in now_stages else short.get(t, t) for _, t in STAGES)
    cells.insert(0, f'<div class="mk"><b>하이먼 민스키 모델</b><small class="mk-s">{seq}</small><svg viewBox="0 0 {W} {H}">{base}<g class="mk-t">{labels}</g></svg></div>')
    return f'<div id="hapop" class="hapop" hidden><div class="mk-bar" onclick="event.stopPropagation()">{"".join(f'<button data-hv="{v}">{v}</button>' for v in "일주월")}<button class="mk-rl" aria-label="새로고침">⟳</button></div>{"".join(cells)}</div>' if len(cells) > 1 else ""


def render(items: list[dict], errors: list[str], ha: str = "") -> None:
    now = datetime.now(KST).strftime("%m/%d %H:%M")
    # PC 배치는 config 의 pc_order(4칸, 왼→오, 위→아래). 휴대폰은 symbols 순서 그대로
    chart_items = [d for d in items if not d.get("bar_only")]
    pc = CFG.get("pc_order", [])
    pc_order = "".join(f'.tile[data-sym="{d["sym"]}"]{{order:{pc.index(d["sym"]) if d["sym"] in pc else 99}}}' for d in chart_items)
    avg_catalog = json.dumps([{k: s[k] for k in ("sym", "name")} for s in CFG["symbols"]], ensure_ascii=False)
    err = "".join(f'<div class="err">{html.escape(e)}</div>' for e in errors)
    page = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="build" content="{BUILD}">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>관심종목 보드</title>
<link rel="manifest" href="manifest.json"><link rel="icon" href="icon.png"><link rel="apple-touch-icon" href="icon.png"><meta name="theme-color" content="#0d1424">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/galmuri@latest/dist/galmuri.css">
<style>
:root{{--bg:#0d1424;--tile:#121b30;--edge:#26355a;--grid:#1d2a48;--txt:#e6ecff;--sub:#8a96b8;
--up:#ff4d6d;--upf:#3a1424;--dn:#3d8bff;--dnf:#0f2650;--low:#ffd23f;--tgt:#3ef0b0;--cbg:#0a1020}}
body.day{{--bg:#eef2f9;--tile:#fff;--edge:#c5d0e6;--grid:#e6ecf6;--txt:#17213b;--sub:#6b7694;
--up:#e8304f;--upf:#ffe3e8;--dn:#2468e0;--dnf:#dce8ff;--low:#c98a00;--tgt:#0f9e6e;--cbg:#fafcff}}
#reload{{margin-left:6px}}.toast{{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);z-index:20;background:var(--tile);color:var(--txt);border:3px solid #00ff3c;padding:10px 18px;font-size:18px;line-height:1.3;white-space:nowrap;pointer-events:none}}#pct{{margin-left:6px}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--txt);font-family:'Galmuri11','Malgun Gothic',monospace}}
header{{display:flex;gap:12px;justify-content:space-between;align-items:center;padding:8px 10px;border-bottom:1px solid var(--edge)}}
h1{{margin:0;font-size:22px;white-space:nowrap}}#avg{{font-family:'GalmuriMono11','Galmuri11',monospace}}#ttl{{cursor:pointer}}
.toast{{}}body.baronly .grid-wrap{{position:relative;padding-top:16px!important}}body.baronly .grid-wrap::before{{content:attr(data-since);position:absolute;left:14px;top:3px;font-size:12px;line-height:1;color:var(--sub)}}#ha{{display:none}}body.baronly #ha{{display:block}}
.hapop{{position:fixed;inset:0;z-index:31;background:#000;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));grid-auto-rows:calc((100dvh - 34px)/4);overflow-y:auto;gap:6px;padding:8px;cursor:pointer}}.hapop[hidden]{{display:none}}
.mk{{-webkit-user-select:none;user-select:none;-webkit-touch-callout:none}}.mk-drag{{border-color:#ffb300!important;opacity:.85}}.mk{{display:flex;flex-direction:column;min-height:0;border:2px solid #1e2a48;padding:4px}}.mk b{{font-weight:normal;font-size:min(14px,3.5vw);color:#e8ecff;white-space:nowrap;overflow:hidden}}.mk i{{font-style:normal;color:#00ff3c}}.mk small{{font-size:11px;color:#8a96c0;white-space:nowrap}}.mk small.mk-s u{{font-size:inherit}}.mk small.mk-s{{white-space:normal;font-size:10px;line-height:1.3;word-break:keep-all}}.mk u{{text-decoration:none;color:#ffb300;font-size:13px}}
.mk svg{{flex:1;min-height:0;width:100%;height:100%}}.mk-c{{fill:none;stroke:#3fae3f;stroke-width:7;stroke-linejoin:round;stroke-linecap:round}}.mk-m{{stroke:#8a96c0;stroke-width:1.5;stroke-dasharray:3 3}}
.mk-p{{fill:none;stroke:#ff2a3c;stroke-width:3;stroke-linejoin:round}}.mk-d{{fill:#ffb300;stroke:#000;stroke-width:1.5}}.mk-t{{fill:#e8ecff;font-size:11px;text-anchor:middle}}
body:has(.avgpop) .toast{{display:none}}.avgpop{{position:fixed;inset:0;z-index:30;display:flex;flex-direction:column;align-items:center;justify-content:center;background:transparent;cursor:pointer}}
.avgpop b{{font-family:'GalmuriMono11','Galmuri11',monospace;font-weight:normal;font-size:min(34vw,220px);line-height:1;
  text-shadow:0 0 6px #000,0 0 18px #000,0 0 30px #000}}
.note{{color:var(--sub);font-size:10px;padding:4px 10px 0}}
.grid-wrap{{display:grid;grid-auto-flow:dense;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px;padding:12px 16px}}
@media(min-width:601px){{.grid-wrap{{grid-template-columns:repeat(4,minmax(0,1fr));grid-auto-flow:row}}{pc_order}
.grid-wrap .tile:not(.zoom) .chart{{aspect-ratio:auto;height:max(36px,calc((100vh - 132px) / {(len(chart_items) + 3) // 4} - 132px))}}}}
@media(max-width:600px){{.grid-wrap .chart{{aspect-ratio:30/10}}.tabs{{gap:3px}}.tabs button{{padding:2px 5px!important}}#reload,#pct,#bar{{margin-left:2px!important}}header{{padding:6px 4px!important;gap:4px!important}}.grid-wrap{{grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:5px;padding:6px}}.price{{font-size:16px!important}}h1{{font-size:16px!important}}.tabs button{{font-size:12px!important;padding:2px 4px!important}}.tile{{padding:5px 6px}}.name{{font-size:12px}}.chg,.tgttxt{{font-size:10px}}.chart{{margin-top:4px}}}}
.wide{{grid-column:1/-1}}.wide .chart{{aspect-ratio:30/5}}.wide .tgttxt{{display:inline-block;margin-right:14px}}.tgttxt{{white-space:nowrap}}.name small{{color:var(--sub);font-size:.72em;white-space:nowrap}}.name{{white-space:nowrap;overflow:hidden}}
.tile{{background:var(--tile);border:3px solid var(--edge);padding:10px}}
.name{{font-size:15px}}.price{{font-size:22px;margin:4px 0 2px}}.chg{{font-size:12px}}
.up .chg{{color:var(--up)}}.down .chg{{color:var(--dn)}}
.chart{{position:relative;margin-top:8px;border:3px solid var(--edge);background:var(--cbg);aspect-ratio:30/11}}
.ax{{position:absolute;left:3px;font-size:9px;color:var(--sub);pointer-events:none}}.ax.top{{top:2px}}.ax.bot{{bottom:2px}}
.view{{display:none}}body[data-v="240"] .view[data-v="240"],body[data-v="일"] .view[data-v="일"],body[data-v="주"] .view[data-v="주"],body[data-v="월"] .view[data-v="월"]{{display:block}}
.tabs{{display:flex;gap:6px}}.tabs button{{font:inherit;font-size:15px;color:var(--txt);background:var(--tile);border:3px solid var(--edge);padding:4px 10px;cursor:pointer}}
body[data-v="240"] .tabs [data-v="240"],body[data-v="일"] .tabs [data-v="일"],body[data-v="주"] .tabs [data-v="주"],body[data-v="월"] .tabs [data-v="월"]{{color:var(--low);border-color:var(--low)}}
.tile{{cursor:zoom-in;touch-action:manipulation;-webkit-user-select:none;user-select:none}}.tile.hl{{border-color:#ffb300}}.x{{display:none;float:right;color:var(--sub)}}
#fold,#sync{{font:inherit;font-size:inherit;color:var(--low);background:none;border:1px solid var(--edge);padding:0 6px;cursor:pointer}}
body.nochart .tile:not(.zoom) .view{{display:none!important}}body.nochart .tile:not(.zoom){{padding-top:6px;padding-bottom:6px}}
body.nochart .tile:not(.zoom) .gauge{{margin-top:6px;height:7px}}
/* 접었을 때 휴대폰: 남는 자리만큼 글씨 크게 */
@media(max-width:600px){{body.nochart .tile:not(.zoom) .name{{font-size:15px}}body.nochart .tile:not(.zoom) .price{{font-size:22px!important;margin:2px 0 1px}}
body.nochart .tile:not(.zoom) .chg,body.nochart .tile:not(.zoom) .tgttxt{{font-size:12px}}}}
.tile.zoom{{position:fixed;inset:0;z-index:9;overflow:auto;cursor:zoom-out;padding:16px}}.tile.zoom .x{{display:inline}}
.tile.zoom .chart{{aspect-ratio:auto;height:62vh}}.tile.zoom .name{{font-size:20px}}.tile.zoom .price{{font-size:30px}}
.tile.zoom .tgttxt{{font-size:14px}}.tile.zoom .ax{{font-size:12px}}
svg{{width:100%;height:100%;display:block}}
.grid line{{stroke:var(--grid);stroke-width:1}}
.line{{fill:none;stroke-width:4;shape-rendering:crispEdges;vector-effect:non-scaling-stroke}}
.up .line{{stroke:var(--up)}}.down .line{{stroke:var(--dn)}}.up .area{{fill:var(--upf)}}.down .area{{fill:var(--dnf)}}
.tgt{{stroke:var(--tgt);stroke-width:1.5;stroke-dasharray:2 3;vector-effect:non-scaling-stroke}}
.peak{{display:none;position:absolute;z-index:2;transform:translate(-50%,-140%);font-size:13px;color:var(--txt);background:var(--cbg);padding:0 3px;white-space:nowrap;pointer-events:none}}
.peak.r{{transform:translate(-95%,-140%)}}.peak::after{{content:"";position:absolute;left:50%;bottom:-9px;width:7px;height:7px;margin-left:-3px;background:var(--txt)}}
.peak.r::after{{left:auto;right:2px}}.tile.zoom .peak{{display:block}}
.tgts{{cursor:pointer}}.gauge[hidden]{{display:none}}
rect.cu{{fill:var(--up)}}rect.cd{{fill:var(--dn)}}line.cu{{stroke:var(--up)}}line.cd{{stroke:var(--dn)}}
line.cu,line.cd{{stroke-width:1.5;vector-effect:non-scaling-stroke}}
.gauge{{height:5px;margin-top:4px;background:var(--grid)}}.gauge i{{display:block;height:100%}}
.lv4{{--lv:#ff0033}}.lv3{{--lv:#ff5500}}.lv2{{--lv:#66ff00}}.lv1{{--lv:#00ff2a}}
body.day .lv4{{--lv:#d8203f}}body.day .lv3{{--lv:#d9690a}}body.day .lv2{{--lv:#6f9a00}}body.day .lv1{{--lv:#1f9e3a}}
.tile[class*=" lv"] .name{{color:var(--lv)}}
.below{{--win:#00ff3c}}body.day .below{{--win:#00a82a}}.below .name,.below .price,.below .tgttxt b{{color:color-mix(in srgb,var(--win) var(--gp),var(--txt))}}.below .gauge i{{margin-left:auto;background:var(--win)}}.gauge i{{background:var(--lv)}}
.tgttxt{{margin-top:3px;font-size:11px;color:var(--tgt)}}.tgttxt b{{font-weight:normal;color:var(--sub)}}
.badge.t{{background:var(--tgt)}}
.badge{{margin-left:6px;font-size:10px;background:var(--low);color:#000;padding:1px 4px}}
.err{{color:var(--up);font-size:12px;padding:0 16px}}
.tile[data-bar-only]:not(.zoom){{display:none}}
#bar{{margin-left:6px}}.bar-live{{display:none}}
body.baronly{{background:#000;height:calc(100vh - 8px);height:calc(var(--bar-viewport,100dvh) - max(8px,env(safe-area-inset-bottom,0px)));overflow:hidden;display:grid;grid-template-rows:auto minmax(0,1fr) auto}}body.baronly .note,body.baronly .err{{display:none}}
body.baronly .bar-live{{display:block;padding:0;font-size:12.5px;line-height:1.2;color:var(--tgt);white-space:nowrap;font-variant-numeric:tabular-nums}}
body.baronly .grid-wrap{{grid-template-columns:minmax(0,1fr)!important;grid-template-rows:minmax(0,1fr);grid-auto-rows:minmax(0,1fr);align-content:stretch;min-height:0;gap:clamp(4px,.7dvh,8px);padding-block:clamp(4px,.7dvh,7px)}}
.baravg{{display:none;appearance:none;border:0;padding:0;margin:0;background:transparent;color:inherit;font:inherit;cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent}}body.baronly .baravg{{display:flex;align-items:center;justify-content:center;min-height:0;font-family:'GalmuriMono11','Galmuri11',monospace;font-size:min(20vw,9.5dvh,112px);line-height:1;overflow:hidden}}
.bar-footer{{display:none}}
body.baronly .bar-footer{{position:relative;display:grid;grid-template-columns:minmax(0,1fr);align-items:center;min-height:clamp(60px,10dvh,96px)}}

.bar-footer .baravg{{min-width:0}}.bar-leading[hidden]{{display:none}}
.bar-leading{{position:absolute;right:clamp(6px,1.5vw,16px);top:max(32px,calc(50% - 42px));transform:translateY(-50%);width:clamp(56px,16vw,84px);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;min-width:0;color:#fff;line-height:1.2;text-align:center}}
.bar-leading-value{{font-family:'GalmuriMono11','Galmuri11',monospace;font-size:clamp(16px,4.4vw,22px);font-variant-numeric:tabular-nums;white-space:nowrap}}
.bar-leading-meta{{font-size:clamp(9px,2.4vw,11px);color:#fff;line-height:1.4;word-break:keep-all;overflow-wrap:anywhere}}
/* 바 모드: 9종목. BATL 빼고 나스닥 종합, WTI, SOXS는 바 전용. 화면 높이에 맞춰 표시. */
body.baronly .tile:not(.zoom){{display:grid;grid-template-columns:minmax(0,1fr);grid-template-areas:"name" "price";row-gap:4px;align-items:center;align-content:center;min-height:0;background:none;border:0;padding:0 4px;cursor:zoom-in}}body.baronly .tile:not(.zoom)>:not(.name):not(.price):not(.gauge),body.baronly .name small{{display:none!important}}
body.baronly .tile:not(.zoom)[data-sym="ecos:901Y067/I16E"],body.baronly .tile:not(.zoom)[data-sym="^KS11"],body.baronly .tile:not(.zoom)[data-sym="^KQ11"],body.baronly .tile:not(.zoom)[data-sym="BATL"]{{display:none}}
body.baronly .grid-wrap .tile:not(.zoom){{padding-block:0!important}}
body.baronly .grid-wrap .tile:not(.zoom) .name{{grid-area:name;font-size:19px!important;line-height:1.1}}
body.baronly .grid-wrap .tile:not(.zoom) .price{{grid-area:price;z-index:1;justify-self:start;align-self:center;padding-left:6px;font-family:'GalmuriMono11','Galmuri11',monospace;font-size:19px!important;font-variant-numeric:tabular-nums;line-height:1;margin:0!important;white-space:nowrap;color:#000;text-shadow:none;pointer-events:none}}
body.baronly .grid-wrap .tile:not(.zoom) .gauge{{grid-area:2 / 1 / 3 / -1;z-index:0;height:24px!important;margin:0!important;min-width:0}}
body.baronly .grid-wrap .tile:not(.zoom)[data-sym="upbit:KRW-BTC"]{{order:0}}body.baronly .tile:not(.zoom)[data-sym="upbit:KRW-BTC"] .gauge{{position:relative}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="USDE"]{{order:1}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="SDEV"]{{order:2}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="AXTI"]{{order:5}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="SOXL"]{{order:3}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="AXTX"]{{order:4}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="^IXIC"]{{order:6}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="CL=F"]{{order:7}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="SOXS"]{{order:8}}
body.baronly .grid-wrap .tile:not(.zoom) .gauge[hidden]{{display:block!important}}body.baronly .grid-wrap .tile:not(.zoom) .gauge[hidden] i{{width:0!important}}
@media(max-width:600px){{body.baronly header{{flex-wrap:wrap;row-gap:6px!important}}}}
@media(max-height:760px){{body.baronly .tile:not(.zoom)[data-sym="upbit:KRW-BTC"] .gauge::after{{left:auto;right:0;top:auto;bottom:calc(100% + 2px);margin-top:0}}}}
@media(max-height:700px){{body.baronly .tile:not(.zoom){{row-gap:3px}}body.baronly .grid-wrap .tile:not(.zoom) .name{{font-size:17px!important}}body.baronly .grid-wrap .tile:not(.zoom) .price{{font-size:18px!important}}body.baronly .grid-wrap .tile:not(.zoom) .gauge{{height:22px!important}}}}
@media(max-height:620px){{body.baronly .grid-wrap{{gap:4px;padding-block:4px}}body.baronly .tile:not(.zoom){{row-gap:3px}}body.baronly .grid-wrap .tile:not(.zoom) .name{{font-size:14px!important}}body.baronly .grid-wrap .tile:not(.zoom) .gauge{{height:19px!important}}}}
@media(max-height:580px){{body.baronly .grid-wrap{{gap:1px;padding-block:3px}}body.baronly .tile:not(.zoom){{row-gap:2px}}body.baronly .grid-wrap .tile:not(.zoom) .name{{font-size:12px!important}}body.baronly .grid-wrap .tile:not(.zoom) .price{{font-size:14px!important}}body.baronly .grid-wrap .tile:not(.zoom) .gauge{{height:15px!important}}}}
body.baronly .below:not(.zoom) .gauge i{{position:relative}}body.baronly .below:not(.zoom) .gauge i::after{{content:attr(data-p);position:absolute;right:6px;top:50%;transform:translateY(-50%);font-family:'GalmuriMono11','Galmuri11',monospace;font-size:18px;line-height:1;color:#000;white-space:nowrap}}
/* 꾹 누른 막대만 이동. 확대 차트의 터치·스크롤은 기존대로. */
body.baronly .grid-wrap .tile:not(.zoom)[data-bar-order]{{order:var(--bar-order);touch-action:none;-webkit-touch-callout:none}}
body.baronly .grid-wrap .tile.bar-dragging:not(.zoom){{position:relative;z-index:12;cursor:grabbing;background:#07150f;outline:2px solid var(--tgt);outline-offset:0;transform:translateY(var(--bar-drag-y,0px))}}
body.bar-sorting,body.bar-sorting .tile{{cursor:grabbing}}
/* 설정 버튼 공통 모양 */
.settings-trigger{{font:inherit;color:var(--txt);background:var(--tile);border:1px solid var(--edge);padding:1px 6px;line-height:1.2;cursor:pointer;touch-action:manipulation}}
.note{{display:flow-root}}.grid-wrap{{clear:both;width:100%}}.note .settings-trigger{{float:right;margin-left:6px}}
button:active{{background:#173026!important;border-color:var(--tgt)!important}}
body.baronly .baravg:active{{background:transparent!important}}
#reload[aria-busy="true"]{{color:var(--tgt);border-color:var(--tgt)}}
.zoom-tools{{display:none}}
body:has(.tile.zoom){{overflow:hidden}}
.tile.zoom .zoom-tools{{display:flex;align-items:center;justify-content:flex-end;gap:10px;position:sticky;top:-16px;z-index:4;background:var(--tile);padding:10px 0;margin:4px 0}}
.tile.zoom .zoom-tools .tabs{{gap:6px}}
.tabs button:disabled{{opacity:.35;cursor:default}}
.tile.zoom .price{{font-size:clamp(22px,6vw,30px)!important}}
#avg-settings{{position:fixed;inset:0;width:min(420px,calc(100vw - 24px));max-height:calc(100dvh - 24px);margin:auto;padding:16px;color:var(--txt);background:var(--tile);border:2px solid var(--tgt);font:inherit;overflow:hidden}}
#avg-settings-form{{display:flex;flex-direction:column;max-height:calc(100dvh - 60px)}}
#avg-settings::backdrop{{background:rgb(0 0 0 / .75)}}
.settings-heading{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}}
.settings-heading h2{{font-size:18px;margin:0}}
.settings-heading button{{font:inherit;color:var(--txt);background:none;border:0;cursor:pointer;padding:4px 6px}}
.settings-hint{{font-size:11px;line-height:1.5;color:var(--sub);margin:0 0 12px}}
#avg-options{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;overflow:auto;overscroll-behavior:contain;min-height:0}}
.settings-heading,.settings-hint,.settings-actions,#avg-selection-count{{flex-shrink:0}}
.avg-option{{display:flex;align-items:center;gap:8px;min-height:44px;padding:7px;background:var(--cbg);border:1px solid var(--edge);cursor:pointer;font-size:13px}}
.avg-option:has(input:checked){{border-color:var(--tgt)}}
.avg-option input{{width:18px;height:18px;flex:0 0 auto;margin:0;accent-color:var(--tgt);cursor:pointer}}
.avg-option span{{min-width:0;overflow-wrap:anywhere}}
.avg-option small{{display:block;font-size:10px;margin-top:4px;color:var(--sub)}}
.settings-actions{{display:flex;gap:8px;justify-content:flex-end;margin-top:14px}}
.settings-actions button{{font:inherit;font-size:13px;padding:7px 12px;color:var(--txt);border:2px solid var(--edge);background:var(--cbg);cursor:pointer}}
.settings-actions button[type="submit"]{{border-color:var(--tgt);color:var(--tgt)}}
#avg-selection-count{{font-size:11px;color:var(--tgt);margin:12px 0 0}}
@media(max-width:350px){{.avg-option{{font-size:12px;gap:5px;padding:6px}}.tile.zoom .zoom-tools{{gap:6px}}.tile.zoom .zoom-tools .tabs{{gap:4px}}}}
/* 바 모드 상단만 두 줄로 확대. */
body.baronly>header{{display:grid;grid-template-columns:minmax(0,1fr) clamp(164px,46vw,192px);grid-template-rows:auto minmax(0,1fr);grid-template-areas:"title controls" "live controls";column-gap:8px!important;row-gap:4px!important}}
body.baronly>header>h1{{grid-area:title;align-self:start;min-width:0;padding-top:8px;font-size:18px!important}}
body.baronly>header>.bar-live{{grid-area:live;align-self:start;margin-top:2px;justify-self:start;min-width:0}}
body.baronly>header>.tabs{{grid-area:controls;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:4px;width:clamp(164px,46vw,192px);flex:0 0 clamp(164px,46vw,192px)}}
body.baronly>header>.tabs>button{{min-width:0;min-height:40px;font-size:16px!important;line-height:1.15;padding:5px 3px!important;touch-action:manipulation}}
body.baronly>header>.tabs>#reload,body.baronly>header>.tabs>#pct,body.baronly>header>.tabs>#bar{{margin:0!important}}
@media(max-width:350px){{body.baronly>header{{grid-template-columns:minmax(0,1fr) 164px;column-gap:4px!important}}body.baronly>header>.tabs{{width:164px;flex-basis:164px}}body.baronly>header>.tabs>button{{min-height:38px;font-size:15px!important;padding:4px 2px!important}}}}
/* 일반 차트는 기존 버튼, 큰 두 줄 버튼은 바 모드에만 적용. */
body:not(.baronly)>header .settings-trigger{{display:none}}

body.baronly>header>.tabs>#reload{{grid-column:1;grid-row:2}}
body.baronly>header>.tabs>#pct{{display:none}}body.baronly>header>.tabs>#ha{{grid-column:4;grid-row:2;margin:0!important}}
body.baronly>header>.tabs>.settings-trigger{{grid-column:2;grid-row:2}}
/* ===== 새 디자인 (시안 적용) ===== */
:root{{--bg:#05070d;--tile:#0c111d;--edge:#1a2236;--grid:#141b2e;--cbg:#070b15;--acc:#ffb300;--tabh:calc(58px + env(safe-area-inset-bottom,0px))}}
body{{padding-bottom:var(--tabh)}}
.tile{{border:1px solid var(--edge)!important;border-radius:12px}}.tile.hl{{box-shadow:inset 0 0 0 2px var(--acc)}}
.chart{{border:1px solid var(--edge)!important;border-radius:8px;overflow:hidden}}
.price{{font-family:'GalmuriMono11','Galmuri11',monospace;font-variant-numeric:tabular-nums}}
.gauge{{border-radius:3px;overflow:hidden}}.gauge i{{border-radius:3px}}
header{{border-bottom:0!important}}
#ttl .ttl-s{{font-size:.8em;color:var(--sub);font-weight:normal}}#avg{{font-size:1.25em}}
header #pct,header #bar,header #ha,header .settings-trigger,.note .settings-trigger{{display:none!important}}
header .tabs{{background:var(--tile);border:1px solid var(--edge);border-radius:10px;padding:3px;gap:2px!important}}
header .tabs button,.zoom-tools .tabs button{{border:0!important;border-radius:7px;background:transparent;color:var(--sub);padding:5px 10px}}
header .tabs button[aria-pressed="true"],.zoom-tools .tabs button[aria-pressed="true"]{{background:#1c2540!important;color:var(--txt)!important}}
#reload{{color:var(--txt)!important}}
#live::before,#bar-stamp::before{{content:"";display:inline-block;width:6px;height:6px;margin-right:5px;border-radius:50%;background:#00ff3c;box-shadow:0 0 5px #00ff3c;vertical-align:1px}}
#fold,#sync{{border-radius:8px}}
.tabbar{{position:fixed;left:0;right:0;bottom:0;z-index:32;display:flex;background:#070a12;border-top:1px solid var(--edge);padding:6px 0 calc(6px + env(safe-area-inset-bottom,0px))}}
.tabbar button{{flex:1;font:inherit;font-size:11px;color:#4a5576;background:none!important;border:0!important;padding:2px 0;cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent}}
.tabbar button span{{display:block;font-size:19px;line-height:1.2}}.tabbar button.on{{color:var(--acc)}}
body:has(.tile.zoom) .tabbar{{display:none}}
/* 바 모드 */
body.baronly{{padding-bottom:0;height:calc(var(--bar-viewport,100dvh) - var(--tabh))!important}}
body.baronly>header{{grid-template-columns:minmax(0,1fr) auto!important}}
body.baronly>header>.tabs{{display:flex!important;width:auto!important;flex:0 0 auto!important;align-self:center}}
body.baronly>header>.tabs>button{{min-height:0!important;font-size:13px!important;padding:5px 8px!important}}
body.baronly .grid-wrap .tile:not(.zoom){{border:0!important;border-radius:0}}body.baronly .grid-wrap .tile:not(.zoom) .gauge{{border-radius:5px}}body.baronly .grid-wrap .tile:not(.zoom) .gauge i{{border-radius:5px}}
body.baronly .bar-footer{{margin:2px 10px 6px;border:1px solid var(--edge);border-radius:14px;background:var(--tile)}}
/* 하 */
.hapop{{bottom:var(--tabh)!important;cursor:default;grid-auto-rows:calc((100dvh - var(--tabh) - 84px)/4)!important;gap:8px!important;padding:10px!important;background:var(--bg)!important}}
.mk-h{{grid-column:1/-1;padding:2px 4px}}.mk-h small{{display:block;font-size:12px;color:var(--sub)}}.mk-h b{{font-weight:normal;font-size:20px}}.mk-h b u{{text-decoration:none;color:var(--acc)}}
.mk{{border:1px solid var(--edge)!important;border-radius:12px;background:var(--tile);padding:7px 8px 4px!important}}
.mk b u{{background:#3a2500;padding:0 6px;border-radius:9px;font-size:11px!important}}
.mk svg{{overflow:visible}}.mk{{position:relative}}.mk .mk-w{{position:absolute;right:9px;top:30px;font-size:10px}}
.mk.mk-drag{{border:2px solid #ffb300!important}}
.hapop{{grid-template-rows:auto}}.mk-bar{{grid-column:1/-1;justify-self:end;display:flex;gap:2px;background:var(--tile);border:1px solid var(--edge);border-radius:10px;padding:3px}}
.toast[data-refresh]{{z-index:40}}.mk-bar button{{font:inherit;font-size:13px;color:var(--sub);background:transparent;border:0;border-radius:7px;padding:5px 12px;cursor:pointer}}.mk-bar .mk-rl{{color:var(--txt)}}
.hapop[data-hv="일"] .mk-bar [data-hv="일"],.hapop[data-hv="주"] .mk-bar [data-hv="주"],.hapop[data-hv="월"] .mk-bar [data-hv="월"]{{background:#1c2540;color:var(--txt)}}
.hapop[data-hv="일"] .mk[data-hv]:not([data-hv="일"]),.hapop[data-hv="주"] .mk[data-hv]:not([data-hv="주"]),.hapop[data-hv="월"] .mk[data-hv]:not([data-hv="월"]){{display:none!important}}
.tile{{-webkit-touch-callout:none}}.tile.bo-drag{{outline:2px solid #ffb300;outline-offset:-1px;opacity:.9;z-index:5;position:relative}}
@media(max-width:600px){{body:not(.baronly) .grid-wrap .tile[data-bo]{{order:var(--bo)}}}}.mk-p{{stroke-width:2.2!important}}
/* 설정 */
#avg-settings{{border:1px solid var(--edge)!important;border-radius:16px;background:var(--bg)!important}}
#avg-options{{grid-template-columns:minmax(0,1fr)!important;gap:0!important;border:1px solid var(--edge);border-radius:12px;background:var(--tile)}}
.avg-option{{border:0!important;border-bottom:1px solid var(--edge)!important;background:none!important;font-size:14px;padding:8px 14px}}.avg-option:last-child{{border-bottom:0!important}}
.avg-option input{{order:2;margin-left:auto!important;appearance:none;-webkit-appearance:none;width:38px!important;height:22px!important;border-radius:11px;background:#222b44;position:relative;transition:background .15s}}
.avg-option input::after{{content:"";position:absolute;left:3px;top:3px;width:16px;height:16px;border-radius:50%;background:#56607c;transition:left .15s}}
.avg-option input:checked{{background:#0a5a22}}.avg-option input:checked::after{{left:19px;background:#00ff3c}}
.settings-actions button{{border-radius:10px;border-width:1px!important}}
@media(max-width:600px){{body.nochart:not(.baronly){{height:calc(var(--bar-viewport,100dvh) - var(--tabh));padding-bottom:0;display:flex;flex-direction:column;overflow:hidden}}
body.nochart:not(.baronly) .grid-wrap{{flex:1;min-height:0;grid-auto-rows:minmax(0,1fr);align-content:stretch;gap:5px;padding:5px 6px 6px}}
body.nochart:not(.baronly) .grid-wrap .tile:not(.zoom):not([data-bar-only]){{min-height:0;overflow:hidden;display:flex;flex-direction:column;justify-content:safe center;line-height:1.15;padding:2px 9px!important}}
body.nochart:not(.baronly) .tile:not(.zoom) .name{{font-size:min(14px,1.75dvh)!important}}body.nochart:not(.baronly) .tile:not(.zoom) .price{{font-size:min(21px,2.5dvh)!important;margin:1px 0!important}}
body.nochart:not(.baronly) .tile:not(.zoom) .chg,body.nochart:not(.baronly) .tile:not(.zoom) .tgttxt{{font-size:min(12px,1.45dvh)!important}}body.nochart:not(.baronly) .tile:not(.zoom) .gauge{{margin-top:3px;height:6px;flex:0 0 auto}}}}
.since-row{{display:flex;justify-content:space-between;align-items:center;margin-top:12px;padding:8px 14px;border:1px solid var(--edge);border-radius:12px;background:var(--tile);font-size:14px}}
.since-row input{{font:inherit;font-size:13px;color:var(--txt);background:var(--cbg);border:1px solid var(--edge);border-radius:8px;padding:4px 6px;color-scheme:dark}}
</style></head><body>
<header><h1 id="ttl" title="눌러서 목표 평균 크게 보기"><svg viewBox="0 0 16 16" style="width:1em;height:1em;display:inline-block;vertical-align:-.12em"><rect width="16" height="16" rx="2" fill="#3a0d14"/><polyline points="2,13 6,8 9,10 14,3" fill="none" stroke="#ff2a3c" stroke-width="2.2"/></svg> <span class="ttl-s">관심종목</span> <span id="avg" title="목표가까지 남은 거리 평균(막대 평균)"></span></h1><div id="bar-live" class="bar-live"><span id="bar-stamp">실시간 {now[-5:]} 갱신</span></div><div class="tabs">{"".join(f'<button data-v="{k}">{k}</button>' for k in VIEWS)}<button id="reload" onclick="refreshBoard()" aria-label="새로고침">⟳</button><button id="pct" aria-label="목표 평균 크게">%</button><button id="bar" aria-label="막대만 보기">바</button><button id="ha" aria-label="하이먼 민스키 모델 겹쳐 보기">하</button><button type="button" class="settings-trigger" aria-label="평균 종목 설정" title="평균 종목 설정" onclick="openAvgSettings()">⚙</button></div></header>

<div class="note"><b id="live" style="font-weight:normal;color:var(--tgt)">{now} 기준</b> · <span id="vdesc"></span> · <i style="color:var(--tgt)">╍ 목표가</i> · <button id="fold">차트 접기</button> <button id="sync">동기화</button><button type="button" class="settings-trigger" aria-label="평균 종목 설정" title="평균 종목 설정" onclick="openAvgSettings()">⚙</button></div>
{err}{ha}<div class="grid-wrap">{"".join(tile(d) for d in items)}</div><div class="bar-footer"><button id="baravg" class="baravg" type="button" aria-label="평균 새로고침" title="눌러서 새로고침" onclick="document.getElementById('reload').click();showPct()"></button><aside id="bar-leading" class="bar-leading" aria-label="선행지수" hidden><div id="bar-leading-value" class="bar-leading-value"></div><div id="bar-leading-meta" class="bar-leading-meta"></div></aside></div>
<nav class="tabbar" aria-label="화면"><button data-k="board"><span>▦</span>보드</button><button data-k="bar"><span>≡</span>바</button><button data-k="ha"><span>∿</span>하</button><button data-k="set"><span>⚙</span>설정</button></nav>
<dialog id="avg-settings" aria-labelledby="avg-settings-title">
<form id="avg-settings-form">
<div class="settings-heading"><h2 id="avg-settings-title">평균 종목</h2><button type="button" aria-label="설정 닫기" onclick="document.getElementById('avg-settings').close()">✕</button></div>
<p class="settings-hint">선택한 종목의 막대 % 평균입니다.<br>목표 아래는 음수 · 목표가가 없으면 제외</p>
<div id="avg-options"></div><p id="avg-selection-count" aria-live="polite"></p>
<label class="since-row">막대 기준일 <input type="date" id="since-in"></label>
<p id="avg-sync-status" class="settings-hint" aria-live="polite"></p>
<div class="settings-actions"><button type="button" aria-label="웹 앱 연동 코드" onclick="askSync(true)">연동 코드</button><button type="submit">적용</button></div>
</form></dialog>

<script>
const D={json.dumps({k: v[4] for k, v in VIEWS.items()}, ensure_ascii=False)};
function setV(v){{if(!D[v])return;document.body.dataset.v=v;document.getElementById('vdesc').textContent=D[v];document.querySelectorAll('.tabs button[data-v]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.v===v)));try{{localStorage.v=v}}catch(e){{}}}}
let saved;try{{saved=localStorage.v}}catch(e){{}}
setV(D[saved]?saved:'일');
document.querySelectorAll('.tabs button[data-v]').forEach(b=>b.onclick=e=>{{e.stopPropagation();setV(b.dataset.v);}});
try{{localStorage.removeItem('day')}}catch(e){{}}  // 데이 모드 없앰
const RAW='https://raw.githubusercontent.com/{CFG.get("repo", "andrewjhshin-debug/watchlist-board")}/live/m/';
const pad=n=>String(n).padStart(2,'0');
const slot=k=>{{const d=new Date(Date.now()+9*36e5-k*6e4);return d.getUTCFullYear()+pad(d.getUTCMonth()+1)+pad(d.getUTCDate())+pad(d.getUTCHours())+pad(d.getUTCMinutes());}};
const moneyFormat=new Intl.NumberFormat('en-US',{{minimumFractionDigits:2,maximumFractionDigits:2}}),wholeFormat=new Intl.NumberFormat('en-US',{{maximumFractionDigits:0}});
const f2=(v,c)=>c==='KRW'?wholeFormat.format(Math.round(v)):moneyFormat.format(v);
const fs=(v,c)=>c==='KRW'&&v>=1e6?wholeFormat.format(Math.round(v/1e4))+'만':f2(v,c);
function getT(el){{try{{const v=localStorage['tg:'+el.dataset.sym];if(v!=null)return JSON.parse(v);}}catch(e){{}}return JSON.parse(el.dataset.tgts0||'[]');}}
function renderT(el){{
  const t=getT(el),c=el.dataset.cur,key=JSON.stringify(t);if(el._targetsPainted&&el.dataset.tgts===key)return;el._targetsPainted=true;el._quoteState=null;el.dataset.tgts=key;
  el.querySelector('.tgts').innerHTML=t.length?t.map(x=>'<div class="tgttxt" data-t="'+x+'">목표 '+fs(x,c)+' <b></b></div>').join(''):'<div class="tgttxt">목표 설정 ✎</div>';
  el.querySelector('.gauge').hidden=!t.length;
  el.querySelectorAll('svg[data-vmin]').forEach(s=>{{s.querySelectorAll('.tgt').forEach(l=>l.remove());
    const lo=+s.dataset.vmin,hi=+s.dataset.vmax,vb=s.viewBox.baseVal;
    t.forEach(x=>{{const y=Math.max(1,Math.min(vb.height-1,vb.height-{CELL / 2}-Math.round((x-lo)/((hi-lo)||1)*{ROWS - 1})*{CELL}));
      const l=document.createElementNS('http://www.w3.org/2000/svg','line');l.setAttribute('class','tgt');
      l.setAttribute('x1',0);l.setAttribute('x2',vb.width);l.setAttribute('y1',y);l.setAttribute('y2',y);s.appendChild(l);}});}});
}}
// 목표가 폰끼리 공유: 본인 Firebase(watchlist-board) 문서 1개. 문서 이름 = 동기화 코드(폰마다 한 번 입력)
const FS='https://firestore.googleapis.com/v1/projects/{CFG["sync_project"]}/databases/(default)/documents/targets/';
const FK='{CFG["sync_key"]}';  // 웹용 공개 키(접근 제한은 코드+보안 규칙)
const ls=(k,v)=>{{try{{if(v===undefined)return localStorage[k];localStorage[k]=v;}}catch(e){{}}}};
const tileList=[...document.querySelectorAll('.tile[data-sym]')],tileBySym=new Map(tileList.map(el=>[el.dataset.sym,el]));
const tiles=()=>tileList;
function registerTile(el){{tileList.push(el);tileBySym.set(el.dataset.sym,el);}}
function repaint(){{tiles().forEach(el=>{{renderT(el);apply(el.dataset.sym,+el.dataset.p,+el.dataset.pv);}});}}
// 목표가·강조 표시·평균 종목·바 순서를 같은 동기화 코드의 문서에서 공유한다.
let targetPullJob=null,targetPullCode=null,targetPullGeneration=0,avgWriteJob=null,avgWriteCode=null,avgSyncState='',avgSettingsDirty=false,avgGeneration=0;
const avgPendingKey=c=>'avg-pending:'+c;
function paintAvgSync(){{
  const el=document.getElementById('avg-sync-status');if(!el)return;
  const code=ls('sync'),pending=code&&(ls(avgPendingKey(code))||ls(barOrderPendingKey(code)));
  el.textContent=!code?'같은 연동 코드를 쓰면 웹·앱에 함께 적용돼요.':pending?(avgSyncState.includes('재시도')?'연동 재시도 중':'웹·앱 연동 중'):avgSyncState||'연동 확인 중';
}}
function adoptSharedAverage(value){{
  if(!Array.isArray(value)||!value.every(s=>typeof s==='string'))return false;
  const next=[...new Set(value)];ls(AVG_KEY,JSON.stringify(next));avgSymbols=new Set(next);showAvg();
  const dialog=document.getElementById('avg-settings');
  if(dialog?.open&&!avgSettingsDirty){{document.querySelectorAll('#avg-options input').forEach(input=>input.checked=avgSymbols.has(input.value));avgSettingsSummary();}}
  return true;
}}
async function updateShared(change){{
  const code=ls('sync');if(!code)return null;
  for(let attempt=0;attempt<3;attempt++){{
    try{{
      const r=await fetch(FS+code+'?key='+FK,{{cache:'no-store'}});if(!r.ok)return null;
      const doc=await r.json(),m=JSON.parse(doc.fields?.json?.stringValue||'{{}}');
      if(ls('sync')!==code)return null;
      if(change(m)===false)return m;
      if(!doc.updateTime)return null;
      const url=FS+code+'?key='+FK+'&updateMask.fieldPaths=json&currentDocument.updateTime='+encodeURIComponent(doc.updateTime);
      const saved=await fetch(url,{{method:'PATCH',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{fields:{{json:{{stringValue:JSON.stringify(m)}}}}}})}});
      if(saved.ok)return m;
      if(saved.status!==409&&saved.status!==412){{const error=await saved.json().catch(()=>null);if(!['FAILED_PRECONDITION','ABORTED'].includes(error?.error?.status))return null;}}
    }}catch(e){{return null;}}
  }}
  return null;
}}
function pushAverage(){{
  if(avgWriteJob)return avgWriteCode===ls('sync')?avgWriteJob:avgWriteJob.then(()=>pushAverage());
  avgWriteCode=ls('sync');
  avgWriteJob=(async()=>{{
    const code=ls('sync');if(!code){{paintAvgSync();return false;}}
    const key=avgPendingKey(code);
    while(ls('sync')===code&&ls(key)){{
      const snapshot=ls(key);let selected;try{{selected=JSON.parse(snapshot);}}catch(e){{return false;}}
      avgSyncState='평균 연동 중';paintAvgSync();
      const saved=await updateShared(m=>{{m._avg=selected;}});
      if(!saved){{avgSyncState='연동 재시도 중';paintAvgSync();return false;}}
      if(ls('sync')!==code)return false;
      if(ls(key)===snapshot)ls(key,'');
    }}
    avgSyncState='웹·앱 연동됨';paintAvgSync();return true;
  }})().finally(()=>{{avgWriteJob=null;}});
  return avgWriteJob;
}}
function pullT(){{
  const code=ls('sync');if(targetPullJob&&targetPullCode===code)return targetPullJob;
  targetPullCode=code;const request=++targetPullGeneration;
  targetPullJob=(async()=>{{
    const generation=avgGeneration,orderGeneration=barOrderGeneration;if(!code){{paintAvgSync();return null;}}
    if(ls(avgPendingKey(code))&&!(await pushAverage()))return null;
    if(ls(barOrderPendingKey(code)))await pushBarOrder();
    try{{
      const r=await fetch(FS+code+'?key='+FK,{{cache:'no-store'}});if(!r.ok)throw Error('sync');
      const doc=await r.json(),m=JSON.parse(doc.fields?.json?.stringValue||'{{}}');if(ls('sync')!==code)return null;
      let changed=false;
      for(const sym in m){{
        if(sym.startsWith('_')&&sym!=='_hl')continue;
        const key=sym==='_hl'?'hl':'tg:'+sym,value=JSON.stringify(m[sym]);
        if(ls(key)!==value){{ls(key,value);changed=true;}}
      }}
      if(changed){{repaint();paintHL();}}
      if(typeof m._since==='string'&&m._since!==ls('since')){{ls('since',m._since);applySince();}}
      if(Array.isArray(m._boardOrder)&&!boP&&JSON.stringify(m._boardOrder)!==ls('board-order'))applyBo(m._boardOrder);
      if(Array.isArray(m._haOrder)&&!haP&&JSON.stringify(m._haOrder)!==ls('ha-order'))applyHa(m._haOrder);
      if(generation===avgGeneration&&!ls(avgPendingKey(code))){{
        if(Array.isArray(m._avg))adoptSharedAverage(m._avg);
        else if(ls(AVG_KEY)!=null){{
          // 처음 연동할 때만 기존 선택을 옮긴다. 다른 기기가 먼저 저장했다면 그 값을 따른다.
          const selected=[...avgSymbols],migrated=await updateShared(remote=>{{if(Array.isArray(remote._avg))return false;remote._avg=selected;}});
          if(!migrated)throw Error('sync');
          if(ls('sync')===code&&generation===avgGeneration&&!ls(avgPendingKey(code)))adoptSharedAverage(migrated._avg);
        }}
      }}
      if(ls('sync')===code&&orderGeneration===barOrderGeneration&&!barPress&&!ls(barOrderPendingKey(code))){{
        if(Array.isArray(m._barOrder))adoptSharedBarOrder(m._barOrder);
        else if(ls(BAR_ORDER_KEY)!=null){{
          const order=readBarOrder(),migrated=await updateShared(remote=>{{if(Array.isArray(remote._barOrder))return false;remote._barOrder=order;}});
          if(!migrated)throw Error('sync');
          if(ls('sync')===code&&orderGeneration===barOrderGeneration&&!barPress&&!ls(barOrderPendingKey(code)))adoptSharedBarOrder(migrated._barOrder);
        }}
      }}
      if(ls('sync')!==code)return null;
      if(!ls(avgPendingKey(code))&&!ls(barOrderPendingKey(code)))avgSyncState='웹·앱 연동됨';paintAvgSync();return m;
    }}catch(e){{avgSyncState='연동 재시도 중';paintAvgSync();return null;}}
  }})().finally(()=>{{if(request===targetPullGeneration)targetPullJob=null;}});
  return targetPullJob;
}}
async function pushT(){{
  const changes={{}};tiles().forEach(el=>changes[el.dataset.sym]=getT(el));changes._hl=getHL();
  return updateShared(m=>Object.assign(m,changes));
}}

async function askSync(force){{if(!force&&(ls('sync')||ls('syncAsked')))return;ls('syncAsked','1');
  const c=prompt('동기화 코드를 입력하세요\\n(PC 다운로드 폴더의 관심종목_동기화코드.txt)',ls('sync')||'');
  if(!c)return;ls('sync',c.trim());const m=await pullT();
  if(m===null){{ls('sync','');alert('코드가 맞지 않아요');}}else if(!Object.keys(m).length)await pushT();  // 처음이면 이 폰 값을 올림
  syncLabel();}}
function syncLabel(){{const b=document.getElementById('sync');if(b)b.textContent=ls('sync')?'동기화됨':'동기화';paintAvgSync();}}
function editT(ev,box){{ev.stopPropagation();editT2(box.closest('.tile'));}}
async function editT2(el){{await askSync();
  const v=prompt(el.querySelector('.name').firstChild.textContent.trim()+' 목표가\\n여러 개는 쉼표로 (예: 100, 98)\\n비우면 목표 없음',getT(el).join(', '));
  if(v===null)return;const t=v.split(/[ ,]+/).map(x=>parseFloat(x.replace(/[^0-9.]/g,''))).filter(x=>x>0);
  ls('tg:'+el.dataset.sym,JSON.stringify(t));
  renderT(el);apply(el.dataset.sym,+el.dataset.p,+el.dataset.pv);pushT();}}
function paintBarLeading(el){{
  const b=document.getElementById('bar-leading');if(!b)return;
  const value=el.querySelector('.price')?.textContent.trim()||'',note=el.querySelector('.name small')?.textContent.trim()||'';
  b.hidden=!value;
  document.getElementById('bar-leading-value').textContent=value;
  document.getElementById('bar-leading-meta').textContent=note?'('+note+')':'';
}}
function apply(sym,price,prev){{
  const el=tileBySym.get(sym);if(!el)return;
  const state=[price,prev,el.dataset.hi,el.dataset.tgts].join('|');if(el._quoteState===state)return;el._quoteState=state;
  const c=el.dataset.cur,ch=price-prev;el.dataset.p=price;el.dataset.pv=prev;
  el.querySelector('.price').textContent=f2(price,c);
  if(sym==='ecos:901Y067/I16E')paintBarLeading(el);
  el.classList.toggle('up',ch>=0);el.classList.toggle('down',ch<0);
  el.querySelector('.chg').textContent=(ch>=0?'▲ ':'▼ ')+f2(Math.abs(ch),c)+' ('+(ch>=0?'+':'')+(ch/prev*100).toFixed(2)+'%)';
  el.querySelectorAll('.tgttxt[data-t]').forEach(t=>{{const g=price/+t.dataset.t-1;t.querySelector('b').textContent=(g>=0?'+':'')+(g*100).toFixed(1)+'%';}});
  const ts=JSON.parse(el.dataset.tgts||'[]');delete el.dataset.left;
  {{const gg=el.querySelector('.gauge');if(ts.length){{const g=price/Math.max(...ts)-1;gg.dataset.g=(g>=0?'+':'')+(g*100).toFixed(1)+'%';}}else delete gg.dataset.g;}}el.classList.remove('lv1','lv2','lv3','lv4','below');
  if(ts.length){{const t=Math.max(...ts),hi=+el.dataset.hi,fill=el.querySelector('.gauge i');
    if(price<t){{const depth=Math.min(1,(t-price)/t/.3);el.classList.add('below');el.style.setProperty('--gp',Math.round(75+25*depth)+'%');el.dataset.left=-depth;
      fill.style.width=Math.round(depth*100)+'%';fill.dataset.p=f2(price,c);}}
    else{{const left=hi>t?Math.max(0,Math.min(1,(price-t)/(hi-t))):0;el.dataset.left=left;
      fill.style.width=Math.round(left*100)+'%';el.classList.add('lv'+(left>=.75?4:left>=.5?3:left>=.25?2:1));
      el.style.setProperty('--lv',['#00ff2a','#22ff00','#55ff00','#88ff00','#ffee00','#ffbb00','#ff8000','#ff5500','#ff2a00','#ff0033'][Math.min(9,Math.floor(left*10))]);}}
  }}
  queueAvg();
}}

// 제목을 누르면 화면은 그대로 두고 가운데에 평균 % 만 크게. 아무 데나 누르면 닫힘
function showPct(){{const a=document.getElementById('avg');if(!a.textContent)return;
  const d=document.createElement('div');d.className='avgpop';
  d.innerHTML='<b style="color:'+a.style.color+'">'+a.textContent+'</b>';
  d.onclick=()=>history.back();document.body.appendChild(d);history.pushState({{pop:1}},'');}}
document.getElementById('ttl').onclick=showPct;
const hapop=document.getElementById('hapop');
document.getElementById('ha').onclick=()=>{{if(!hapop)return;hapop.hidden=false;history.pushState({{pop:1}},'');}};
if(hapop)hapop.onclick=()=>{{if(Date.now()<haSkip)return;history.back();}};
// 하: 칸을 꾹 눌러 끌면 순서 바뀜(모델 칸은 늘 맨 앞). 동기화 문서 _haOrder 로 기기끼리 공유
let haP=null,haSkip=0;
function applyHa(order){{if(!hapop||!Array.isArray(order))return;ls('ha-order',JSON.stringify(order));
  const cells=[...hapop.querySelectorAll('.mk[data-k]')],rk=el=>{{const i=order.indexOf(el.dataset.k);return i<0?999+cells.indexOf(el):i;}};
  hapop.append(...cells.sort((a,b)=>rk(a)-rk(b)));}}
try{{applyHa(JSON.parse(ls('ha-order')||'null'));}}catch(e){{}}
function setHv(v){{if(!hapop)return;hapop.dataset.hv=v;ls('ha-v',v);}}
setHv(ls('ha-v')||'주');
async function refreshHa(){{const b=hapop.querySelector('.mk-rl');b.disabled=true;
  try{{const url=new URL(location.href);url.searchParams.set('_refresh',Date.now());
    const doc=new DOMParser().parseFromString(await (await fetch(url,{{cache:'no-store'}})).text(),'text/html'),nh=doc.getElementById('hapop');
    if(nh){{hapop.querySelectorAll('.mk').forEach(c=>c.remove());hapop.append(...nh.querySelectorAll('.mk'));try{{applyHa(JSON.parse(ls('ha-order')||'null'));}}catch(e){{}}}}
    showRefreshToast(nh?'새로고침했습니다':'새로고침하지 못했습니다');}}catch(e){{showRefreshToast('새로고침하지 못했습니다');}}finally{{b.disabled=false;}}}}
if(hapop)hapop.querySelector('.mk-bar').onclick=e=>{{e.stopPropagation();const b=e.target.closest('button');if(!b)return;if(b.dataset.hv)setHv(b.dataset.hv);else refreshHa();}};
if(hapop){{
  hapop.addEventListener('pointerdown',e=>{{const el=e.target.closest('.mk[data-k]');if(!el||e.button!==0)return;
    const p={{el,id:e.pointerId,x:e.clientX,y:e.clientY,active:false}};haP=p;
    p.timer=setTimeout(()=>{{if(haP!==p)return;p.active=true;el.classList.add('mk-drag');try{{el.setPointerCapture(p.id);}}catch(e){{}}}},450);}});
  hapop.addEventListener('pointermove',e=>{{const p=haP;if(!p||e.pointerId!==p.id)return;
    if(!p.active){{if(Math.hypot(e.clientX-p.x,e.clientY-p.y)>10){{clearTimeout(p.timer);haP=null;}}return;}}
    const t=document.elementFromPoint(e.clientX,e.clientY)?.closest('.mk[data-k]');
    if(t&&t!==p.el){{const cs=[...hapop.children];cs.indexOf(t)>cs.indexOf(p.el)?t.after(p.el):t.before(p.el);}}
    const r=hapop.getBoundingClientRect();if(e.clientY>r.bottom-40)hapop.scrollTop+=12;else if(e.clientY<r.top+40)hapop.scrollTop-=12;}});
  const end=e=>{{const p=haP;if(!p||e.pointerId!==p.id)return;clearTimeout(p.timer);haP=null;if(!p.active)return;
    p.el.classList.remove('mk-drag');haSkip=Date.now()+500;
    const order=[...new Set([...hapop.querySelectorAll('.mk[data-k]')].filter(c=>c.offsetParent).map(c=>c.dataset.k))];applyHa(order);
    if(ls('sync'))updateShared(m=>{{m._haOrder=order;}});}};
  for(const t of ['pointerup','pointercancel'])hapop.addEventListener(t,end);
  hapop.addEventListener('touchmove',e=>{{if(haP?.active)e.preventDefault();}},{{passive:false}});
  hapop.addEventListener('contextmenu',e=>e.preventDefault());
}}
document.getElementById('pct').onclick=showPct;
addEventListener('popstate',()=>{{document.querySelectorAll('.tile.zoom').forEach(e=>e.classList.remove('zoom'));
  document.querySelectorAll('.avgpop').forEach(d=>d.remove());if(hapop)hapop.hidden=true;}});
// 목표 평균 색 10단계(10% 단위): 0~40% 초록 4단계(낮을수록 진함) → 노랑 → 주황 → 빨강
const AC=['#00ff3c','#3dff5a','#7dff6e','#b4ff7a','#e6f04a','#ffd23f','#ffaa33','#ff8a3c','#ff6a50','#ff4d6d'];
const AVG_CATALOG={avg_catalog};
const AVG_DEFAULT=['upbit:KRW-BTC','USDE','SDEV','SOXL','AXTX','AXTI'];
const AVG_KEY='avg-symbols-v1';
function readAvgSymbols(){{
  try{{const value=JSON.parse(ls(AVG_KEY)||'null');if(Array.isArray(value))return [...new Set(value.filter(s=>typeof s==='string'))];}}catch(e){{}}
  return AVG_DEFAULT.slice();
}}
let avgSymbols=new Set(readAvgSymbols()),avgFrame=0;
function queueAvg(){{if(!avgFrame)avgFrame=requestAnimationFrame(()=>{{avgFrame=0;showAvg();}});}}
let refreshAverageNamesVisible=false,refreshAverageNamesTimer=null;
function averageMembers(){{return tiles().filter(el=>avgSymbols.has(el.dataset.sym)&&el.dataset.left!==undefined&&Number.isFinite(+el.dataset.left));}}
function paintRefreshAverageNames(members=averageMembers()){{
  const included=new Set(refreshAverageNamesVisible&&document.body.classList.contains('baronly')?members:[]);
  tiles().forEach(el=>el.classList.toggle('avg-refresh-member',included.has(el)));
}}
function clearRefreshAverageNames(){{
  clearTimeout(refreshAverageNamesTimer);refreshAverageNamesVisible=false;
  tiles().forEach(el=>el.classList.remove('avg-refresh-member'));
}}
function showRefreshAverageNames(duration=0){{
  clearTimeout(refreshAverageNamesTimer);refreshAverageNamesVisible=true;paintRefreshAverageNames();
  if(duration)refreshAverageNamesTimer=setTimeout(clearRefreshAverageNames,duration);
}}

function showAvg(){{
  const members=averageMembers(),values=members.map(el=>+el.dataset.left);
  if(refreshAverageNamesVisible)paintRefreshAverageNames(members);
  const mean=values.length?values.reduce((a,b)=>a+b,0)/values.length:null;
  const text=mean===null?'—':Math.round(mean*100)+'%',color=mean===null?'var(--sub)':AC[Math.max(0,Math.min(9,Math.floor(mean*10)))];
  for(const id of ['avg','baravg']){{const el=document.getElementById(id);if(el){{if(el.textContent!==text)el.textContent=text;el.style.color=color;}}}}
  document.querySelectorAll('.avgpop b').forEach(b=>{{b.textContent=text;b.style.color=color;}});
}}
function avgSettingsSummary(){{
  const selected=[...document.querySelectorAll('#avg-options input:checked')];
  const ready=selected.filter(input=>{{const el=tileBySym.get(input.value);return el&&getT(el).length;}}).length;
  document.getElementById('avg-selection-count').textContent=selected.length+'개 선택 · '+ready+'개 계산';
}}
function openAvgSettings(){{
  const dialog=document.getElementById('avg-settings'),options=document.getElementById('avg-options');avgSettingsDirty=false;
  options.replaceChildren();
  for(const item of AVG_CATALOG){{
    const row=document.createElement('label'),input=document.createElement('input'),text=document.createElement('span'),name=document.createElement('span');
    row.className='avg-option';input.type='checkbox';input.value=item.sym;input.checked=avgSymbols.has(item.sym);
    name.textContent=item.name;text.appendChild(name);const el=tileBySym.get(item.sym);
    if(!el||!getT(el).length){{const note=document.createElement('small');note.textContent=el?'목표가 없음':'데이터 없음';text.appendChild(note);}}
    row.append(input,text);options.appendChild(row);
  }}
  avgSettingsSummary();paintAvgSync();dialog.showModal();pullT();
}}
document.getElementById('avg-options').addEventListener('change',()=>{{avgSettingsDirty=true;avgSettingsSummary();}});
if(document.getElementById('avg-default'))document.getElementById('avg-default').onclick=()=>{{avgSettingsDirty=true;
  document.querySelectorAll('#avg-options input').forEach(input=>input.checked=AVG_DEFAULT.includes(input.value));avgSettingsSummary();
}};
document.getElementById('avg-settings-form').addEventListener('submit',e=>{{
  e.preventDefault();avgSymbols=new Set([...document.querySelectorAll('#avg-options input:checked')].map(input=>input.value));
  const saved=JSON.stringify([...avgSymbols]);avgGeneration++;ls(AVG_KEY,saved);showAvg();document.getElementById('avg-settings').close();
  const code=ls('sync');if(code){{ls(avgPendingKey(code),saved);pushAverage();}}
}});
addEventListener('storage',e=>{{if(e.key===AVG_KEY){{avgGeneration++;avgSymbols=new Set(readAvgSymbols());showAvg();}}}});

const stamp=t=>{{const n=document.getElementById('live');if(n)n.textContent='실시간 '+t;const b=document.getElementById('bar-stamp');if(b)b.textContent='실시간 '+t.slice(0,5)+' 갱신';}};
let lastSlot='{datetime.now(KST):%Y%m%d%H%M}';
async function pollLive(force=false){{if(!force&&document.visibilityState==='hidden')return false;for(let k=force?0:1;k<=6;k++){{const sl=slot(k);if(sl<lastSlot)return false;try{{const r=await fetch(RAW+sl+'.json'+(force?'?t='+Date.now():''),{{cache:'no-store'}});
  if(r.ok){{lastSlot=sl;const j=await r.json();if(j.b&&j.b!==BUILD)staleReload();for(const x in j.q)if(!x.startsWith('upbit:'))apply(x,j.q[x][0],j.q[x][1]);stamp(j.t);return true;}}}}catch(e){{}}}}return false;}}
const UP=[...document.querySelectorAll('.tile[data-sym^="upbit:"]')].map(e=>e.dataset.sym.slice(6));
async function pollUpbit(){{if(document.visibilityState==='hidden'||!UP.length)return false;try{{const r=await fetch('https://api.upbit.com/v1/ticker?markets='+UP.join(','),{{cache:'no-store'}});if(!r.ok)return false;
  const rows=await r.json();for(const x of rows)apply('upbit:'+x.market,x.trade_price,x.prev_closing_price);return rows.length>0;}}catch(e){{return false;}}}}
let refreshJob=null,refreshAnnounce=false,refreshToastTimer=null;
function showRefreshToast(message){{
  let toast=document.querySelector('.toast[data-refresh]');
  if(!toast){{toast=document.createElement('div');toast.className='toast';toast.dataset.refresh='1';toast.setAttribute('role','status');toast.setAttribute('aria-live','polite');document.body.appendChild(toast);}}
  toast.textContent=message;clearTimeout(refreshToastTimer);
  refreshToastTimer=setTimeout(()=>toast.remove(),1800);
}}
const BUILD=document.querySelector('meta[name=build]').content;
// 옛 코드 화면이면 통째로 새로 받음. 배포 직후 엇갈려 계속 새로고침하지 않게 5분에 한 번만
function staleReload(){{let t=0;try{{t=+sessionStorage.staleAt||0;}}catch(e){{}}if(Date.now()-t<300000)return false;
  try{{sessionStorage.staleAt=Date.now();}}catch(e){{}}location.reload();return true;}}
async function refreshCharts(){{
  try{{
    const url=new URL(location.href);url.searchParams.set('_refresh',Date.now());
    const response=await fetch(url,{{cache:'no-store'}});if(!response.ok)return false;
    const next=new DOMParser().parseFromString(await response.text(),'text/html');
    const nb=next.querySelector('meta[name=build]');if(nb&&nb.content!==BUILD&&staleReload())return true;
    const incoming=[...next.querySelectorAll('.tile[data-sym]')];
    if(!next.querySelector('#baravg')||!incoming.length)return false;
    const current=tileBySym;
    const board=document.querySelector('.grid-wrap');
    for(const fresh of incoming){{
      const sym=fresh.dataset.sym;let el=current.get(sym);
      if(!el){{el=fresh;board.appendChild(el);registerTile(el);}}
      else{{
        for(const key of ['hi','tgts0','pd'])if(fresh.dataset[key]!==undefined)el.dataset[key]=fresh.dataset[key];
        const name=el.querySelector('.name'),nextName=fresh.querySelector('.name');
        if(name&&nextName&&name.innerHTML!==nextName.innerHTML)name.replaceChildren(...nextName.childNodes);
        for(const view of [...fresh.querySelectorAll('.view')]){{
          const old=el.querySelector('.view[data-v="'+view.dataset.v+'"]');
          if(old){{if(old.innerHTML!==view.innerHTML){{old.replaceChildren(...view.childNodes);el._targetsPainted=false;}}}}
          else{{el.insertBefore(view,el.querySelector('.gauge'));el._targetsPainted=false;}}
        }}
        el.querySelectorAll('.zoom-tools button[data-v]').forEach(button=>button.disabled=!el.querySelector('.view[data-v="'+button.dataset.v+'"]'));
        if(sym.startsWith('ecos:')){{el.dataset.p=fresh.dataset.p;el.dataset.pv=fresh.dataset.pv;}}
      }}
      renderT(el);apply(sym,+el.dataset.p,+el.dataset.pv);
    }}
    paintHL();if(!barPress)applyBarOrder();applySince();return true;
  }}catch(e){{return false;}}
}}
function refreshBoard(announce=true){{
  refreshAnnounce=refreshAnnounce||announce;
  if(announce&&document.body.classList.contains('baronly'))showRefreshAverageNames();
  if(refreshJob)return refreshJob;
  const reload=document.getElementById('reload');reload.setAttribute('aria-busy','true');
  refreshJob=(async()=>{{
    const results=await Promise.allSettled([refreshCharts(),pollLive(true),pollUpbit(),pullT()]);
    const ok=results.slice(0,3).some(r=>r.status==='fulfilled'&&r.value);
    if(refreshAnnounce){{if(refreshAverageNamesVisible)showRefreshAverageNames(1500);showRefreshToast(ok?'새로고침했습니다':'새로고침하지 못했습니다');}}
    return ok;
  }})().finally(()=>{{refreshJob=null;refreshAnnounce=false;reload.removeAttribute('aria-busy');}});
  return refreshJob;
}}

// 바 순서는 같은 동기화 코드의 웹·앱에서 공유. 차트 모드 배치는 유지한다.
const BAR_ORDER_KEY='bar-order-v1';
const BAR_DEFAULT_ORDER=['upbit:KRW-BTC','USDE','SDEV','SOXL','AXTX','AXTI','^IXIC','CL=F','SOXS'];
const barBoard=document.querySelector('.grid-wrap');
let barPress=null,barSkipClickUntil=0;
const barOrderPendingKey=code=>'bar-order-pending:'+code;
let barOrderGeneration=0,barOrderWriteJob=null,barOrderWriteCode=null;
function adoptSharedBarOrder(value){{
  if(barPress||!Array.isArray(value)||!value.every(sym=>typeof sym==='string'))return false;
  const order=[...new Set(value)];ls(BAR_ORDER_KEY,JSON.stringify(order));applyBarOrder(order);return true;
}}
function saveBarOrder(order){{
  const saved=JSON.stringify([...new Set(order)]);barOrderGeneration++;ls(BAR_ORDER_KEY,saved);
  const code=ls('sync');if(code){{ls(barOrderPendingKey(code),saved);pushBarOrder();}}
}}
function pushBarOrder(){{
  if(barOrderWriteJob)return barOrderWriteCode===ls('sync')?barOrderWriteJob:barOrderWriteJob.then(()=>pushBarOrder());
  barOrderWriteCode=ls('sync');
  barOrderWriteJob=(async()=>{{
    const code=ls('sync');if(!code)return false;const key=barOrderPendingKey(code);
    while(ls('sync')===code&&ls(key)){{
      const snapshot=ls(key);let order;try{{order=JSON.parse(snapshot);}}catch(e){{return false;}}
      if(!Array.isArray(order)||!order.every(sym=>typeof sym==='string'))return false;
      avgSyncState='종목 순서 연동 중';paintAvgSync();
      const saved=await updateShared(remote=>{{remote._barOrder=order;}});
      if(!saved){{avgSyncState='연동 재시도 중';paintAvgSync();return false;}}
      if(ls('sync')!==code)return false;
      if(ls(key)===snapshot)ls(key,'');
    }}
    avgSyncState='웹·앱 연동됨';paintAvgSync();return true;
  }})().finally(()=>{{barOrderWriteJob=null;}});
  return barOrderWriteJob;
}}

function readBarOrder(){{try{{const v=JSON.parse(ls(BAR_ORDER_KEY)||'[]');return Array.isArray(v)?v.filter(s=>typeof s==='string'):[];}}catch(e){{return [];}}}}
function applyBarOrder(order=readBarOrder()){{
  const all=tiles(),rank=[...new Set([...order,...BAR_DEFAULT_ORDER,...all.map(el=>el.dataset.sym)])];
  const on=document.body.classList.contains('baronly');
  all.forEach(el=>{{
    const n=rank.indexOf(el.dataset.sym);el.dataset.barOrder=n;el.style.setProperty('--bar-order',n);
    const visible=on&&!el.classList.contains('zoom')&&getComputedStyle(el).display!=='none';
    if(visible){{el.tabIndex=0;el.setAttribute('title','꾹 누른 뒤 위아래로 끌어 순서 변경 · Alt+↑↓');}}
    else{{el.removeAttribute('tabindex');el.removeAttribute('title');}}
  }});
}}
function barRows(){{return [...barBoard.querySelectorAll('.tile[data-sym]:not(.zoom)')].filter(el=>getComputedStyle(el).display!=='none').sort((a,b)=>+a.dataset.barOrder-+b.dataset.barOrder);}}
function barTile(target){{return target.closest?.('.tile[data-sym]:not(.zoom)');}}
function moveBarPress(y){{
  const p=barPress;if(!p?.active)return;
  let at=0;for(let i=1;i<p.centers.length;i++)if(Math.abs(y-p.centers[i])<Math.abs(y-p.centers[at]))at=i;
  const next=p.rows.filter(el=>el!==p.el);next.splice(at,0,p.el);
  const order=next.map(el=>el.dataset.sym);if(order.join('|')!==p.order.join('|')){{p.order=order;applyBarOrder(p.order);}}
  p.el.style.setProperty('--bar-drag-y','0px');
  const r=p.el.getBoundingClientRect(),board=barBoard.getBoundingClientRect();
  const top=Math.max(board.top,Math.min(board.bottom-r.height,y-p.offset));
  p.el.style.setProperty('--bar-drag-y',(top-r.top)+'px');
}}
function finishBarPress(save=false){{
  const p=barPress;if(!p)return;barPress=null;clearTimeout(p.timer);
  if(p.active){{
    barSkipClickUntil=Date.now()+700;
    if(save&&p.order.join('|')!==p.before.join('|'))saveBarOrder(p.order);
    p.el.classList.remove('bar-dragging');p.el.style.removeProperty('--bar-drag-y');document.body.classList.remove('bar-sorting');
    applyBarOrder(save?p.order:p.before);
  }}
  try{{if(p.el.hasPointerCapture(p.id))p.el.releasePointerCapture(p.id);}}catch(e){{}}
}}
barBoard.addEventListener('pointerdown',e=>{{
  if(barPress){{finishBarPress(false);return;}}
  const el=barTile(e.target);
  if(!document.body.classList.contains('baronly')||document.querySelector('.tile.zoom')||!el||e.isPrimary===false||e.button!==0)return;
  barSkipClickUntil=0;
  const p={{el,id:e.pointerId,x:e.clientX,y:e.clientY,active:false}};barPress=p;
  try{{el.setPointerCapture(e.pointerId);}}catch(e){{}}
  p.timer=setTimeout(()=>{{
    if(barPress!==p)return;
    p.rows=barRows();p.before=p.rows.map(row=>row.dataset.sym);p.order=p.before.slice();
    p.centers=p.rows.map(row=>{{const r=row.getBoundingClientRect();return r.top+r.height/2;}});
    p.offset=p.y-el.getBoundingClientRect().top;p.active=true;
    clearTimeout(tapT);tapT=null;el.classList.add('bar-dragging');document.body.classList.add('bar-sorting');
  }},450);
}});
barBoard.addEventListener('pointermove',e=>{{
  const p=barPress;if(!p||e.pointerId!==p.id)return;
  if(p.active){{e.preventDefault();moveBarPress(e.clientY);}}
  else if(Math.hypot(e.clientX-p.x,e.clientY-p.y)>10){{barSkipClickUntil=Date.now()+700;finishBarPress(false);}}
}},{{passive:false}});
barBoard.addEventListener('pointerup',e=>{{if(barPress?.id===e.pointerId)finishBarPress(true);}});
barBoard.addEventListener('pointercancel',e=>{{if(barPress?.id===e.pointerId)finishBarPress(false);}});
barBoard.addEventListener('lostpointercapture',e=>{{if(barPress?.id===e.pointerId)finishBarPress(false);}});
barBoard.addEventListener('click',e=>{{if(barPress?.active||Date.now()<barSkipClickUntil){{e.preventDefault();e.stopImmediatePropagation();}}}},true);
for(const type of ['contextmenu','dragstart'])barBoard.addEventListener(type,e=>{{if(document.body.classList.contains('baronly')&&barTile(e.target))e.preventDefault();}});
barBoard.addEventListener('keydown',e=>{{
  if(e.key==='Escape'&&barPress){{e.preventDefault();finishBarPress(false);return;}}
  const el=barTile(e.target);if(!document.body.classList.contains('baronly')||document.querySelector('.tile.zoom')||!el)return;
  if(e.altKey&&['ArrowUp','ArrowDown'].includes(e.key)){{
    e.preventDefault();finishBarPress(false);const rows=barRows(),from=rows.indexOf(el),to=from+(e.key==='ArrowUp'?-1:1);
    if(from<0||to<0||to>=rows.length)return;
    rows.splice(from,1);rows.splice(to,0,el);const order=rows.map(row=>row.dataset.sym);
    saveBarOrder(order);applyBarOrder(order);
  }}else if(e.key==='Enter'||e.key===' '){{e.preventDefault();el.click();}}
}});
addEventListener('blur',()=>finishBarPress(false));
addEventListener('resize',()=>finishBarPress(false));
document.addEventListener('visibilitychange',()=>{{if(document.visibilityState==='hidden'){{clearRefreshAverageNames();finishBarPress(false);}}}});
addEventListener('storage',e=>{{if(e.key===BAR_ORDER_KEY){{barOrderGeneration++;if(!barPress)applyBarOrder();}}}});
applyBarOrder();

// 차트 접기: 휴대폰은 처음엔 접힌 상태(12종목이 한 화면에), 선택은 기억
const fold=document.getElementById('fold');
function setF(on){{document.body.classList.toggle('nochart',on);fold.textContent=on?'차트 펴기':'차트 접기';ls('fold',on?'1':'0');}}
fold.onclick=()=>setF(!document.body.classList.contains('nochart'));
setF(innerWidth<601&&ls('fold')!=='0');
function fitBarViewport(){{const h=Math.floor(window.visualViewport?.height||innerHeight);if(h>0)document.body.style.setProperty('--bar-viewport',h+'px');}}
addEventListener('resize',fitBarViewport);window.visualViewport?.addEventListener('resize',fitBarViewport);
const barB=document.getElementById('bar');
function setB(on){{clearRefreshAverageNames();finishBarPress(false);fitBarViewport();document.body.classList.toggle('baronly',on);barB.style.color=on?'var(--low)':'';barB.style.borderColor=on?'var(--low)':'';ls('bar',on?'1':'0');applyBarOrder();paintTab();}}
function paintTab(){{const k=hapop&&!hapop.hidden?'ha':document.body.classList.contains('baronly')?'bar':'board';document.querySelectorAll('.tabbar button').forEach(b=>b.classList.toggle('on',b.dataset.k===k));}}
document.querySelector('.tabbar').onclick=e=>{{const b=e.target.closest('button');if(!b)return;const k=b.dataset.k;
  if(k==='set'){{openAvgSettings();return;}}
  if(k==='ha'){{if(hapop&&hapop.hidden)document.getElementById('ha').click();paintTab();return;}}
  if(hapop&&!hapop.hidden)history.back();
  setB(k==='bar');}};
addEventListener('popstate',paintTab);
barB.onclick=()=>setB(!document.body.classList.contains('baronly'));setB(ls('bar')==='1');
document.getElementById('sync').onclick=()=>askSync(true);syncLabel();
// 노란 테두리: 카드를 두 번 톡톡(더블탭·더블클릭)하면 켜고 끔, 한 번이면 차트 크게. 폰끼리 동기화
function getHL(){{try{{return JSON.parse(ls('hl')||'[]');}}catch(e){{return [];}}}}
function paintHL(){{const h=getHL();tiles().forEach(el=>el.classList.toggle('hl',h.includes(el.dataset.sym)));}}
function toggleHL(el){{const h=getHL(),s=el.dataset.sym,i=h.indexOf(s);i<0?h.push(s):h.splice(i,1);ls('hl',JSON.stringify(h));paintHL();pushT();
  if(navigator.vibrate)navigator.vibrate(30);}}
// 차트 모드: 두 번 톡톡 = 테두리만(펼치지 않음), 한 번 = 잠깐 기다렸다 펼침. 바 모드는 바로 펼침.
let tapT=null,tapEl=null,tapAt=0;
function openChart(el){{
  if(!el.querySelector('.view[data-v="'+document.body.dataset.v+'"]')){{
    const fallback=el.querySelector('.view[data-v="일"]')||el.querySelector('.view');if(fallback)setV(fallback.dataset.v);
  }}
  el.classList.add('zoom');history.pushState({{pop:1}},'');
}}
function tap(el){{
  if(el.classList.contains('zoom')){{history.back();return;}}
  if(document.body.classList.contains('baronly')){{openChart(el);return;}}
  if(tapT&&tapEl===el){{clearTimeout(tapT);tapT=null;toggleHL(el);return;}}
  clearTimeout(tapT);tapEl=el;tapT=setTimeout(()=>{{tapT=null;openChart(el);}},300);
}}
// 막대 기준일(설정에서 고름): 그날 다음 날부터의 최고가 = 막대 100%. 동기화 코드로 공유
const SINCE0=(d=>{{d.setDate(d.getDate()-1);return d.toISOString().slice(0,10);}})(new Date("{CFG.get('gauge_since', '2026-07-31')}T00:00:00Z"));
function sinceDay(){{return ls('since')||SINCE0;}}
function applySince(){{const d=sinceDay(),n=new Date(d+'T00:00:00Z');n.setUTCDate(n.getUTCDate()+1);const from=n.toISOString().slice(0,10);
  barBoard.dataset.since=(+d.slice(5,7))+'/'+(+d.slice(8,10));const si=document.getElementById('since-in');if(si)si.value=d;
  tiles().forEach(el=>{{let m;try{{m=JSON.parse(el.dataset.pd||'null');}}catch(e){{}}if(!m)return;
    const v=Object.entries(m).filter(([k])=>k>=from).map(([,x])=>x);const hi=v.length?Math.max(...v):Math.max(...Object.values(m));
    if(String(hi)!==el.dataset.hi){{el.dataset.hi=hi;apply(el.dataset.sym,+el.dataset.p,+el.dataset.pv);}}}});}}
document.getElementById('since-in').onchange=e=>{{const v=e.target.value;if(!v)return;ls('since',v);applySince();if(ls('sync'))updateShared(m=>{{m._since=v;}});}};
applySince();
// 보드(휴대폰): 꾹(0.45초) 누르면 노란 테두리 → 끌어서 자리 이동. 꾹 눌렀다 그냥 떼면 아무 일 없음
let boP=null,boSkip=0;
function applyBo(order){{if(!Array.isArray(order))return;ls('board-order',JSON.stringify(order));
  tiles().forEach((el,i)=>{{const k=order.indexOf(el.dataset.sym);el.dataset.bo='';el.style.setProperty('--bo',k<0?100+i:k);}});}}
try{{applyBo(JSON.parse(ls('board-order')||'null'));}}catch(e){{}}
function boRows(){{return tiles().filter(el=>!el.classList.contains('zoom')&&getComputedStyle(el).display!=='none').sort((a,b)=>(+a.style.getPropertyValue('--bo')||0)-(+b.style.getPropertyValue('--bo')||0)||0);}}
barBoard.addEventListener('pointerdown',e=>{{
  if(document.body.classList.contains('baronly')||innerWidth>600||document.querySelector('.tile.zoom')||e.button!==0)return;
  const el=e.target.closest('.tile[data-sym]');if(!el)return;
  if(!el.style.getPropertyValue('--bo'))applyBo(tiles().map(t=>t.dataset.sym));
  const p={{el,id:e.pointerId,x:e.clientX,y:e.clientY,active:false}};boP=p;
  p.timer=setTimeout(()=>{{if(boP!==p)return;p.active=true;clearTimeout(tapT);tapT=null;el.classList.add('bo-drag');try{{el.setPointerCapture(p.id);}}catch(e){{}}if(navigator.vibrate)navigator.vibrate(20);}},450);
}});
barBoard.addEventListener('pointermove',e=>{{const p=boP;if(!p||e.pointerId!==p.id)return;
  if(!p.active){{if(Math.hypot(e.clientX-p.x,e.clientY-p.y)>10){{clearTimeout(p.timer);boP=null;}}return;}}
  const t=document.elementFromPoint(e.clientX,e.clientY)?.closest('.tile[data-sym]');
  if(t&&t!==p.el){{const rows=boRows(),from=rows.indexOf(p.el),to=rows.indexOf(t);if(from>=0&&to>=0){{rows.splice(from,1);rows.splice(to,0,p.el);rows.forEach((r,i)=>r.style.setProperty('--bo',i));}}}}
  if(e.clientY>innerHeight-90)scrollBy(0,10);else if(e.clientY<60)scrollBy(0,-10);
}});
const boEnd=e=>{{const p=boP;if(!p||e.pointerId!==p.id)return;clearTimeout(p.timer);boP=null;if(!p.active)return;
  p.el.classList.remove('bo-drag');boSkip=Date.now()+500;
  const order=boRows().map(r=>r.dataset.sym);applyBo(order);if(ls('sync'))updateShared(m=>{{m._boardOrder=order;}});}};
for(const t of ['pointerup','pointercancel'])barBoard.addEventListener(t,boEnd);
document.addEventListener('touchmove',e=>{{if(boP?.active)e.preventDefault();}},{{passive:false}});
barBoard.addEventListener('click',e=>{{if(boP?.active||Date.now()<boSkip){{e.preventDefault();e.stopImmediatePropagation();}}}},true);
barBoard.addEventListener('contextmenu',e=>{{if(e.target.closest('.tile'))e.preventDefault();}});
paintHL();
repaint();pullT();setInterval(()=>{{if(document.visibilityState==='visible')pullT();}},15000);  // 웹·앱의 목표가와 평균 종목을 함께 가져옴
pollLive();pollUpbit();setInterval(pollLive,30000);setInterval(pollUpbit,15000);
try{{if(sessionStorage.rl){{sessionStorage.removeItem('rl');showRefreshToast('새로고침했습니다');}}}}catch(e){{}}
setInterval(()=>refreshBoard(false),{CFG["refresh_min"] * 60000});
const loadedAt=Date.now();
// 앱을 다시 켰을 때 옛 화면이 보이지 않게: 1분 넘게 쉬었으면 새 화면을 받아 맞출 때까지 가려 둔다(최대 3초)
let hiddenAt=0;
async function resume(){{
  if(Date.now()-Math.max(hiddenAt,loadedAt)<60000){{pullT();return;}}
  document.documentElement.style.visibility='hidden';
  const show=()=>{{document.documentElement.style.visibility='';}};const t=setTimeout(show,3000);
  try{{await refreshBoard(false);}}finally{{clearTimeout(t);show();}}
}}
document.addEventListener('visibilitychange',()=>{{if(document.visibilityState==='hidden')hiddenAt=Date.now();else resume();}});
addEventListener('pageshow',e=>{{if(e.persisted){{hiddenAt=0;resume();}}}});
if('serviceWorker' in navigator)navigator.serviceWorker.register('sw.js',{{updateViaCache:'none'}});
</script></body></html>'''
    (ROOT / "index.html").write_text(page, encoding="utf-8")


# ---------------------------------------------------------------- 실행
def run_once() -> None:
    items, errors = [], []
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
            try:
                now_q = None if s["sym"].startswith("ecos:") else quote(s["sym"])
            except Exception:
                now_q = None
            items.append({"sym": s["sym"], "now": now_q, "peak": peak(s["sym"], views["일"]), "name": s["name"], "target": s.get("target"), "currency": cur, "views": views,
                          "wide": False, "bar_only": s.get("bar_only", False), "last": views["일"].get("last")})
        except Exception as e:  # 한 종목 실패가 전체를 막지 않게
            errors.append(f"{s['name']} 불러오기 실패: {e}")
    try:
        ha = minsky_html()
    except Exception as e:
        ha = ""
        print(f"하 실패: {e}")
    render(items, errors, ha)
    print(f"{datetime.now(KST):%H:%M} 갱신 {len(items)}종목" + (f", 오류 {len(errors)}" if errors else ""))


def self_test() -> None:
    d = {"closes": [10, 9, 12, 11], "currency": "USD"}
    t = tile({"name": "T", "target": 5, "currency": "USD", "views": {"일": d, "주": d}})
    assert t.count('class="view"') == 2 and "목표 5.00" in t and "목표 도달" not in t
    below = tile({"name": "T", "target": 12, "currency": "USD", "views": {"일": d}})                  # 11 < 12: 목표 아래
    assert ' below"' in below and 'width:28%' in below and "목표 도달" not in below            # (12-11)/12/0.3 = 28%
    assert " lv4" in tile({"name": "T", "target": 5, "currency": "USD", "views": {"일": d}})          # 86% → 빨강 단계
    assert 'width:86%' in tile({"name": "T", "target": 5, "currency": "USD", "views": {"일": d}})     # (11-5)/(12-5) = 86%
    assert "<svg" in chart_svg(d) and "class=\"tgt\"" not in chart_svg(d)
    assert chart_svg(d | {"target": [1, 20]}).count('class="tgt"') == 2   # 목표 여러 개
    assert "class=\"tgt\"" in chart_svg(d | {"target": 1})   # 멀리 있는 목표가도 항상 표시
    print("OK")


if __name__ == "__main__":
    if "--live" in sys.argv:
        run_live()
    elif "--test" in sys.argv:
        self_test()
    elif "--loop" in sys.argv:
        while True:
            run_once()
            time.sleep(CFG["refresh_min"] * 60)
    else:
        run_once()
