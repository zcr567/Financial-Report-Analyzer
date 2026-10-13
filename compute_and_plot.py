# -*- coding: utf-8 -*-
"""
脆弱性指标计算与绘图
====================

依据《项目计划书》第六部分「会计规则与异常信号体系」提出的 5 项脆弱性指标，
对已提取的财报数据（财报数据提取.csv）进行指标计算、评分，并逐份生成图表。

五项指标及评分规则（每项 0—2 分，总分 0—10 分，分数越高脆弱性越强）：
    1. 增长失速     ：营收同比增速 - 样本中位数营收同比增速
                      0分≥0；1分 -10%~0；2分 <-10%
    2. 现金背离     ：(净利润 - 经营现金流) / 平均总资产
                      0分 净利润为正且比率≤0；1分 净利润为正且0<比率≤5%，或亏损但CFO为正；
                      2分 比率>5%，或净利润与CFO同时为负
    3. 回款压力     ：(应收账款+合同资产+存货)/营业收入×365，取同比天数变化
                      0分 ≤0天；1分 0~30天；2分 >30天
    4. 利润质量与减值：非经常性损益占比；商誉/max(净资产, 1%×营业收入)
                      0分 非经常性≤20%且商誉≤10%；1分 任一在20~50%/10~30%；
                      2分 非经常性>50%或商誉>30%
    5. 估值预期压力 ：PS_ttm / 样本中位数PS_ttm（需市值，财报内无）

数据局限（如实标注，不编造）：
    - 指标 1/3 需要「上年同期」数据，仅金蝶（3 个年度）可算同比；
      商汤、广联达仅单年报告，同比无法计算。
    - 指标 1 的「样本中位数」仅有金蝶两年同比值（n=2），中位数为近似。
    - 指标 5 需要市值（PS = 市值/营业收入），财报内不包含，标记为「需外部行情数据」。
    - 港股（金蝶/商汤）IFRS 不单独披露非经常性损益，按 0 处理并注明。

输出：
    - 脆弱性指标汇总.csv   —— 逐报告逐指标的原始值、得分、总分
    - 脆弱性评分_<公司>_<年份>.png —— 每份报告一张评分卡图
"""

import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")  # 无界面后端
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun"]
plt.rcParams["axes.unicode_minus"] = False

BASE = r"D:\python\Financial-Report-Analyzer"
CSV_PATH = os.path.join(BASE, "财报数据提取.csv")
OUT_CSV = os.path.join(BASE, "脆弱性指标汇总.csv")

FIELDS = ["营业收入", "净利润", "经营活动产生的现金流量净额", "总资产",
          "所有者权益", "应收账款", "合同资产", "存货", "商誉", "非经常性损益"]

REPORTS = [
    ("金蝶国际", "00268.HK", 2023),
    ("金蝶国际", "00268.HK", 2024),
    ("金蝶国际", "00268.HK", 2025),
    ("商汤-W", "00020.HK", 2023),
    ("广联达", "002410.SZ", 2023),
]

IND_NAMES = ["增长失速", "现金背离", "回款压力", "利润质量与减值压力", "估值预期压力"]

# 状态色（score：0健康 / 1预警 / 2风险 / None数据不足）
COLOR_GOOD = "#2E8540"     # 绿
COLOR_WARN = "#C98A00"     # 琥珀
COLOR_RISK = "#C0392B"     # 红
COLOR_NA   = "#9AA0A6"     # 灰

RISK_LEVELS = [(0, 2, "低"), (3, 5, "中"), (6, 8, "高"), (9, 10, "很高")]


# ---------------------------------------------------------------------------
# 数据读取
# ---------------------------------------------------------------------------
def load_fields():
    df = pd.read_csv(CSV_PATH)
    df["year"] = df["期间结束"].astype(str).str[:4].astype(int)

    def get(company, year, field):
        r = df[(df["公司"] == company) & (df["year"] == year) & (df["字段"] == field)]
        if len(r) == 0:
            return None
        v = r["数值"].iloc[0]
        return None if pd.isna(v) else float(v)

    data = {}
    for company, code, year in REPORTS:
        data[(company, year)] = {f: get(company, year, f) for f in FIELDS}
    return data


# ---------------------------------------------------------------------------
# 指标计算与评分
# ---------------------------------------------------------------------------
def score_growth(yoy_diff):
    if yoy_diff is None:
        return None
    if yoy_diff >= 0:
        return 0
    if yoy_diff >= -0.10:
        return 1
    return 2


