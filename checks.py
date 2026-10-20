# -*- coding: utf-8 -*-
"""体检规则集

每条规则都是「输入数据 → 输出问题清单」，互不依赖，可以单独启用或关闭。
新增一条规则 = 写一个函数 + 注册到 RULES 里，不需要改其他任何地方。
"""

import statistics
from dataclasses import dataclass
from datetime import datetime

SEVERE = "严重"
WARN = "警告"
INFO = "提示"

LEVEL_ORDER = {SEVERE: 0, WARN: 1, INFO: 2}


@dataclass
class Finding:
    """一条体检结论。"""

    level: str  # 严重 / 警告 / 提示
    rule: str  # 规则名
    table: str  # 出问题的表
    where: str  # 定位：哪一行、哪个单号
    message: str  # 问题描述
    advice: str = ""  # 修复建议


def parse_date(text):
    """解析日期，返回 (日期对象, 是否标准格式)。

    只认 YYYY-MM-DD 为「标准」；YYYY/M/D 能解析但会提示格式不统一；
    解析不了返回 (None, False)，由调用方当作数据错误处理。
    """
    text = (text or "").strip()
    if not text:
        return None, False
    for fmt, standard in (("%Y-%m-%d", True), ("%Y/%m/%d", False)):
        try:
            return datetime.strptime(text, fmt).date(), standard
        except ValueError:
            continue
    return None, False


