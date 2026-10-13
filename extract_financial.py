# -*- coding: utf-8 -*-
"""
财报数据提取脚本
================

从 PDF 年报中提取 10 个财务指标，整理成 CSV。

覆盖三类财报格式：
1. 港股 IFRS 双语年报（金蝶国际：英文 + 繁体，单位人民币千元）
2. 港股 IFRS 繁体年报（商汤-W：繁体，单位人民币千元）
3. A 股 CAS 年报   （广联达：简体，单位人民币元）

输出字段（全部使用中文字段名）：
    公司、代码、期间开始、期间结束、期间类型、字段、数值、
    币种、单位、来源文件、PDF页码、原始标签、审核状态

字段（中文）：
    营业收入、净利润、经营活动产生的现金流量净额、总资产、
    所有者权益、应收账款、合同资产、存货、商誉、非经常性损益

提取口径约定（详见字段映射说明）：
    - 净利润   = 报告期净损益总额（含少数股东损益）
    - 所有者权益 = 所有者权益总额（含少数股东权益）
    - 金额统一换算为「元」（原单位为千元的乘以 1000）
    - 未披露字段留空，绝不填 0

依赖：PyMuPDF（fitz）、pandas
"""

import os
import re

import fitz  # PyMuPDF
import pandas as pd

# ---------------------------------------------------------------------------
# 字段常量（中文）
# ---------------------------------------------------------------------------
FIELD_REVENUE = "营业收入"
FIELD_NET = "净利润"
FIELD_CFO = "经营活动产生的现金流量净额"
FIELD_ASSET = "总资产"
FIELD_EQUITY = "所有者权益"
FIELD_AR = "应收账款"
FIELD_CONTRACT = "合同资产"
FIELD_INV = "存货"
FIELD_GOODWILL = "商誉"
FIELD_NR = "非经常性损益"


# ---------------------------------------------------------------------------
# 通用工具函数
# ---------------------------------------------------------------------------
def clean_num(s):
    """把财报中的数字文本解析成 float，无法解析返回 None。

    支持：'5,679,073'、'(269,806)'（负数）、'-924,433,593.88'、'6,524,575,067.70'。
    '–' / '—' / 空串 返回 None。
    """
    if s is None:
        return None
    s = s.strip()
    if s in ("–", "—", "-", "", "－", "—"):
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    s = s.replace(",", "").replace("，", "").replace(" ", "")
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", s):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def is_note_ref(s):
    """判断一个 token 是否为报表附注编号（需跳过，而非数值）。"""
    s = s.strip()
    if not s:
        return True
    if re.search(r"[a-zA-Z]", s):      # 含字母 -> 附注编号
        return True
    if re.fullmatch(r"\d{1,2}", s):     # 裸 1~2 位整数 -> 附注编号
        return True
    if re.fullmatch(r"\d{1,2}[,\s]+\d{1,2}", s):  # 多附注 '5, 25'
        return True
    return False


def flatten(doc):
    """返回 [(页码(1起), 行文本), ...]，仅保留非空行。"""
    out = []
    for i in range(doc.page_count):
        for line in doc[i].get_text().split("\n"):
            s = line.strip()
            if s:
                out.append((i + 1, s))
    return out


def find_statement(flat, headers, marker=None):
    """定位某张报表的起始页（1 起）。

    headers: 报表标题关键词（任一命中）。
    marker: 若提供，要求同一页也必须包含该关键词，用于区分目录/正文。
    """
    # 先按页聚合文本，再判断“同一页是否同时含标题与 marker”
    page_text = {}
    for pg, line in flat:
        page_text.setdefault(pg, []).append(line)
    for pg in sorted(page_text):
        t = "\n".join(page_text[pg])
        if any(h in t for h in headers):
            if marker is None or marker in t:
                return pg
    return None