def score_cash(net, cfo, ratio):
    if net is None or cfo is None or ratio is None:
        return None
    if net > 0:
        if ratio <= 0:
            return 0
        if ratio <= 0.05:
            return 1
        return 2
    # 亏损情形，结合现金流方向
    if cfo > 0:
        return 1          # 亏损但经营现金流为正
    return 2              # 净利润与经营现金流同时为负（或亏损且现金流非正）


def score_collection(delta_days):
    if delta_days is None:
        return None
    if delta_days <= 0:
        return 0
    if delta_days <= 30:
        return 1
    return 2


def score_quality(nr_ratio, gw_ratio):
    if nr_ratio is None and gw_ratio is None:
        return None
    nr_ratio = nr_ratio if nr_ratio is not None else 0.0
    gw_ratio = gw_ratio if gw_ratio is not None else 0.0
    nr_band = 0 if nr_ratio <= 0.20 else (1 if nr_ratio <= 0.50 else 2)
    gw_band = 0 if gw_ratio <= 0.10 else (1 if gw_ratio <= 0.30 else 2)
    return max(nr_band, gw_band)


def risk_level(total):
    for lo, hi, name in RISK_LEVELS:
        if lo <= total <= hi:
            return name
    return "很高" if total > 10 else "低"


def pct(x):
    return f"{x * 100:.2f}%"


def compute(data):
    # 先算营收同比增速，再取样本中位数
    yoy = {}
    for (company, year), f in data.items():
        rev = f["营业收入"]
        prev = data.get((company, year - 1), {}).get("营业收入")
        yoy[(company, year)] = ((rev - prev) / prev) if (rev and prev) else None

    yoy_vals = [v for v in yoy.values() if v is not None]
    median_yoy = float(np.median(yoy_vals)) if yoy_vals else None

    results = []
    for company, code, year in REPORTS:
        f = data[(company, year)]
        rev = f["营业收入"]; net = f["净利润"]; cfo = f["经营活动产生的现金流量净额"]
        assets = f["总资产"]; equity = f["所有者权益"]
        ar = f["应收账款"]; contract = f["合同资产"]; inv = f["存货"]
        goodwill = f["商誉"]; nr = f["非经常性损益"]

        # ---- 指标1 增长失速 ----
        yv = yoy[(company, year)]
        g1 = score_growth((yv - median_yoy) if (yv is not None and median_yoy is not None) else None)

        # ---- 指标2 现金背离 ----
        prev_assets = data.get((company, year - 1), {}).get("总资产")
        avg_assets = ((prev_assets + assets) / 2.0) if prev_assets else assets
        ratio2 = ((net - cfo) / avg_assets) if (net is not None and cfo is not None and avg_assets) else None
        g2 = score_cash(net, cfo, ratio2)

        # ---- 指标3 回款压力 ----
        def days(rv, a, c, iv):
            if not all(x is not None for x in (rv, a, c, iv)) or rv == 0:
                return None
            return (a + c + iv) / rv * 365.0
        d3 = days(rev, ar, contract, inv)
        pf = data.get((company, year - 1), {})
        d3_prev = days(pf.get("营业收入"), pf.get("应收账款"),
                       pf.get("合同资产"), pf.get("存货"))
        d3_delta = (d3 - d3_prev) if (d3 is not None and d3_prev is not None) else None
        g3 = score_collection(d3_delta)

        # ---- 指标4 利润质量与减值压力 ----
        nr_ratio = (abs(nr) / abs(net)) if (nr is not None and net not in (None, 0)) else (0.0 if nr is None else None)
        gw_denom = None
        if equity is not None and rev is not None:
            gw_denom = max(equity, 0.01 * rev)
        gw_ratio = (goodwill / gw_denom) if (goodwill is not None and gw_denom) else (0.0 if goodwill is None else None)
        g4 = score_quality(nr_ratio, gw_ratio)

        # ---- 指标5 估值预期压力 ----
        g5 = None  # 需市值，财报内无

        scores = [g1, g2, g3, g4, g5]
        scored = [s for s in scores if s is not None]
        total = sum(scored) if scored else None

        results.append({
            "公司": company, "代码": code, "年份": year,
            "增长失速_营收同比增速": yv,
            "增长失速_样本中位数": median_yoy,
            "增长失速_得分": g1,
            "现金背离_比率": ratio2,
            "现金背离_得分": g2,
            "回款压力_回款天数": d3,
            "回款压力_同比天数变化": d3_delta,
            "回款压力_得分": g3,
            "利润质量_非经常性损益占比": nr_ratio,
            "利润质量_商誉占比": gw_ratio,
            "利润质量_得分": g4,
            "估值预期压力_PS_ttm": None,
            "估值预期压力_得分": g5,
            "可计算得分合计": total,
            "未评分指标数": sum(1 for s in scores if s is None),
        })
    return results