def to_number(text):
    """把金额字符串转成数字，转换不了返回 None。"""
    text = (text or "").strip().replace(",", "").replace("，", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# ─────────────────────────── 规则 ───────────────────────────


def check_required(ctx):
    """必填项不能为空。空值会让后续所有统计静默失真。"""
    out = []
    for table, fields in (("contracts", ["contract_no", "customer", "sign_date", "amount"]),
                          ("invoices", ["invoice_no", "contract_no", "issue_date", "amount"]),
                          ("ledger", ["id", "date", "category", "direction", "amount"])):
        for row in ctx[table]:
            for name in fields:
                if not (row.get(name) or "").strip():
                    out.append(Finding(
                        SEVERE, "必填项缺失", table,
                        f"第 {row['_line']} 行（{row.get('contract_no') or row.get('invoice_no') or row.get('id')}）",
                        f"字段 `{name}` 为空",
                        "补齐后再参与统计，否则分类汇总会漏掉这笔",
                    ))
    return out


def check_duplicate(ctx):
    """主键与疑似重复记账。重复会导致金额被算两遍。"""
    out = []

    seen = {}
    for row in ctx["invoices"]:
        key = (row.get("invoice_no") or "").strip()
        if not key:
            continue
        if key in seen:
            out.append(Finding(
                SEVERE, "单号重复", "invoices",
                f"第 {row['_line']} 行与第 {seen[key]} 行",
                f"发票号 `{key}` 出现两次",
                "核对是否为重复录入；若确为两张票，说明开票方把票号写错了",
            ))
        else:
            seen[key] = row["_line"]

    seen = {}
    for row in ctx["ledger"]:
        key = (row.get("date", ""), row.get("category", ""),
               row.get("direction", ""), row.get("amount", ""))
        if not all(key):
            continue
        if key in seen:
            out.append(Finding(
                WARN, "疑似重复记账", "ledger",
                f"第 {row['_line']} 行与第 {seen[key]} 行",
                f"日期、分类、方向、金额四项完全相同（{row['amount']}）",
                "如果确实是两笔业务，请在备注里区分；否则删掉一条",
            ))
        else:
            seen[key] = row["_line"]
    return out


def check_orphan(ctx):
    """引用完整性：发票挂的合同、流水挂的单据，必须真实存在。"""
    out = []
    contracts = {(r.get("contract_no") or "").strip() for r in ctx["contracts"]}
    invoices = {(r.get("invoice_no") or "").strip() for r in ctx["invoices"]}
    known = contracts | invoices

    for row in ctx["invoices"]:
        ref = (row.get("contract_no") or "").strip()
        if ref and ref not in contracts:
            out.append(Finding(
                SEVERE, "引用不存在", "invoices",
                f"第 {row['_line']} 行（{row.get('invoice_no')}）",
                f"引用的合同 `{ref}` 在主表里不存在",
                "合同号写错，或合同根本没录进系统",
            ))

    for row in ctx["ledger"]:
        ref = (row.get("ref_no") or "").strip()
        if ref and ref not in known:
            out.append(Finding(
                WARN, "引用不存在", "ledger",
                f"第 {row['_line']} 行",
                f"关联单号 `{ref}` 在合同表和发票表里都找不到",
                "补录来源单据，或清理这个错误的关联",
            ))
    return out


def check_date_order(ctx):
    """时间逻辑：开票日期不可能早于合同签订日期。"""
    out = []
    sign = {}
    for row in ctx["contracts"]:
        d, _ = parse_date(row.get("sign_date"))
        if d:
            sign[(row.get("contract_no") or "").strip()] = d

    for row in ctx["invoices"]:
        issue, _ = parse_date(row.get("issue_date"))
        ref = (row.get("contract_no") or "").strip()
        if issue and ref in sign and issue < sign[ref]:
            out.append(Finding(
                SEVERE, "时间倒置", "invoices",
                f"第 {row['_line']} 行（{row.get('invoice_no')}）",
                f"开票日期 {issue} 早于合同签订日期 {sign[ref]}",
                "日期录错，或这笔是先开票后补合同——两种情况都需要说明",
            ))
    return out


def check_date_format(ctx):
    """日期格式统一性。格式混用会让排序、按月汇总悄悄出错。"""
    out = []
    for table, field in (("contracts", "sign_date"), ("invoices", "issue_date"), ("ledger", "date")):
        for row in ctx[table]:
            raw = (row.get(field) or "").strip()
            if not raw:
                continue
            d, standard = parse_date(raw)
            if d is None:
                out.append(Finding(
                    SEVERE, "日期无法解析", table,
                    f"第 {row['_line']} 行",
                    f"字段 `{field}` 的值 `{raw}` 无法识别为日期",
                    "统一改成 YYYY-MM-DD",
                ))
            elif not standard:
                out.append(Finding(
                    INFO, "日期格式不统一", table,
                    f"第 {row['_line']} 行",
                    f"字段 `{field}` 用了 `{raw}`，其他行是 YYYY-MM-DD",
                    "批量替换成 YYYY-MM-DD，否则按月统计会漏",
                ))
    return out


def check_negative(ctx):
    """金额为负或为零。负数会让「合计」变成减法，必须人工确认。"""
    out = []
    for table in ("contracts", "invoices", "ledger"):
        for row in ctx[table]:
            val = to_number(row.get("amount"))
            if val is None:
                out.append(Finding(
                    SEVERE, "金额无法解析", table,
                    f"第 {row['_line']} 行",
                    f"金额 `{row.get('amount')}` 不是数字",
                    "清掉单位、空格或全角字符",
                ))
            elif val < 0:
                out.append(Finding(
                    SEVERE, "金额为负", table,
                    f"第 {row['_line']} 行",
                    f"金额为 {val:,.2f}",
                    "负数要么是冲销、要么是录错了符号；确认后在备注里写明性质",
                ))
            elif val == 0:
                out.append(Finding(
                    WARN, "金额为零", table,
                    f"第 {row['_line']} 行",
                    "金额为 0",
                    "零金额记录通常没有业务意义，确认是否漏填",
                ))
    return out


def check_over_invoice(ctx):
    """勾稽：同一合同的开票总额不应超过合同金额。"""
    out = []
    contract_amount = {}
    for row in ctx["contracts"]:
        key = (row.get("contract_no") or "").strip()
        val = to_number(row.get("amount"))
        if key and val is not None:
            contract_amount[key] = val

    billed = {}
    for row in ctx["invoices"]:
        key = (row.get("contract_no") or "").strip()
        val = to_number(row.get("amount"))
        if key and val is not None:
            billed.setdefault(key, []).append((row["_line"], val))

    for key, items in billed.items():
        if key not in contract_amount:
            continue
        total = sum(v for _, v in items)
        limit = contract_amount[key]
        if limit > 0 and total > limit:
            ratio = total / limit
            out.append(Finding(
                SEVERE if ratio > 1.05 else WARN, "超额开票", "invoices",
                f"合同 `{key}`（涉及第 {', '.join(str(l) for l, _ in items)} 行）",
                f"开票合计 {total:,.2f}，超过合同金额 {limit:,.2f}（{ratio:.1%}）",
                "核对是否有补充协议；没有的话属于多开票，需要红冲",
            ))
    return out


def check_reconcile(ctx):
    """对账：流水金额应当等于对应发票金额。不等说明有一边录错或部分收付。"""
    out = []
    invoice_amount = {}
    for row in ctx["invoices"]:
        key = (row.get("invoice_no") or "").strip()
        val = to_number(row.get("amount"))
        if key and val is not None:
            invoice_amount.setdefault(key, val)

    for row in ctx["ledger"]:
        ref = (row.get("ref_no") or "").strip()
        if not ref or ref not in invoice_amount:
            continue
        flow = to_number(row.get("amount"))
        expect = invoice_amount[ref]
        if flow is None:
            continue
        if abs(flow - expect) > 0.01:
            out.append(Finding(
                WARN, "金额不符", "ledger",
                f"第 {row['_line']} 行（{ref}）",
                f"流水 {flow:,.2f} ≠ 发票 {expect:,.2f}，差额 {flow - expect:,.2f}",
                "部分付款请拆成多行分别登记；否则是其中一边录错了",
            ))
    return out


def check_receivable(ctx):
    """应收对账：合同产值 × 约定收款比例 = 应收，与已到账流水比较。

    这条规则是整套关系模型里最有用的一条——它把「钱该什么时候到、到多少」
    从人的记忆变成了可计算的数字，于是欠款能被自动发现。
    """
    out = []

    inv_by_contract = {}
    for row in ctx["invoices"]:
        ref = (row.get("contract_no") or "").strip()
        inv = (row.get("invoice_no") or "").strip()
        if ref and inv:
            inv_by_contract.setdefault(ref, set()).add(inv)

    received = {}
    for row in ctx["ledger"]:
        if (row.get("direction") or "").strip().lower() != "in":
            continue
        ref = (row.get("ref_no") or "").strip()
        val = to_number(row.get("amount"))
        if ref and val is not None:
            received[ref] = received.get(ref, 0.0) + val

    for row in ctx["contracts"]:
        no = (row.get("contract_no") or "").strip()
        if (row.get("type") or "").strip() != "商务":
            continue
        amount = to_number(row.get("amount"))
        ratio = to_number(row.get("collection_ratio"))
        if not no or amount is None or ratio is None or amount <= 0 or ratio <= 0:
            continue

        due = amount * ratio
        got = sum(received.get(inv, 0.0) for inv in inv_by_contract.get(no, ()))
        diff = got - due
        if abs(diff) < 1:
            continue

        out.append(Finding(
            WARN if diff < 0 else INFO,
            "应收未收" if diff < 0 else "实收超过应收",
            "contracts",
            f"{no}（{row.get('customer')}）",
            f"应收 {due:,.2f}（产值 {amount:,.2f} × {ratio:.0%}），"
            f"实收 {got:,.2f}，差额 {diff:+,.2f}",
            "确认是否有未开票的到账、预收款，或收款比例已按补充协议调整过",
        ))
    return out


def check_outlier(ctx):
    """离群值：用四分位距找出「比同类大一个量级」的记录。

    不用平均数判断——一笔极端值会把平均数拉高，反而藏住它自己。
    """
    out = []
    values = []
    for row in ctx["ledger"]:
        val = to_number(row.get("amount"))
        if val is not None and val > 0:
            values.append((row, val))

    if len(values) < 8:
        return out

    nums = sorted(v for _, v in values)
    q1 = statistics.quantiles(nums, n=4)[0]
    q3 = statistics.quantiles(nums, n=4)[2]
    iqr = q3 - q1
    if iqr <= 0:
        return out
    upper = q3 + 3 * iqr
    lower = max(0.0, q1 - 3 * iqr)

    for row, val in values:
        if val > upper or val < lower:
            out.append(Finding(
                WARN, "疑似离群值", "ledger",
                f"第 {row['_line']} 行（{row.get('ref_no') or '无关联单号'}）",
                f"金额 {val:,.2f}，中位数 {statistics.median(nums):,.2f}，"
                f"正常区间约 {lower:,.0f} ~ {upper:,.0f}",
                "大概率是多打或少打了一个零，也可能是真有大额业务——请人工确认",
            ))
    return out


RULES = [
    check_required,
    check_duplicate,
    check_orphan,
    check_date_order,
    check_date_format,
    check_negative,
    check_over_invoice,
    check_reconcile,
    check_receivable,
    check_outlier,
]