def label_value(flat, labels, start_page, end_page, take="first",
                sum_all=False, exact=False):
    """在 [start_page, end_page] 内查找标签，返回 (数值或None, 页码或None)。

    labels: 候选标签。
    exact:  True 时标签须与整行完全相等（避免子串误匹配）。
    take:   'first' 取第一个金额；'last' 取最后一个（同一标签分列非流动/流动时取流动）。
    sum_all: True 时把该标签所有出现处的第一个金额相加（如合同资产分列两处时合计）。
    """
    hits = []
    for idx, (pg, line) in enumerate(flat):
        if pg < start_page or pg > end_page:
            continue
        matched = False
        for l in labels:
            if exact:
                if line == l:
                    matched = True
                    break
            else:
                if l in line:
                    matched = True
                    break
        if not matched:
            continue
        # 向后扫描金额
        j = idx + 1
        vals = []
        while j < len(flat) and flat[j][0] <= end_page and len(vals) < 3:
            token = flat[j][1]
            if is_note_ref(token):
                j += 1
                continue
            v = clean_num(token)
            if v is not None:
                vals.append(v)
                j += 1
                continue
            j += 1
        if vals:
            hits.append((pg, vals[0]))
    if not hits:
        return None, None
    if sum_all:
        return sum(v for _, v in hits), hits[0][0]
    if take == "last":
        return hits[-1][1], hits[-1][0]
    return hits[0][1], hits[0][0]


def _row(company, code, year, field, value, currency, unit, source, page,
         original_label, review_status=""):
    return {
        "公司": company,
        "代码": code,
        "期间开始": f"{year}-01-01",
        "期间结束": f"{year}-12-31",
        "期间类型": "全年",
        "字段": field,
        "数值": value,
        "币种": currency,
        "单位": unit,
        "来源文件": source,
        "PDF页码": page,
        "原始标签": original_label,
        "审核状态": review_status,
    }


# ---------------------------------------------------------------------------
# 各公司提取器
# ---------------------------------------------------------------------------
def extract_kingdee(path, company, code, year):
    """金蝶国际（双语 IFRS 年报，人民币千元）。"""
    doc = fitz.open(path)
    flat = flatten(doc)
    total = doc.page_count

    # 中英双语标题 + 「人民幣千元」单位标记，排除目录/审计报告误匹配。
    # 注意：2025 年报将「合併」改为「綜合」、「损益表」改为「利潤表」，需同时覆盖两种措辞。
    bs = find_statement(flat, ["CONSOLIDATED STATEMENT OF FINANCIAL POSITION",
                               "合併財務狀況表", "綜合財務狀況表"],
                        marker="人民幣千元")
    ins = find_statement(flat, ["CONSOLIDATED INCOME STATEMENT",
                                "合併損益表", "綜合利潤表"],
                         marker="人民幣千元")
    cf = find_statement(flat, ["CONSOLIDATED CASH FLOW", "CONSOLIDATED STATEMENT OF CASH FLOWS",
                               "合併現金流量表", "綜合現金流量表"], marker="人民幣千元")

    rows = []

    def add(field, value, page, label, review=""):
        rows.append(_row(company, code, year, field, value, "人民币", "元",
                         os.path.basename(path), page, label, review))

    # 利润表（窗口 +5 页）
    v, pg = label_value(flat, ["Revenue from contracts with customers"],
                        ins, ins + 5)
    add(FIELD_REVENUE, v, pg, "Revenue from contracts with customers / 與客戶之間的合同產生的收入")

    v, pg = label_value(flat, ["Loss for the year", "Profit for the year",
                               "Profit/(loss) for the year", "Loss/(profit) for the year"],
                        ins, ins + 5, exact=True)
    add(FIELD_NET, v, pg, "Profit/(loss) for the year / 年度利潤/（虧損）")

    # 资产负债表
    v, pg = label_value(flat, ["Total assets"], bs, bs + 5)
    add(FIELD_ASSET, v, pg, "Total assets / 總資產")

    v, pg = label_value(flat, ["Total equity"], bs, bs + 5)
    add(FIELD_EQUITY, v, pg, "Total equity / 總權益")

    v, pg = label_value(flat, ["Trade and other receivables"],
                        bs, bs + 5, take="last")
    add(FIELD_AR, v, pg, "Trade and other receivables / 應收賬款及其他應收款",
        "需要人工确认：IFRS口径含其他应收款，非纯应收账款")

    v, pg = label_value(flat, ["Contract assets"], bs, bs + 5)
    add(FIELD_CONTRACT, v, pg, "Contract assets / 合同資產")

    v, pg = label_value(flat, ["Inventories"], bs, bs + 5)
    add(FIELD_INV, v, pg, "Inventories / 存貨")

    # 商誉（不在主表，含于无形资产，取自附注，返回千元口径）
    gw, gw_pg = _find_goodwill_kingdee(flat)
    add(FIELD_GOODWILL, gw, gw_pg, "Goodwill（附注：含于无形资产）",
        "需要人工确认：商誉含于无形资产，金额取自附注" if gw is not None else "未披露")

    # 现金流量表
    v, pg = label_value(flat, ["Net cash inflow from operating activities",
                               "Net cash generated from operating activities",
                               "Net cash (used in) operating activities",
                               "Net cash used in operating activities"],
                        cf, cf + 5)
    add(FIELD_CFO, v, pg, "Net cash inflow from operating activities / 經營活動產生淨現金")

    # 非经常性损益（IFRS 不单独披露）
    add(FIELD_NR, None, None, "非经常性损益（IFRS不单独披露）",
        "未披露：IFRS准则下不单独披露非经常性损益")

    doc.close()
    return rows