# ---------------------------------------------------------------------------
# 汇总 CSV
# ---------------------------------------------------------------------------
def write_summary(results):
    df = pd.DataFrame(results)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    return df


# ---------------------------------------------------------------------------
# 绘图：每份报告一张评分卡
# ---------------------------------------------------------------------------
def raw_str(r, idx):
    """构造每项指标的原始值说明文字。"""
    if idx == 0:  # 增长失速
        v = r["增长失速_营收同比增速"]
        return f"营收同比增速 {pct(v)}" if v is not None else "无上年数据"
    if idx == 1:  # 现金背离
        v = r["现金背离_比率"]
        return f"(净利-CFO)/总资产 = {pct(v)}" if v is not None else "—"
    if idx == 2:  # 回款压力
        d = r["回款压力_回款天数"]
        dd = r["回款压力_同比天数变化"]
        if d is None:
            return "—"
        if dd is None:
            return f"回款周期 {d:.0f} 天（无同比）"
        return f"回款周期 {d:.0f} 天，同比 {dd:+.1f} 天"
    if idx == 3:  # 利润质量
        nr = r["利润质量_非经常性损益占比"]
        gw = r["利润质量_商誉占比"]
        return f"非经常性占比 {pct(nr)}，商誉/净资产 {pct(gw)}"
    # 估值
    return "需外部行情数据（市值/PS）"


def score_label(s):
    if s is None:
        return "—"
    return f"{s} 分"


def status_color(s):
    if s == 0:
        return COLOR_GOOD
    if s == 1:
        return COLOR_WARN
    if s == 2:
        return COLOR_RISK
    return COLOR_NA


def plot_report(r):
    company = r["公司"]; code = r["代码"]; year = r["年份"]
    scores = [r["增长失速_得分"], r["现金背离_得分"], r["回款压力_得分"],
              r["利润质量_得分"], r["估值预期压力_得分"]]

    fig, ax = plt.subplots(figsize=(9, 5.6), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    n = len(IND_NAMES)
    ypos = list(range(n))[::-1]  # 自上而下

    for y, name, s, idx in zip(ypos, IND_NAMES, scores, range(n)):
        c = status_color(s)
        ax.barh(y, 1.0, height=0.72, color=c, alpha=0.92,
                edgecolor="white", linewidth=1.2, zorder=2)
        # 指标名（左）
        ax.text(0.03, y, name, va="center", ha="left",
                color="white", fontsize=13, fontweight="bold", zorder=3)
        # 得分 + 原始值（右）
        txt = f"{score_label(s)}   |   {raw_str(r, idx)}"
        ax.text(0.97, y, txt, va="center", ha="right",
                color="white", fontsize=10.5, zorder=3)

    ax.set_xlim(0, 1)
    ax.set_ylim(-0.6, n - 0.4)
    ax.set_yticks([])
    ax.set_xticks([])
    for sp in ["top", "right", "bottom", "left"]:
        ax.spines[sp].set_visible(False)

    total = r["可计算得分合计"]
    unscored = r["未评分指标数"]
    if total is not None:
        lvl = risk_level(total)
        total_txt = f"可计算得分合计 {total} 分（满分10，另 {unscored} 项需外部/上年数据未计）"
        title = f"{company}（{code}）{year} 年  财务脆弱性初步评估\n{total_txt}"
    else:
        title = f"{company}（{code}）{year} 年  财务脆弱性初步评估（数据不足）"
    ax.set_title(title, fontsize=14, fontweight="bold", pad=14)

    # 图例
    legend_labels = [("0 分 健康", COLOR_GOOD), ("1 分 预警", COLOR_WARN),
                     ("2 分 风险", COLOR_RISK), ("数据不足/需外部数据", COLOR_NA)]
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, c in legend_labels]
    ax.legend(handles, [t for t, _ in legend_labels], loc="lower center",
              bbox_to_anchor=(0.5, -0.22), ncol=4, frameon=False, fontsize=9)

    fig.tight_layout()
    out = os.path.join(BASE, f"脆弱性评分_{company}_{year}.png")
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    data = load_fields()
    results = compute(data)
    df = write_summary(results)
    paths = [plot_report(r) for r in results]
    return df, paths


if __name__ == "__main__":
    df, paths = main()
    print("=== 脆弱性指标汇总 ===")
    cols = ["公司", "年份", "增长失速_得分", "现金背离_得分", "回款压力_得分",
            "利润质量_得分", "估值预期压力_得分", "可计算得分合计", "未评分指标数"]
    print(df[cols].to_string(index=False))
    print("\n已生成图表：")
    for p in paths:
        print("  ", p)
