import json, math, numpy as np
E = json.load(open("episodes_raw.json"))
E = [e for e in E if -1.5 < e["r24"] < 4 and e["sig"] < 2.5]
y = np.array([e["d"] for e in E]); T = np.array([e["T"] for e in E]); g = np.array([e["s"] for e in E])
same = g[:, None] == g[None, :]
def since(p, m):
    k = 0
    while m - 2 - k >= 0 and p[m - 2 - k] == p[m - 1]: k += 1
    return k
dp = lambda p: np.median(np.abs(np.exp(p) - np.exp(y))) * 100
W = np.array((.5, .5, 3, 1, 3))
for m in (3, 5, 7, 10, 13, 18):
    X = np.array([[e["r24"], e["sig"], math.log(e["path"][m - 1]), since(e["path"], m) / m, math.log(e["cl"][m - 1] / e["path"][m - 1])] for e in E])
    Z = (X - X.mean(0)) / X.std(0); cur = X[:, 2]
    D = ((Z[:, None, :] - Z[None, :, :]) ** 2 * W).sum(2); D[same] = 1e9
    nn = np.argsort(D, 1)[:, :40]
    lowm = np.array([m - since(e["path"], m) for e in E]); truep = T <= m
    medT = np.median(T[nn], 1); pin = np.mean(T[nn] <= m, 1)  # 이웃 중 이미 바닥 친 비율
    row = f"[{m}개월] 실제 지남 {truep.mean():.0%}"
    for th in (.5, .6, .7):
        passed = pin >= th
        pd_ = np.where(passed, cur, np.minimum(np.array([np.median(y[nn[i]][T[nn[i]] > m]) if (T[nn[i]] > m).sum() >= 5 else cur[i] for i in range(len(E))]), cur))
        pT = np.where(passed, lowm, np.array([np.median(T[nn[i]][T[nn[i]] > m]) if (T[nn[i]] > m).sum() >= 5 else m + 2 for i in range(len(E))]))
        row += f" | 기준 {th}: 깊이 {dp(pd_):.1f} 기간 {np.median(np.abs(pT-T)):.1f} 판정 정확도 {np.mean(passed==truep):.0%} 지남 정밀도 {np.mean(truep[passed]) if passed.any() else 0:.0%} ({passed.mean():.0%} 해당)"
    pd0 = np.minimum(np.median(y[nn], 1), cur); pT0 = np.maximum(medT, lowm)
    row += f" | 단순: 깊이 {dp(pd0):.1f} 기간 {np.median(np.abs(pT0-T)):.1f}"
    print(row)
