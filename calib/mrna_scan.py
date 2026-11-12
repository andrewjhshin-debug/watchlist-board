"""모더나형: 월봉으로 거품(급등)→폭락(좌절)→다시 크게 반등(정상화·2차 상승) 끝까지 돈 종목 찾기."""
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, r"C:\Users\user\Downloads\watchlist-chart")
import watch

US = """MRNA 모더나,BNTX 바이오엔텍,NVAX 노바백스,ZM 줌,PTON 펠로톤,DOCU 도큐사인,ROKU 로쿠,TDOC 텔라독,PLUG 플러그파워,SPCE 버진갤럭틱,
LCID 루시드,RIVN 리비안,NIO 니오,XPEV 샤오펑,LI 리오토,CVNA 카바나,AFRM 어펌,UPST 업스타트,XYZ 블록,SHOP 쇼피파이,SE 씨,COIN 코인베이스,
HOOD 로빈후드,PLTR 팔란티어,SNOW 스노우,NET 클라우드플레어,ZS 지스케일러,DDOG 데이터독,MDB 몽고DB,TWLO 트윌리오,U 유니티,RBLX 로블록스,
ETSY 엣시,CHWY 츄이,W 웨이페어,FUBO 푸보,AMC AMC,GME 게임스탑,SOFI 소파이,OPEN 오픈도어,Z 질로우,BYND 비욘드미트,CRSP 크리스퍼,
NTLA 인텔리아,BEAM 빔,PACB 팩바이오,ILMN 일루미나,EXAS 이그젝트,QS 퀀텀스케이프,CHPT 차지포인트,ENPH 엔페이즈,SEDG 솔라엣지,RUN 선런,
FSLR 퍼스트솔라,TSLA 테슬라,ARKK 아크,BILI 빌리빌리,BABA 알리바바,JD 징둥,PDD 핀둬둬,TAL TAL,EDU 신동방,DKNG 드래프트킹스,PENN 펜,
LMND 레모네이드,ROOT 루트,MARA 마라톤,RIOT 라이엇,MSTR 마이크로스트래티지,TLRY 틸레이,CGC 캐노피,SNAP 스냅,PINS 핀터레스트,
META 메타,NFLX 넷플릭스,PYPL 페이팔,INTC 인텔,MU 마이크론,AMD AMD,NVDA 엔비디아,SMCI 슈퍼마이크로,CELH 셀시어스,DXCM 덱스컴,
TTD 트레이드데스크,OKTA 옥타,ZI 줌인포,FVRR 파이버,BIGC 빅커머스,PATH 유아이패스,AI C3AI,IONQ 아이온큐,RGTI 리게티,QBTS 디웨이브,
ASTS AST스페이스,RKLB 로켓랩,ACHR 아처,JOBY 조비,SOUN 사운드하운드,APP 앱러빈,CAVA 카바,DASH 도어대시,ABNB 에어비앤비,UBER 우버,
LYFT 리프트,CRWD 크라우드,PANW 팔로알토,SQM SQM,ALB 앨버말,LAC 리튬아메리카,MP MP머티리얼즈,CLF 클리블랜드,X US스틸,FCX 프리포트,
OXY 옥시,DVN 데본,APA APA,AA 알코아,NEM 뉴몬트,GDX 금광주,SLV 은,URA 우라늄,CCJ 카메코,SMR 뉴스케일,OKLO 오클로,
BTC-USD 비트코인,ETH-USD 이더리움,SOL-USD 솔라나,DOGE-USD 도지,XRP-USD 리플,ADA-USD 에이다,AVAX-USD 아발란체,
BA 보잉,CCL 카니발,NCLH 노르웨이크루즈,AAL 아메리칸항공,DAL 델타,EXPE 익스피디아,NKLA 니콜라,WBD 워너,PARA 파라마운트,
VRTX 버텍스,REGN 리제네론,BIIB 바이오젠,GILD 길리어드,LLY 릴리,NVO 노보,HIMS 힘스,VKTX 바이킹,SRPT 사렙타"""
KR = """005930.KS 삼성전자,000660.KS 하이닉스,068270.KS 셀트리온,086520.KQ 에코프로,247540.KQ 에코프로비엠,003670.KS 포스코퓨처엠,
373220.KS LG엔솔,035720.KS 카카오,035420.KS 네이버,036570.KS 엔씨,096530.KQ 씨젠,019170.KS 신풍제약,011200.KS HMM,011000.KS 진원생명과학,
196170.KQ 알테오젠,352820.KS 하이브,112040.KQ 위메이드,293490.KQ 카카오게임즈,259960.KS 크래프톤,336260.KS 두산퓨얼셀,009830.KS 한화솔루션,
207940.KS 삼성바이오,302440.KS SK바이오사이언스,066970.KQ 엘앤에프,278280.KQ 천보,028300.KQ HLB,006400.KS 삼성SDI,051910.KS LG화학,
005490.KS 포스코홀딩스,042700.KS 한미반도체,012450.KS 한화에어로,064350.KS 현대로템,042660.KS 한화오션,010140.KS 삼성중공업,329180.KS HD현대중,
267260.KS HD현대일렉,010120.KS LS일렉,034020.KS 두산에너빌,015760.KS 한전,005380.KS 현대차,000270.KS 기아,011070.KS LG이노텍,
009150.KS 삼성전기,058470.KQ 리노공업,240810.KQ 원익IPS,007660.KS 이수페타시스,041510.KQ 에스엠,035900.KQ JYP,251270.KS 넷마블,
263750.KQ 펄어비스,095660.KQ 네오위즈,078340.KQ 컴투스,326030.KS SK바이오팜,000100.KS 유한양행,128940.KS 한미약품,145020.KQ 휴젤,
214150.KQ 클래시스,141080.KQ 리가켐바이오,298380.KQ 에이비엘바이오,086900.KQ 메디톡스,091990.KQ 셀트리온헬스케어,950160.KQ 코오롱티슈진,
039030.KQ 이오테크닉스,403870.KQ HPSP,357780.KQ 솔브레인,005070.KS 코스모신소재,020150.KS 롯데에너지머티리얼즈,010060.KS OCI홀딩스,
^KS11 코스피,^KQ11 코스닥"""
C = [x.strip().split(" ", 1) for x in (US + "," + KR).replace("\n", "").split(",") if x.strip()]


