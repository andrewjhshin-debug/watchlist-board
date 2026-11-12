"""과거 급락 사례 수집: 월봉 전체 이력 → (고점, 그 뒤 최저) 에피소드와 특징값."""
import sys, json, math, urllib.request
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, r"C:\Users\user\Downloads\watchlist-chart"); sys.path.insert(0, ".")
import watch
src = open("early.py", encoding="utf-8").read(); ns = {}
exec(src[src.index('US = """'):src.index("rows = []")].replace("watch.", "_w."), {"_w": watch}, ns)
from mrna_scan import C as C2
MORE = """^IXIC ^SOX ^KS11 ^KQ11 ^N225 ^GSPC ^HSI 000001.SS ^NDX ^RUT ^TWII ^GDAXI ^STOXX50E ^BVSP ^NSEI
INTC GLW NOK ERIC VIAV JNPR CIEN EXTR XRX T VZ SIRI AKAM EBAY BKNG EA ADSK NTAP STX WDC SWKS QRVO ON MCHP TER AMKR COHR LITE UCTT ACLS FORM ONTO CAMT
PLUG FCEL BLDP ENPH RUN SPWR FSLR NIO XPEV LI RIVN LCID QS CHPT BYND SPCE GME BB TLRY CGC ACB MARA HUT CLSK HOOD SOFI UPST LMND RBLX U DDOG ZS MDB TEAM ZM PTON ROKU PINS SNAP TDOC DOCU FVRR ETSY W CVNA OPEN Z RDFN
BIDU BABA JD PDD TCEHY NTES SE MELI GRAB CPNG SMCI ARKK ARKG TAN ICLN LIT URA XBI IBB SMH SOXX KWEB FXI EWY EWJ EWZ GDX GDXJ SLV USO UNG XLE XLF KRE XHB ITB
005930.KS 000660.KS 035420.KS 035720.KS 051910.KS 006400.KS 373220.KS 207940.KS 068270.KS 005380.KS 000270.KS 012330.KS 028260.KS 066570.KS 003670.KS 247540.KQ 086520.KQ 091990.KQ 196170.KQ 028300.KQ 041510.KQ 035900.KQ 352820.KS 259960.KS 036570.KS 251270.KS 293490.KQ 112040.KQ 263750.KQ 042700.KS 010140.KS 009540.KS 010620.KS 042660.KS 011200.KS 034020.KS 010120.KS 267260.KS 012450.KS 047810.KS 079550.KS 064350.KS 011070.KS 009150.KS 058470.KQ 240810.KQ 007660.KS 000100.KS 128940.KS 326030.KS 011170.KS 010950.KS 096770.KS 005490.KS 004020.KS""".split()
syms = sorted(set([s for s, _ in ns["C"]] + [s for s, _ in C2] + [s for s, _ in watch.HA] + [s for s, _, _ in watch.EXTRA] + MORE) - set(watch.LEV) - {"SOXL", "SOXS"})
CUT = 1719792000  # 2024-07-01: 이 뒤 고점은 아직 진행 중이라 제외


def eps(sym):
    try:
        q = watch.get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?interval=1mo&range=max")["chart"]["result"][0]
        m = [(t, v) for t, v in zip(q["timestamp"], q["indicators"]["quote"][0]["close"]) if v and v > 0]
    except Exception:
        return []
    out, n, i = [], len(m), 24
    while i < n - 12:
        p = m[i][1]
        # 고점: 지난 36개월 최고이면서, 이후 회복(고점 재돌파) 전에 25% 넘게 빠짐
        if p < max(v for _, v in m[max(0, i - 36):i + 1]) or m[i][0] > CUT:
            i += 1; continue
        j = next((k for k in range(i + 1, n) if m[k][1] > p), n)  # 고점 재돌파 달
        seg = m[i:min(j, i + 121)]  # 최대 10년
        b = min(range(len(seg)), key=lambda k: seg[k][1])
        if b == 0 or seg[b][1] / p > .75 or (j == n and i + b > n - 7):  # 얕거나, 아직 바닥 확인 전
            i += 1; continue
        r = [math.log(m[k][1] / m[k - 1][1]) for k in range(max(1, i - 35), i + 1)]
        mu = sum(r) / len(r)
        path, cl, lo = [], [], p
        for k in range(1, 37):
            if i + k < n: lo = min(lo, m[i + k][1])
            path.append(round(lo / p, 4)); cl.append(round(m[min(i + k, n - 1)][1] / p, 4))
        out.append({"s": sym, "t": m[i][0], "r24": round(math.log(p / m[i - 24][1]), 4), "r12": round(math.log(p / m[i - 12][1]), 4),
                    "sig": round((sum((x - mu) ** 2 for x in r) / len(r) * 12) ** .5, 4), "d": round(math.log(seg[b][1] / p), 4), "T": b, "path": path, "cl": cl})
        i += b  # 바닥 뒤부터 다시
    return out


with ThreadPoolExecutor(8) as ex:
    E = [e for r in ex.map(eps, syms) for e in r]
json.dump(E, open("episodes_raw.json", "w"))
print(len(syms), "종목", len(E), "사례", "| 급등(2년 +100%↑)", sum(1 for e in E if e["r24"] >= math.log(2)))
