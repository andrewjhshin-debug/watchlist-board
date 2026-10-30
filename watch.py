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


def peak(sym: str, day: dict) -> tuple[float, str]:
    """gauge_since 이후 최고점(값, 날짜). 미국 종목은 프리·애프터장 포함(60분봉).
    시간외 봉은 거래량 0 인 잘못 찍힌 꼬리(예: AXTX 9/22 150.56)가 있어 시가·종가만 본다."""
    since = CFG.get("gauge_since", "")
    if sym.startswith(("upbit:", "ecos:")):
        rows = list(zip(day.get("highs", day["closes"]), day["dates"]))
    else:
        d = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}"
                     "?range=3mo&interval=60m&includePrePost=true")["chart"]["result"][0]
        q = d["indicators"]["quote"][0]
        rows = [(h if v else max(o, c), datetime.fromtimestamp(t, KST).strftime("%Y-%m-%d"))
                for t, o, h, c, v in zip(d["timestamp"], q["open"], q["high"], q["close"], q["volume"])
                if None not in (o, h, c)]
    return max([r for r in rows if r[1] >= since] or rows)


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
    (out / f"{now:%Y%m%d%H%M}.json").write_text(json.dumps({"t": f"{now:%H:%M:%S}", "q": q}), encoding="utf-8")
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
        pv, pd = d["peak"]
        i = max(j for j, dt in enumerate(dates) if dt <= pd)
        px = (i // k + .5) / m * 100
        py = max(CELL / 2, y(pv)) / H * 100
        peak = f'<span class="peak{" r" if px > 80 else ""}" style="left:{px:.1f}%;top:{py:.1f}%">{fmt(pv, cur)}</span>'
    return f'''{peak}<span class="ax top">{fmt(vmax, cur)}</span><span class="ax bot">{fmt(vmin, cur)}</span><svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" data-vmin="{vmin}" data-vmax="{vmax}">
<g class="grid">{grid}</g>
{body}
{"".join(f'<line class="tgt" x1="0" y1="{y(t)}" x2="{W}" y2="{y(t)}"/>' for t in tgts)}
</svg>'''


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
    live_attr = f' data-hi="{hi}" data-tgts0="{json.dumps(tgts)}" data-tgts="{json.dumps(tgts)}" data-p="{price}" data-pv="{prev}"'
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
    return (f'<div class="tile {cls}{" wide" if d.get("wide") else ""}{lv}" data-sym="{d.get('sym', '')}" data-cur="{cur}"{bar_attr}{live_attr} onclick="tap(this)">'
            f'<div class="name">{html.escape(d["name"])}{when}<span class="x">✕</span></div>'
            f'<div class="price">{fmt(price, cur)}</div>'
            f'<div class="chg">{"▲" if chg >= 0 else "▼"} {fmt(abs(chg), cur)} ({pct:+.2f}%)</div>'
            f'{views}<div class="gauge"{"" if tgts else " hidden"}><i style="width:{left * 100:.0f}%"></i></div>'
            f'<div class="tgts" onclick="editT(event,this)">{tgt or '<div class="tgttxt">목표 설정 ✎</div>'}</div></div>')


def render(items: list[dict], errors: list[str]) -> None:
    now = datetime.now(KST).strftime("%m/%d %H:%M")
    # PC 배치는 config 의 pc_order(4칸, 왼→오, 위→아래). 휴대폰은 symbols 순서 그대로
    chart_items = [d for d in items if not d.get("bar_only")]
    pc = CFG.get("pc_order", [])
    pc_order = "".join(f'.tile[data-sym="{d["sym"]}"]{{order:{pc.index(d["sym"]) if d["sym"] in pc else 99}}}' for d in chart_items)
    err = "".join(f'<div class="err">{html.escape(e)}</div>' for e in errors)
    page = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8">
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
.avgpop{{position:fixed;inset:0;z-index:30;display:flex;flex-direction:column;align-items:center;justify-content:center;background:transparent;cursor:pointer}}
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
body.baronly{{background:#000;height:calc(100vh - 8px);height:calc(var(--bar-viewport,100dvh) - max(8px,env(safe-area-inset-bottom,0px)));overflow:hidden;display:grid;grid-template-rows:auto auto minmax(0,1fr) auto}}body.baronly .note,body.baronly .err{{display:none}}
body.baronly .bar-live{{display:block;padding:4px 10px 0;font-size:11px;line-height:1.2;color:var(--tgt);white-space:nowrap;font-variant-numeric:tabular-nums}}
body.baronly .grid-wrap{{grid-template-columns:minmax(0,1fr)!important;grid-template-rows:minmax(0,1fr);grid-auto-rows:minmax(0,1fr);align-content:stretch;min-height:0;gap:clamp(4px,.7dvh,8px);padding-block:clamp(4px,.7dvh,7px)}}
.baravg{{display:none;appearance:none;border:0;padding:0;margin:0;background:transparent;color:inherit;font:inherit;cursor:pointer;touch-action:manipulation}}body.baronly .baravg{{display:flex;align-items:center;justify-content:center;min-height:0;font-family:'GalmuriMono11','Galmuri11',monospace;font-size:min(20vw,9.5dvh,112px);line-height:1;overflow:hidden}}
.bar-footer{{display:none}}
body.baronly .bar-footer{{position:relative;display:grid;grid-template-columns:minmax(0,1fr);align-items:center;min-height:clamp(60px,10dvh,96px)}}

.bar-footer .baravg{{min-width:0}}.bar-leading[hidden]{{display:none}}
.bar-leading{{position:absolute;right:clamp(6px,1.5vw,16px);top:max(32px,calc(50% - 42px));transform:translateY(-50%);width:clamp(56px,16vw,84px);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;min-width:0;color:#fff;line-height:1.2;text-align:center}}
.bar-leading-value{{font-family:'GalmuriMono11','Galmuri11',monospace;font-size:clamp(16px,4.4vw,22px);font-variant-numeric:tabular-nums;white-space:nowrap}}
.bar-leading-meta{{font-size:clamp(9px,2.4vw,11px);color:#fff;line-height:1.4;word-break:keep-all;overflow-wrap:anywhere}}
/* 바 모드: 9종목. BATL·WTI 복원, SOXS는 바 전용. 화면 높이에 맞춰 표시. */
body.baronly .tile:not(.zoom){{display:grid;grid-template-columns:minmax(0,1fr);grid-template-areas:"name" "price";row-gap:4px;align-items:center;align-content:center;min-height:0;background:none;border:0;padding:0 4px;cursor:zoom-in}}body.baronly .tile:not(.zoom)>:not(.name):not(.price):not(.gauge),body.baronly .name small{{display:none!important}}
body.baronly .tile:not(.zoom)[data-sym="ecos:901Y067/I16E"],body.baronly .tile:not(.zoom)[data-sym="^KS11"],body.baronly .tile:not(.zoom)[data-sym="^KQ11"],body.baronly .tile:not(.zoom)[data-sym="^IXIC"]{{display:none}}
body.baronly .grid-wrap .tile:not(.zoom){{padding-block:0!important}}
body.baronly .grid-wrap .tile:not(.zoom) .name{{grid-area:name;font-size:19px!important;line-height:1.1}}
body.baronly .grid-wrap .tile:not(.zoom) .price{{grid-area:price;z-index:1;justify-self:start;align-self:center;padding-left:6px;font-family:'GalmuriMono11','Galmuri11',monospace;font-size:19px!important;font-variant-numeric:tabular-nums;line-height:1;margin:0!important;white-space:nowrap;color:#000;text-shadow:none;pointer-events:none}}
body.baronly .grid-wrap .tile:not(.zoom) .gauge{{grid-area:2 / 1 / 3 / -1;z-index:0;height:24px!important;margin:0!important;min-width:0}}
body.baronly .grid-wrap .tile:not(.zoom)[data-sym="upbit:KRW-BTC"]{{order:0}}body.baronly .tile:not(.zoom)[data-sym="upbit:KRW-BTC"] .gauge{{position:relative}}body.baronly .tile:not(.zoom)[data-sym="upbit:KRW-BTC"] .gauge::after{{content:"7/30";position:absolute;left:0;top:100%;margin-top:2px;font-size:12px;line-height:1;color:var(--sub)}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="USDE"]{{order:1}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="SDEV"]{{order:2}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="AXTI"]{{order:5}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="SOXL"]{{order:3}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="AXTX"]{{order:4}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="BATL"]{{order:6}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="CL=F"]{{order:7}}body.baronly .grid-wrap .tile:not(.zoom)[data-sym="SOXS"]{{order:8}}
body.baronly .grid-wrap .tile:not(.zoom) .gauge[hidden]{{display:block!important}}body.baronly .grid-wrap .tile:not(.zoom) .gauge[hidden] i{{width:0!important}}
@media(max-width:600px){{body.baronly header{{flex-wrap:wrap;row-gap:6px!important}}}}
@media(max-height:760px){{body.baronly .tile:not(.zoom)[data-sym="upbit:KRW-BTC"] .gauge::after{{left:auto;right:0;top:auto;bottom:calc(100% + 2px);margin-top:0}}}}
@media(max-height:700px){{body.baronly .tile:not(.zoom){{row-gap:3px}}body.baronly .grid-wrap .tile:not(.zoom) .name{{font-size:17px!important}}body.baronly .grid-wrap .tile:not(.zoom) .price{{font-size:18px!important}}body.baronly .grid-wrap .tile:not(.zoom) .gauge{{height:22px!important}}}}
@media(max-height:620px){{body.baronly .grid-wrap{{gap:4px;padding-block:4px}}body.baronly .tile:not(.zoom){{row-gap:3px}}body.baronly .grid-wrap .tile:not(.zoom) .name{{font-size:14px!important}}body.baronly .grid-wrap .tile:not(.zoom) .gauge{{height:19px!important}}}}
@media(max-height:580px){{body.baronly .grid-wrap{{gap:1px;padding-block:3px}}body.baronly .tile:not(.zoom){{row-gap:2px}}body.baronly .grid-wrap .tile:not(.zoom) .name{{font-size:12px!important}}body.baronly .grid-wrap .tile:not(.zoom) .price{{font-size:14px!important}}body.baronly .grid-wrap .tile:not(.zoom) .gauge{{height:15px!important}}}}
body.baronly .below:not(.zoom) .gauge i{{position:relative}}body.baronly .below:not(.zoom) .gauge i::after{{content:attr(data-p);position:absolute;right:6px;top:50%;transform:translateY(-50%);font-family:'GalmuriMono11','Galmuri11',monospace;font-size:18px;line-height:1;color:#000;white-space:nowrap}}
</style></head><body>
<header><h1 id="ttl" title="눌러서 목표 평균 크게 보기"><svg viewBox="0 0 16 16" style="width:1em;height:1em;display:inline-block;vertical-align:-.12em"><rect width="16" height="16" rx="2" fill="#3a0d14"/><polyline points="2,13 6,8 9,10 14,3" fill="none" stroke="#ff2a3c" stroke-width="2.2"/></svg> 관심종목 <span id="avg" title="목표가까지 남은 거리 평균(막대 평균)"></span></h1><div class="tabs">{"".join(f'<button data-v="{k}">{k}</button>' for k in VIEWS)}<button id="reload" onclick="refreshBoard()" aria-label="새로고침">⟳</button><button id="pct" aria-label="목표 평균 크게">%</button><button id="bar" aria-label="막대만 보기">바</button></div></header>
<div id="bar-live" class="bar-live">실시간 {now[-5:]} 갱신</div>
<div class="note"><b id="live" style="font-weight:normal;color:var(--tgt)">{now} 기준</b> · <span id="vdesc"></span> · <i style="color:var(--tgt)">╍ 목표가</i> · <button id="fold">차트 접기</button> <button id="sync">동기화</button></div>
{err}<div class="grid-wrap">{"".join(tile(d) for d in items)}</div><div class="bar-footer"><button id="baravg" class="baravg" type="button" aria-label="평균 새로고침" title="눌러서 새로고침" onclick="document.getElementById('reload').click()"></button><aside id="bar-leading" class="bar-leading" aria-label="선행지수" hidden><div id="bar-leading-value" class="bar-leading-value"></div><div id="bar-leading-meta" class="bar-leading-meta"></div></aside></div>
<script>
const D={json.dumps({k: v[4] for k, v in VIEWS.items()}, ensure_ascii=False)};
function setV(v){{document.body.dataset.v=v;document.getElementById('vdesc').textContent=D[v];try{{localStorage.v=v}}catch(e){{}}}}
let saved;try{{saved=localStorage.v}}catch(e){{}}
setV(D[saved]?saved:'일');
document.querySelectorAll('.tabs button[data-v]').forEach(b=>b.onclick=()=>setV(b.dataset.v));
try{{localStorage.removeItem('day')}}catch(e){{}}  // 데이 모드 없앰
const RAW='https://raw.githubusercontent.com/{CFG.get("repo", "andrewjhshin-debug/watchlist-board")}/live/m/';
const pad=n=>String(n).padStart(2,'0');
const slot=k=>{{const d=new Date(Date.now()+9*36e5-k*6e4);return d.getUTCFullYear()+pad(d.getUTCMonth()+1)+pad(d.getUTCDate())+pad(d.getUTCHours())+pad(d.getUTCMinutes());}};
const f2=(v,c)=>c==='KRW'?Math.round(v).toLocaleString('en-US'):v.toLocaleString('en-US',{{minimumFractionDigits:2,maximumFractionDigits:2}});
const fs=(v,c)=>c==='KRW'&&v>=1e6?Math.round(v/1e4).toLocaleString('en-US')+'만':f2(v,c);
function getT(el){{try{{const v=localStorage['tg:'+el.dataset.sym];if(v!=null)return JSON.parse(v);}}catch(e){{}}return JSON.parse(el.dataset.tgts0||'[]');}}
function renderT(el){{
  const t=getT(el),c=el.dataset.cur;el.dataset.tgts=JSON.stringify(t);
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
const tiles=()=>[...document.querySelectorAll('.tile[data-sym]')];
function repaint(){{tiles().forEach(el=>{{renderT(el);apply(el.dataset.sym,+el.dataset.p,+el.dataset.pv);}});}}
async function pullT(){{const c=ls('sync');if(!c)return null;
  try{{const r=await fetch(FS+c+'?key='+FK,{{cache:'no-store'}});if(!r.ok)return null;
    const m=JSON.parse((await r.json()).fields.json.stringValue||'{{}}');
    if(Object.keys(m).length){{for(const s in m)ls(s==='_hl'?'hl':'tg:'+s,JSON.stringify(m[s]));repaint();paintHL();}}return m;}}catch(e){{return null;}}}}
async function pushT(){{const c=ls('sync');if(!c)return;const m={{}};tiles().forEach(el=>m[el.dataset.sym]=getT(el));m._hl=getHL();
  try{{await fetch(FS+c+'?key='+FK,{{method:'PATCH',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{fields:{{json:{{stringValue:JSON.stringify(m)}}}}}})}});}}catch(e){{}}}}
async function askSync(force){{if(!force&&(ls('sync')||ls('syncAsked')))return;ls('syncAsked','1');
  const c=prompt('동기화 코드를 입력하세요\\n(PC 다운로드 폴더의 관심종목_동기화코드.txt)',ls('sync')||'');
  if(!c)return;ls('sync',c.trim());const m=await pullT();
  if(m===null){{ls('sync','');alert('코드가 맞지 않아요');}}else if(!Object.keys(m).length)await pushT();  // 처음이면 이 폰 값을 올림
  syncLabel();}}
function syncLabel(){{const b=document.getElementById('sync');if(b)b.textContent=ls('sync')?'동기화됨':'동기화';}}
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
  document.querySelectorAll('.tile[data-sym="'+sym+'"]').forEach(el=>{{
    const c=el.dataset.cur,ch=price-prev;el.dataset.p=price;el.dataset.pv=prev;
    el.querySelector('.price').textContent=f2(price,c);
    if(sym==='ecos:901Y067/I16E')paintBarLeading(el);
    el.classList.toggle('up',ch>=0);el.classList.toggle('down',ch<0);
    el.querySelector('.chg').textContent=(ch>=0?'▲ ':'▼ ')+f2(Math.abs(ch),c)+' ('+(ch>=0?'+':'')+(ch/prev*100).toFixed(2)+'%)';
    el.querySelectorAll('.tgttxt[data-t]').forEach(t=>{{const g=price/+t.dataset.t-1;t.querySelector('b').textContent=(g>=0?'+':'')+(g*100).toFixed(1)+'%';}});
    const ts=JSON.parse(el.dataset.tgts||'[]');delete el.dataset.left;el.classList.remove('lv1','lv2','lv3','lv4','below');
    if(ts.length){{const t=Math.max(...ts),hi=+el.dataset.hi;
      if(price<t){{const dp=Math.min(1,(t-price)/t/.3);el.classList.add('below');el.style.setProperty('--gp',Math.round(75+25*dp)+'%');el.dataset.left=0;
        el.querySelector('.gauge i').style.width=Math.round(dp*100)+'%';el.querySelector('.gauge i').dataset.p=f2(price,c);}}
      else{{const left=hi>t?Math.max(0,Math.min(1,(price-t)/(hi-t))):0;el.dataset.left=left;
        el.querySelector('.gauge i').style.width=Math.round(left*100)+'%';el.classList.add('lv'+(left>=.75?4:left>=.5?3:left>=.25?2:1));
        el.style.setProperty('--lv',['#00ff2a','#22ff00','#55ff00','#88ff00','#ffee00','#ffbb00','#ff8000','#ff5500','#ff2a00','#ff0033'][Math.min(9,Math.floor(left*10))]);}}}}
  }});
  showAvg();
}}
// 제목을 누르면 화면은 그대로 두고 가운데에 평균 % 만 크게. 아무 데나 누르면 닫힘
function showPct(){{const a=document.getElementById('avg');if(!a.textContent)return;
  const d=document.createElement('div');d.className='avgpop';
  d.innerHTML='<b style="color:'+a.style.color+'">'+a.textContent+'</b>';
  d.onclick=()=>history.back();document.body.appendChild(d);history.pushState({{pop:1}},'');}}
document.getElementById('ttl').onclick=showPct;document.getElementById('pct').onclick=showPct;
addEventListener('popstate',()=>{{document.querySelectorAll('.tile.zoom').forEach(e=>e.classList.remove('zoom'));
  document.querySelectorAll('.avgpop').forEach(d=>d.remove());}});
// 목표 평균 색 10단계(10% 단위): 0~40% 초록 4단계(낮을수록 진함) → 노랑 → 주황 → 빨강
const AC=['#00ff3c','#3dff5a','#7dff6e','#b4ff7a','#e6f04a','#ffd23f','#ffaa33','#ff8a3c','#ff6a50','#ff4d6d'];
// 목표 평균: 목표가 있는 종목들 막대 값(0~100%) 평균(BATL·바 전용 종목·선행지수·WTI·나스닥 종합·코스피·코스닥 제외). 0=목표 근처(초록) ~ 100=멀다(빨강)
function showAvg(){{const v=tiles().filter(e=>!e.dataset.barOnly&&!e.dataset.sym.startsWith('ecos:')&&!['BATL','CL=F','^IXIC','^KS11','^KQ11'].includes(e.dataset.sym)).map(e=>e.dataset.left).filter(x=>x!==undefined).map(Number),a=document.getElementById('avg');
  if(!a)return;if(!v.length){{a.textContent='';return;}}const m=v.reduce((x,y)=>x+y,0)/v.length;
  a.textContent=Math.round(m*100)+'%';a.style.color=AC[Math.min(9,Math.floor(m*10))];
  const b=document.getElementById('baravg');if(b){{b.textContent=a.textContent;b.style.color=a.style.color;}}}}
const stamp=t=>{{const n=document.getElementById('live');if(n)n.textContent='실시간 '+t;const b=document.getElementById('bar-live');if(b)b.textContent='실시간 '+t.slice(0,5)+' 갱신';}};
let lastSlot='{datetime.now(KST):%Y%m%d%H%M}';
async function pollLive(force=false){{for(let k=force?0:1;k<=6;k++){{const sl=slot(k);if(sl<lastSlot)return false;try{{const r=await fetch(RAW+sl+'.json'+(force?'?t='+Date.now():''),{{cache:'no-store'}});
  if(r.ok){{lastSlot=sl;const j=await r.json();for(const x in j.q)if(!x.startsWith('upbit:'))apply(x,j.q[x][0],j.q[x][1]);stamp(j.t);return true;}}}}catch(e){{}}}}return false;}}
const UP=[...document.querySelectorAll('.tile[data-sym^="upbit:"]')].map(e=>e.dataset.sym.slice(6));
async function pollUpbit(){{if(!UP.length)return false;try{{const r=await fetch('https://api.upbit.com/v1/ticker?markets='+UP.join(','),{{cache:'no-store'}});if(!r.ok)return false;
  const rows=await r.json();for(const x of rows)apply('upbit:'+x.market,x.trade_price,x.prev_closing_price);return rows.length>0;}}catch(e){{return false;}}}}
let refreshJob=null,refreshAnnounce=false,refreshToastTimer=null;
function showRefreshToast(message){{
  let toast=document.querySelector('.toast[data-refresh]');
  if(!toast){{toast=document.createElement('div');toast.className='toast';toast.dataset.refresh='1';toast.setAttribute('role','status');toast.setAttribute('aria-live','polite');document.body.appendChild(toast);}}
  toast.textContent=message;clearTimeout(refreshToastTimer);
  refreshToastTimer=setTimeout(()=>toast.remove(),1800);
}}
async function refreshCharts(){{
  try{{
    const url=new URL(location.href);url.searchParams.set('_refresh',Date.now());
    const response=await fetch(url,{{cache:'no-store'}});if(!response.ok)return false;
    const next=new DOMParser().parseFromString(await response.text(),'text/html');
    const incoming=[...next.querySelectorAll('.tile[data-sym]')];
    if(!next.querySelector('#baravg')||!incoming.length)return false;
    const current=new Map(tiles().map(el=>[el.dataset.sym,el]));
    const board=document.querySelector('.grid-wrap');
    for(const fresh of incoming){{
      const sym=fresh.dataset.sym;let el=current.get(sym);
      if(!el){{el=fresh;board.appendChild(el);current.set(sym,el);}}
      else{{
        for(const key of ['hi','tgts0'])if(fresh.dataset[key]!==undefined)el.dataset[key]=fresh.dataset[key];
        const name=el.querySelector('.name'),nextName=fresh.querySelector('.name');
        if(name&&nextName&&name.innerHTML!==nextName.innerHTML)name.replaceChildren(...nextName.childNodes);
        for(const view of [...fresh.querySelectorAll('.view')]){{
          const old=el.querySelector('.view[data-v="'+view.dataset.v+'"]');
          if(old){{if(old.innerHTML!==view.innerHTML)old.replaceChildren(...view.childNodes);}}
          else el.insertBefore(view,el.querySelector('.gauge'));
        }}
        if(sym.startsWith('ecos:')){{el.dataset.p=fresh.dataset.p;el.dataset.pv=fresh.dataset.pv;}}
      }}
      renderT(el);apply(sym,+el.dataset.p,+el.dataset.pv);
    }}
    paintHL();return true;
  }}catch(e){{return false;}}
}}
function refreshBoard(announce=true){{
  refreshAnnounce=refreshAnnounce||announce;
  if(refreshJob)return refreshJob;
  refreshJob=(async()=>{{
    const results=await Promise.allSettled([refreshCharts(),pollLive(true),pollUpbit(),pullT()]);
    const ok=results.slice(0,3).some(r=>r.status==='fulfilled'&&r.value);
    if(refreshAnnounce)showRefreshToast(ok?'새로고침했습니다':'새로고침하지 못했습니다');
    return ok;
  }})().finally(()=>{{refreshJob=null;refreshAnnounce=false;}});
  return refreshJob;
}}

// 차트 접기: 휴대폰은 처음엔 접힌 상태(12종목이 한 화면에), 선택은 기억
const fold=document.getElementById('fold');
function setF(on){{document.body.classList.toggle('nochart',on);fold.textContent=on?'차트 펴기':'차트 접기';ls('fold',on?'1':'0');}}
fold.onclick=()=>setF(!document.body.classList.contains('nochart'));
setF(innerWidth<601&&ls('fold')!=='0');
function fitBarViewport(){{const h=Math.floor(window.visualViewport?.height||innerHeight);if(h>0)document.body.style.setProperty('--bar-viewport',h+'px');}}
addEventListener('resize',fitBarViewport);window.visualViewport?.addEventListener('resize',fitBarViewport);
const barB=document.getElementById('bar');
function setB(on){{fitBarViewport();document.body.classList.toggle('baronly',on);barB.style.color=on?'var(--low)':'';barB.style.borderColor=on?'var(--low)':'';ls('bar',on?'1':'0');}}
barB.onclick=()=>setB(!document.body.classList.contains('baronly'));setB(ls('bar')==='1');
document.getElementById('sync').onclick=()=>askSync(true);syncLabel();
// 노란 테두리: 카드를 두 번 톡톡(더블탭·더블클릭)하면 켜고 끔, 한 번이면 차트 크게. 폰끼리 동기화
function getHL(){{try{{return JSON.parse(ls('hl')||'[]');}}catch(e){{return [];}}}}
function paintHL(){{const h=getHL();tiles().forEach(el=>el.classList.toggle('hl',h.includes(el.dataset.sym)));}}
function toggleHL(el){{const h=getHL(),s=el.dataset.sym,i=h.indexOf(s);i<0?h.push(s):h.splice(i,1);ls('hl',JSON.stringify(h));paintHL();pushT();
  if(navigator.vibrate)navigator.vibrate(30);}}
let tapT=null,tapEl=null;
function tap(el){{if(el.classList.contains('zoom')){{history.back();return;}}
  if(document.body.classList.contains('baronly')){{clearTimeout(tapT);tapT=null;el.classList.add('zoom');history.pushState({{pop:1}},'');return;}}
  if(tapT&&tapEl===el){{clearTimeout(tapT);tapT=null;toggleHL(el);return;}}  // 두 번째 탭 → 테두리
  clearTimeout(tapT);tapEl=el;tapT=setTimeout(()=>{{tapT=null;el.classList.add('zoom');history.pushState({{pop:1}},'');}},300);}}  // 한 번 → 잠깐 기다렸다 펼침
paintHL();
repaint();pullT();setInterval(pullT,60000);  // 다른 폰에서 바꾼 목표가를 1분마다 가져옴
pollLive();pollUpbit();setInterval(pollLive,30000);setInterval(pollUpbit,5000);
try{{if(sessionStorage.rl){{sessionStorage.removeItem('rl');showRefreshToast('새로고침했습니다');}}}}catch(e){{}}
setInterval(()=>refreshBoard(false),{CFG["refresh_min"] * 60000});
const loadedAt=Date.now();
document.addEventListener('visibilitychange',()=>{{if(document.visibilityState==='visible'&&Date.now()-loadedAt>60000)refreshBoard(false);}});
addEventListener('pageshow',e=>{{if(e.persisted)refreshBoard(false);}});
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
    render(items, errors)
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