def scan(item):
    sym, name = item
    try:
        q = watch.get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1mo&range=max")["chart"]["result"][0]
        tc = [(t, v) for t, v in zip(q["timestamp"], q["indicators"]["quote"][0]["close"]) if v]
        tc = [x for x in tc if x[0] > datetime(2015, 1, 1).timestamp()]
        if len(tc) < 36:
            return None
        c = [v for _, v in tc]
        best = None
        # 고점 후보: 앞뒤 12개월 중 최고인 달들
        for ip in range(6, len(c) - 12):
            if c[ip] < max(c[max(0, ip - 12):ip + 13]):
                continue
            pre = min(c[max(0, ip - 48):ip])               # 거품 전 저점(4년 안)
            it = min(range(ip, len(c)), key=lambda i: c[i])  # 고점 이후 최저(좌절)
            run, dd, rec = c[ip] / pre, 1 - c[it] / c[ip], c[-1] / c[it]
            if run >= 3 and dd >= .65 and it - ip >= 9 and rec >= 2 and it < len(c) - 3:
                sc = (run, dd, rec, ip, it)
                if not best or dd * rec > best[1] * best[2]:
                    best = sc
        if not best:
            return None
        run, dd, rec, ip, it = best
        f = lambda i: datetime.fromtimestamp(tc[i][0]).strftime("%y.%m")
        return (name, sym, run, f(ip), dd, f(it), rec, c[-1] / c[ip])
    except Exception:
        return None


if __name__ == "__main__":
    with ThreadPoolExecutor(8) as ex:
        rows = [r for r in ex.map(scan, C) if r]
    rows.sort(key=lambda r: -r[6])
    print(f"후보 {len(rows)}개 / 전체 {len(C)}")
    print("종목 | 거품(배) 고점 | 폭락 좌절 | 좌절 이후 반등(배) | 지금/옛고점")
    for name, sym, run, fp, dd, ft, rec, nowpk in rows:
        print(f"{name}({sym}) | x{run:.1f} {fp} | -{dd*100:.0f}% {ft} | x{rec:.1f} | {nowpk*100:.0f}%")