def _find_goodwill_kingdee(flat):
    """金蝶商誉（千元口径）：优先取审计报告 'goodwill of RMB...'，否则累加附注 'goodwill amounting to RMB...'。"""
    for pg, line in flat:
        m = re.search(r"goodwill of RMB([\d,]+)", line, re.IGNORECASE)
        if m:
            return (clean_num(m.group(1)) / 1000.0, pg)
    total = 0.0
    pg = None
    for p, line in flat:
        m = re.search(r"goodwill amounting to RMB([\d,]+)", line, re.IGNORECASE)
        if m:
            total += clean_num(m.group(1)) or 0
            pg = pg or p
    if pg:
        return (total / 1000.0, pg)
    return (None, None)


def extract_sensetime(path, company, code, year):
    """商汤-W（繁体 IFRS 年报，人民币千元）。"""
    doc = fitz.open(path)
    flat = flatten(doc)

    ins = find_statement(flat, ["綜合收益表"], marker="人民幣千元")
    bs = find_statement(flat, ["綜合資產負債表"], marker="人民幣千元")
    cf = find_statement(flat, ["綜合現金流量表"], marker="人民幣千元")

    rows = []

    def add(field, value, page, label, review=""):
        rows.append(_row(company, code, year, field, value, "人民币", "元",
                         os.path.basename(path), page, label, review))

    v, pg = label_value(flat, ["收入"], ins, ins + 5, exact=True)
    add(FIELD_REVENUE, v, pg, "收入")

    v, pg = label_value(flat, ["年度虧損", "年度溢利"], ins, ins + 5, exact=True)
    add(FIELD_NET, v, pg, "年度虧損/溢利")

    v, pg = label_value(flat, ["總資產"], bs, bs + 5)
    add(FIELD_ASSET, v, pg, "總資產")

    v, pg = label_value(flat, ["總權益"], bs, bs + 5)
    add(FIELD_EQUITY, v, pg, "總權益")

    v, pg = label_value(flat, ["貿易、其他應收款項及預付款項", "貿易及其他應收款項"],
                        bs, bs + 5)
    add(FIELD_AR, v, pg, "貿易、其他應收款項及預付款項",
        "需要人工确认：含其他应收款及预付款项，非纯应收账款")

    # 合同资产分列非流动与流动两处，需合计
    v, pg = label_value(flat, ["合約資產"], bs, bs + 5, sum_all=True)
    add(FIELD_CONTRACT, v, pg, "合約資產（非流动+流动合计）")

    v, pg = label_value(flat, ["存貨"], bs, bs + 5)
    add(FIELD_INV, v, pg, "存貨")

    add(FIELD_GOODWILL, None, None, "商譽（未单独列示）",
        "未披露：报表未单独列示商誉")

    v, pg = label_value(flat, ["經營活動所用現金淨額", "經營活動所得現金淨額",
                               "經營活動（所用）/所得現金淨額",
                               "經營活動所用/所得現金淨額"],
                        cf, cf + 5)
    add(FIELD_CFO, v, pg, "經營活動所用/所得現金淨額")

    add(FIELD_NR, None, None, "非经常性损益（IFRS不单独披露）",
        "未披露：IFRS准则下不单独披露非经常性损益")

    doc.close()
    return rows


