# -*- coding: utf-8 -*-
"""穿透查询：给定一个单号，还原它背后的完整关系链。

支持三种入口——合同号、发票号、流水 id，都会先解析到所属合同，
再顺着「合同 → 发票 → 流水 → 分包 → 成本 → 毛利」把整条链打出来。

这就是「关系设计得完整」的证明：任何一个数字都能追到它的源头。
"""

from checks import to_number


def _num(v):
    return f"{v:,.2f}" if isinstance(v, (int, float)) else str(v)


def resolve(ctx, key):
    """把任意单号解析到合同号，找不到返回 None。"""
    key = (key or "").strip()
    contracts = {(c.get("contract_no") or "").strip(): c for c in ctx["contracts"]}
    if key in contracts:
        return key

    for inv in ctx["invoices"]:
        if (inv.get("invoice_no") or "").strip() == key:
            ref = (inv.get("contract_no") or "").strip()
            return ref if ref in contracts else None

    for row in ctx["ledger"]:
        if (row.get("id") or "").strip() == key:
            ref = (row.get("ref_no") or "").strip()
            if ref in contracts:
                return ref
            for inv in ctx["invoices"]:
                if (inv.get("invoice_no") or "").strip() == ref:
                    c = (inv.get("contract_no") or "").strip()
                    return c if c in contracts else None
    return None


def trace(ctx, key):
    """返回 (行列表, 未找到的说明)。"""
    contract_no = resolve(ctx, key)
    if not contract_no:
        return [], f"找不到与 `{key}` 相关的合同，请确认单号是否存在"

    contract = next(c for c in ctx["contracts"]
                    if (c.get("contract_no") or "").strip() == contract_no)
    lines = []

    amount = to_number(contract.get("amount")) or 0.0
    ratio = to_number(contract.get("collection_ratio"))
    lines.append(f"合同 {contract_no}　{contract.get('customer') or '—'}　{contract.get('sign_date') or '—'}")
    lines.append(f"  产值 {_num(amount)}"
                 + (f"　约定收款 {ratio:.0%}" if ratio else "　约定收款 —"))
    if ratio and amount > 0:
        lines.append(f"  应收 {_num(amount * ratio)}")

    # ── 收入链 ──
    invoices = [i for i in ctx["invoices"]
                if (i.get("contract_no") or "").strip() == contract_no]
    received_total = 0.0

    # 单号重复时，按单号关联会把两张票的钱串在一起，这里显式标出来
    dup_counter = {}
    for i in ctx["invoices"]:
        n = (i.get("invoice_no") or "").strip()
        if n:
            dup_counter[n] = dup_counter.get(n, 0) + 1

    lines.append("")
    lines.append("  收入链")
    if not invoices:
        lines.append("  └─ 尚无开票记录")
    for n, inv in enumerate(invoices):
        last = n == len(invoices) - 1
        branch = "  └─" if last else "  ├─"
        inv_no = (inv.get("invoice_no") or "").strip()
        inv_amt = to_number(inv.get("amount")) or 0.0
        warn = "　← 单号重复，下列流水可能串单" if dup_counter.get(inv_no, 0) > 1 else ""
        lines.append(f"{branch} 发票 {inv_no}　{inv.get('issue_date') or '—'}　{_num(inv_amt)}{warn}")

        flows = [r for r in ctx["ledger"]
                 if (r.get("ref_no") or "").strip() == inv_no
                 and (r.get("direction") or "").strip().lower() == "in"]
        pad = "  " if last else "  │ "
        if not flows:
            lines.append(f"{pad}  └─ 未收到对应款项")
        for m, f in enumerate(flows):
            f_last = m == len(flows) - 1
            fb = "└─" if f_last else "├─"
            fa = to_number(f.get("amount")) or 0.0
            received_total += fa
            lines.append(f"{pad}  {fb} 流水 #{f.get('id')}　{f.get('date')}　"
                         f"{f.get('category') or '未分类'}　{_num(fa)}")

    # ── 成本链 ──
    subs = [c for c in ctx["contracts"]
            if (c.get("parent_contract_no") or "").strip() == contract_no]
    cost_by_cat = {}
    lines.append("")
    lines.append("  成本链")

    if not subs:
        lines.append("  └─ 无分包")
    for n, sub in enumerate(subs):
        last = n == len(subs) - 1
        branch = "  └─" if last else "  ├─"
        sub_no = (sub.get("contract_no") or "").strip()
        sub_amt = to_number(sub.get("amount")) or 0.0
        lines.append(f"{branch} 分包 {sub_no}　{sub.get('customer') or '—'}　约定 {_num(sub_amt)}")

        pad = "  " if last else "  │ "
        flows = [r for r in ctx["ledger"]
                 if (r.get("ref_no") or "").strip() == sub_no
                 and (r.get("direction") or "").strip().lower() == "out"]
        if not flows:
            lines.append(f"{pad}  └─ 尚未付款")
        for m, f in enumerate(flows):
            f_last = m == len(flows) - 1
            fb = "└─" if f_last else "├─"
            fa = to_number(f.get("amount")) or 0.0
            cat = f.get("category") or "未分类"
            cost_by_cat[cat] = cost_by_cat.get(cat, 0.0) + fa
            flag = "　← 与约定金额不符" if abs(fa - sub_amt) > max(1.0, sub_amt * 0.05) else ""
            lines.append(f"{pad}  {fb} 流水 #{f.get('id')}　{f.get('date')}　{cat}　{_num(fa)}{flag}")

    # 直接挂在本合同上的支出（非分包）
    direct = [r for r in ctx["ledger"]
              if (r.get("ref_no") or "").strip() == contract_no
              and (r.get("direction") or "").strip().lower() == "out"]
    for f in direct:
        fa = to_number(f.get("amount")) or 0.0
        cat = f.get("category") or "未分类"
        cost_by_cat[cat] = cost_by_cat.get(cat, 0.0) + fa
        lines.append(f"  ├─ 直接支出 #{f.get('id')}　{f.get('date')}　{cat}　{_num(fa)}")

    # ── 结论 ──
    cost_total = sum(cost_by_cat.values())
    lines.append("")
    lines.append("  成本汇总")
    if cost_by_cat:
        for cat, val in sorted(cost_by_cat.items(), key=lambda x: -x[1]):
            lines.append(f"  {cat}　{_num(val)}")
    else:
        lines.append("  （暂无归集成本）")
    lines.append(f"  合计 {_num(cost_total)}")

    lines.append("")
    lines.append(f"  实收 {_num(received_total)}　−　成本 {_num(cost_total)}　"
                 f"＝　毛利 {_num(received_total - cost_total)}")
    if cost_total > received_total and received_total > 0:
        lines.append("  注：成本大于实收，通常是某笔金额多打或少打了一位，或项目尚未收齐款")

    return lines, None
