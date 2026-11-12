import sys
sys.path.insert(0, r"C:\Users\user\Downloads\watchlist-chart")
import watch


def corr(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    s = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    sa = sum((x - ma) ** 2 for x in a) ** .5
    sb = sum((y - mb) ** 2 for y in b) ** .5
    return s / (sa * sb) if sa and sb else -1


def best(c, lo, hi):
    b = (-1, 0, 0)
    for n in range(26, len(c) + 1, 4):
        seg = c[-n:]
        for k in range(lo, hi + 1, 2):
            te = k / 100
            r = corr(seg, [watch.mkf(i / (n - 1) * te) for i in range(n)])
            if r > b[0]:
                b = (r, n, te)
    return b


US = """NVDA 엔비디아,TSM TSMC,AVGO 브로드컴,AAPL 애플,MSFT MS,GOOGL 구글,AMZN 아마존,META 메타,NFLX 넷플릭스,ORCL 오라클,PLTR 팔란티어,CRM 세일즈포스,ADBE 어도비,NOW 서비스나우,CRWD 크라우드,PANW 팔로알토,SNOW 스노우,SHOP 쇼피파이,UBER 우버,ABNB 에어비앤비,
QCOM 퀄컴,TXN TI,ADI 아날로그,MRVL 마벨,KLAC KLA,CDNS 케이던스,SNPS 시놉시스,ANET 아리스타,DELL 델,HPQ HP,IBM IBM,CSCO 시스코,
VST 비스트라,CEG 컨스텔레이션,GEV GE버노바,NEE 넥스트에라,ETN 이튼,PWR 콴타,VRT 버티브,CCJ 카메코,
LLY 릴리,NVO 노보,UNH 유나이티드,JNJ J&J,ABBV 애브비,MRK 머크,PFE 화이자,AMGN 암젠,ISRG 인튜이티브,TMO 써모,
JPM JP모건,GS 골드만,MS 모건,BAC BoA,WFC 웰스,BRK-B 버크셔,V 비자,MA 마스터,AXP 아멕스,BLK 블랙록,SCHW 슈왑,HOOD 로빈후드,COIN 코인베이스,PYPL 페이팔,
XOM 엑슨,CVX 셰브론,COP 코노코,OXY 옥시,SLB 슐럼,
LMT 록히드,RTX RTX,NOC 노스롭,GD 제너럴다이,BA 보잉,GE GE,CAT 캐터필러,DE 디어,HON 하니웰,RKLB 로켓랩,
COST 코스트코,WMT 월마트,HD 홈디포,MCD 맥도날드,SBUX 스타벅스,NKE 나이키,KO 코카콜라,PEP 펩시,PG P&G,PM 필립모리스,DIS 디즈니,TSLA 테슬라,F 포드,GM GM,
LIN 린데,FCX 프리포트,NEM 뉴몬트,
SPY S&P,QQQ 나스닥100,IWM 러셀,GLD 금,SLV 은,USO 원유,TLT 미국채,EWY 한국,EWJ 일본,FXI 중국,INDA 인도,EEM 신흥국,
BTC-USD 비트코인,ETH-USD 이더리움,SOL-USD 솔라나,XRP-USD XRP"""
KR = """005930.KS 삼성전자,000660.KS 하이닉스,373220.KS LG엔솔,207940.KS 삼바,005380.KS 현대차,000270.KS 기아,068270.KS 셀트리온,105560.KS KB금융,055550.KS 신한,086790.KS 하나,
035420.KS 네이버,035720.KS 카카오,012450.KS 한화에어로,079550.KS LIG넥스원,064350.KS 현대로템,329180.KS HD현대중,042660.KS 한화오션,010140.KS 삼성중공업,
267260.KS HD현대일렉,010120.KS LS일렉,298040.KS 효성중공업,042700.KS 한미반도체,034020.KS 두산에너빌,009540.KS HD한국조선,
005490.KS 포스코홀딩스,003670.KS 포스코퓨처엠,086520.KQ 에코프로,247540.KQ 에코프로비엠,006400.KS 삼성SDI,051910.KS LG화학,
028260.KS 삼성물산,000810.KS 삼성화재,032830.KS 삼성생명,015760.KS 한전,017670.KS SKT,030200.KS KT,
352820.KS 하이브,041510.KQ 에스엠,035900.KQ JYP,251270.KS 넷마블,036570.KS 엔씨,259960.KS 크래프톤,
000100.KS 유한양행,196170.KQ 알테오젠,326030.KS SK바이오팜,
011200.KS HMM,003490.KS 대한항공,090430.KS 아모레,051900.KS LG생건,097950.KS CJ제일제당,139480.KS 이마트,
000720.KS 현대건설,047050.KS 포스코인터,011070.KS LG이노텍,009150.KS 삼성전기,018260.KS 삼성SDS,
^KS11 코스피,^KQ11 코스닥"""
C = [x.strip().split(" ", 1) for x in (US + "," + KR).replace("\n", "").split(",") if x.strip()]
rows = []
for s, n in C:
    try:
        q = watch.get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval=1wk&range=5y")["chart"]["result"][0]
        c = [v for v in q["indicators"]["quote"][0]["close"] if v]
        if len(c) < 60:
            continue
        e = best(c, 20, 52)      # 이륙~1차 현금화
        m = best(c, 54, 86)      # 중간
        l = best(c, 88, 96)      # 좌절
        rows.append((n, e, m, l, c[-1] / max(c) - 1, c[-1] / min(c)))
    except Exception as ex:
        print(n, "fail", ex, file=sys.stderr)
print(f"전체 {len(rows)}개")
print()
print("[이륙·1차 현금화] 앞 구간 90%↑, 다른 구간보다 2점 이상")
for n, e, m, l, dd, mul in sorted(rows, key=lambda r: -(r[1][0] - max(r[2][0], r[3][0]))):
    if e[0] >= .90 and e[0] - max(m[0], l[0]) >= .02:
        st = next(t for x, t in watch.STAGES if e[2] < x)
        print(f"{st:8s} {n:10s} {e[0]*100:.0f}% (다른 구간 {max(m[0],l[0])*100:.0f}%)  고점대비 {dd*100:+.0f}%  5년 저점의 {mul:.1f}배")
print()
print("[좌절] 좌절 구간 85%↑, 다른 구간보다 잘 맞음")
for n, e, m, l, dd, mul in sorted(rows, key=lambda r: -r[3][0]):
    if l[0] >= .85 and l[0] - max(e[0], m[0]) >= .0:
        print(f"좌절     {n:10s} {l[0]*100:.0f}% (다른 구간 {max(e[0],m[0])*100:.0f}%)  고점대비 {dd*100:+.0f}%  5년 저점의 {mul:.1f}배")