def extract_glodon(path, company, code, year):
    """广联达（A股 CAS 年报，人民币元）。"""
    doc = fitz.open(path)
    flat = flatten(doc)

    bs = find_statement(flat, ["合并资产负债表"], marker="编制单位")
    ins = find_statement(flat, ["合并利润表"], marker="营业总收入")
    cf = find_statement(flat, ["合并现金流量表"], marker="经营活动产生的现金流量净额")

    rows = []

    def add(field, value, page, label, review=""):
        rows.append(_row(company, code, year, field, value, "人民币", "元",
                         os.path.basename(path), page, label, review))

    v, pg = label_value(flat, ["其中：营业收入"], ins, ins + 5)
    add(FIELD_REVENUE, v, pg, "其中：营业收入")

    v, pg = label_value(flat, ["五、净利润"], ins, ins + 5)
    add(FIELD_NET, v, pg, "五、净利润（含少数股东损益）")

    v, pg = label_value(flat, ["经营活动产生的现金流量净额"], cf, cf + 5)
    add(FIELD_CFO, v, pg, "经营活动产生的现金流量净额")

    v, pg = label_value(flat, ["资产总计"], bs, bs + 5)
    add(FIELD_ASSET, v, pg, "资产总计")

    v, pg = label_value(flat, ["所有者权益合计"], bs, bs + 5, exact=True)
    add(FIELD_EQUITY, v, pg, "所有者权益合计")

    v, pg = label_value(flat, ["应收账款"], bs, bs + 5)
    add(FIELD_AR, v, pg, "应收账款")

    v, pg = label_value(flat, ["合同资产"], bs, bs + 5)
    add(FIELD_CONTRACT, v, pg, "合同资产")

    v, pg = label_value(flat, ["存货"], bs, bs + 5)
    add(FIELD_INV, v, pg, "存货")

    v, pg = label_value(flat, ["商誉"], bs, bs + 5)
    add(FIELD_GOODWILL, v, pg, "商誉")

    nr, nr_pg = _find_nonrecurring_glodon(flat)
    add(FIELD_NR, nr, nr_pg, "非经常性损益合计（归属于母公司股东）")

    doc.close()
    return rows


def _find_nonrecurring_glodon(flat):
    """广联达非经常性损益：定位「非经常性损益项目及金额」表，取最后一个「合计」行金额。"""
    start = None
    for pg, line in flat:
        if "非经常性损益" in line and "项目" in line:
            start = pg
            break
    if start is None:
        return (None, None)
    result = None
    result_pg = None
    for idx, (pg, line) in enumerate(flat):
        if pg < start or pg > start + 3:
            continue
        if line == "合计":
            j = idx + 1
            while j < len(flat) and flat[j][0] <= start + 3:
                v = clean_num(flat[j][1])
                if v is not None:
                    result = v
                    result_pg = pg
                    break
                j += 1
    return (result, result_pg)


# ---------------------------------------------------------------------------
# 单位换算：千元 -> 元
# ---------------------------------------------------------------------------
def to_yuan(value, src_unit):
    if value is None:
        return None
    return value * 1000.0 if src_unit == "千元" else value


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    reports = [
        {"path": r"C:\Users\36544\Desktop\问题较少的财报\金蝶国际：二零二三年年报.pdf",
         "company": "金蝶国际", "code": "00268.HK", "year": 2023,
         "format": "kingdee", "unit": "千元"},
        {"path": r"C:\Users\36544\Desktop\问题较少的财报\金蝶国际：二零二四年年报.pdf",
         "company": "金蝶国际", "code": "00268.HK", "year": 2024,
         "format": "kingdee", "unit": "千元"},
        {"path": r"C:\Users\36544\Desktop\问题较少的财报\金蝶国际：二零二五年年报.pdf",
         "company": "金蝶国际", "code": "00268.HK", "year": 2025,
         "format": "kingdee", "unit": "千元"},
        {"path": r"C:\Users\36544\Desktop\问题最多的财报\商汤-W：2023 年报.pdf",
         "company": "商汤-W", "code": "00020.HK", "year": 2023,
         "format": "sensetime", "unit": "千元"},
        {"path": r"C:\Users\36544\Desktop\问题最多的财报\广联达：2023年年度报告.pdf",
         "company": "广联达", "code": "002410.SZ", "year": 2023,
         "format": "glodon", "unit": "元"},
    ]

    extractors = {
        "kingdee": extract_kingdee,
        "sensetime": extract_sensetime,
        "glodon": extract_glodon,
    }

    all_rows = []
    for r in reports:
        if not os.path.exists(r["path"]):
            print(f"[跳过] 文件不存在：{r['path']}")
            continue
        rows = extractors[r["format"]](r["path"], r["company"], r["code"], r["year"])
        for row in rows:
            if row["数值"] is not None:
                row["数值"] = to_yuan(row["数值"], r["unit"])
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows, columns=[
        "公司", "代码", "期间开始", "期间结束", "期间类型", "字段",
        "数值", "币种", "单位", "来源文件", "PDF页码", "原始标签", "审核状态",
    ])
    out_csv = r"D:\python\Financial-Report-Analyzer\财报数据提取.csv"
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    return df


if __name__ == "__main__":
    df = main()
