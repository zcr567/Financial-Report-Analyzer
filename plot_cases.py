# -*- coding: utf-8 -*-
"""
三个演示案例的脆弱性评分图
============================

依据《第七部分 数据来源、演示案例与合规》文字稿（7.2 样本验证）中的三个案例，
用与 compute_and_plot.py 完全相同的评分卡样式（横向条形 + 状态色 + 图例）绘制：

    案例一  芯海科技  2022 年报    总分 8 · 高风险
    案例二  完美世界  2024 一季报  总分 6 · 高风险
    案例三  拓维信息  2023 年报    总分 5 · 中风险

数据只取自文字稿原文，未做任何编造；原文未逐项列出的指标以灰色「—」标注。
完美世界 2024 一季报「利润质量」「估值」两项得分据「三项各 2 分、总分 6 分」反推为 0。

输出：脆弱性评分_<公司>_<期间>.png（3 张）
"""

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun"]
plt.rcParams["axes.unicode_minus"] = False

BASE = r"D:\python\Financial-Report-Analyzer"

IND_NAMES = ["增长失速", "现金背离", "回款压力", "利润质量与减值压力", "估值预期压力"]

# 状态色（与 compute_and_plot.py 一致）
COLOR_GOOD = "#2E8540"     # 绿
COLOR_WARN = "#C98A00"     # 琥珀
COLOR_RISK = "#C0392B"     # 红
COLOR_NA = "#9AA0A6"       # 灰

# 三个案例：公司、代码、报告期、风险等级、总分、[(得分, 关键事实)×5]、标题补充说明
CASES = [
    (
        "芯海科技", "688595.SH", "2022 年报", "高风险", 8,
        [
            (2, "营收同比 -15.30%"),
            (2, "净利 +0.42 亿 vs 经营现金流 -0.85 亿"),
            (2, "存货 2.41→3.52 亿（+46%）"),
            (2, "非经常性损益占比 61.9%"),
            (0, "市销率处样本合理区间，未触发"),
        ],
        "",
    ),
    (
        "完美世界", "002624.SZ", "2024 一季报", "高风险", 6,
        [
            (2, "营收同比 -30.19%"),
            (2, "净利 -0.30 亿，经营现金流 -3.55 亿"),
            (2, "触发（原文未列明细）"),
            (0, "未触发（据总分反推）"),
            (0, "未触发（据总分反推）"),
        ],
        "（增长失速 / 现金背离 / 回款压力各 2 分）",
    ),
    (
        "拓维信息", "002261.SZ", "2023 年报", "中风险", 5,
        [
            (None, "原文未逐项列出"),
            (2, "净利 +0.45 亿 vs 经营现金流 -11.70 亿（24.83%）"),
            (None, "原文未逐项列出"),
            (2, "非经常性损益占比 134.85%"),
            (None, "原文未逐项列出"),
        ],
        "（现金背离、利润质量各 2 分；另 1 分在其余三项）",
    ),
]


def status_color(s):
    if s == 0:
        return COLOR_GOOD
    if s == 1:
        return COLOR_WARN
    if s == 2:
        return COLOR_RISK
    return COLOR_NA


def score_label(s):
    if s is None:
        return "—"
    return f"{s} 分"


def plot_case(company, code, period, risk, total, items, detail):
    fig, ax = plt.subplots(figsize=(9.5, 5.8), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    n = len(IND_NAMES)
    ypos = list(range(n))[::-1]  # 自上而下

    for y, name, (s, fact) in zip(ypos, IND_NAMES, items):
        c = status_color(s)
        ax.barh(y, 1.0, height=0.72, color=c, alpha=0.92,
                edgecolor="white", linewidth=1.2, zorder=2)
        # 指标名（左）
        ax.text(0.03, y, name, va="center", ha="left",
                color="white", fontsize=13, fontweight="bold", zorder=3)
        # 得分 + 关键事实（右）
        txt = f"{score_label(s)}   |   {fact}"
        ax.text(0.97, y, txt, va="center", ha="right",
                color="white", fontsize=9.5, zorder=3)

    ax.set_xlim(0, 1)
    ax.set_ylim(-0.6, n - 0.4)
    ax.set_yticks([])
    ax.set_xticks([])
    for sp in ["top", "right", "bottom", "left"]:
        ax.spines[sp].set_visible(False)

    ax.set_title(f"{company}（{code}）{period}  财务脆弱性评分\n总分 {total} 分 · {risk}{detail}",
                 fontsize=14, fontweight="bold", pad=14)

    # 图例
    legend_labels = [("0 分 健康", COLOR_GOOD), ("1 分 预警", COLOR_WARN),
                     ("2 分 风险", COLOR_RISK), ("原文未逐项列出", COLOR_NA)]
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, c in legend_labels]
    ax.legend(handles, [t for t, _ in legend_labels], loc="lower center",
              bbox_to_anchor=(0.5, -0.20), ncol=4, frameon=False, fontsize=9)

    fig.tight_layout()
    out = os.path.join(BASE, f"脆弱性评分_{company}_{period.replace(' ', '')}.png")
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def main():
    paths = [plot_case(c, code, period, risk, total, items, detail)
             for c, code, period, risk, total, items, detail in CASES]
    return paths


if __name__ == "__main__":
    for p in main():
        print("generated:", p)
