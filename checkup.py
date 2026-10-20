#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据体检 —— 台账一致性检查工具

用法：
    python checkup.py                # 检查 sample/ 里的示例数据
    python checkup.py 我的数据目录     # 检查自己的数据
    python checkup.py 目录 --open    # 检查完自动打开报告

数据目录里需要三个 CSV：contracts.csv、invoices.csv、ledger.csv
字段见 README。缺哪一个就跳过依赖它的检查，不会报错。
"""

import csv
import os
import sys
import webbrowser

import checks
import report

TABLES = ("contracts", "invoices", "ledger")
SEVERITY_MARK = {checks.SEVERE: "✕", checks.WARN: "!", checks.INFO: "·"}
ANSI = {checks.SEVERE: "\033[31m", checks.WARN: "\033[33m", checks.INFO: "\033[36m"}
RESET = "\033[0m"


def load(data_dir):
    """读入三张表。行号从 2 开始（第 1 行是表头），方便直接跳到 Excel 对应行。"""
    ctx, stats = {}, {"tables": {}, "rows": 0}
    for name in TABLES:
        path = os.path.join(data_dir, f"{name}.csv")
        rows = []
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                for i, row in enumerate(csv.DictReader(f), start=2):
                    row["_line"] = i
                    rows.append(row)
        ctx[name] = rows
        stats["tables"][name] = len(rows)
        stats["rows"] += len(rows)
    return ctx, stats


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    data_dir = args[0] if args else os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample")

    if not os.path.isdir(data_dir):
        sys.exit(f"目录不存在：{data_dir}")

    ctx, stats = load(data_dir)
    if stats["rows"] == 0:
        sys.exit(f"在 {data_dir} 里没读到任何数据（需要有 contracts.csv / invoices.csv / ledger.csv）")

    findings = []
    for rule in checks.RULES:
        findings.extend(rule(ctx))

    counts = {level: sum(1 for f in findings if f.level == level) for level in SEVERITY_MARK}

    # ── 终端摘要 ──
    print()
    print(f"  数据体检　·　{os.path.basename(os.path.abspath(data_dir))}")
    print("  " + "─" * 52)
    for name, count in stats["tables"].items():
        print(f"  {name:<12}{count:>6} 条")
    print("  " + "─" * 52)
    for level, count in counts.items():
        color = ANSI[level] if sys.stdout.isatty() else ""
        print(f"  {color}{SEVERITY_MARK[level]} {level:<4}{count:>6} 项{RESET if color else ''}")
    print("  " + "─" * 52)

    for f in sorted(findings, key=lambda x: checks.LEVEL_ORDER[x.level]):
        color = ANSI[f.level] if sys.stdout.isatty() else ""
        reset = RESET if color else ""
        print(f"  {color}{f.level}{reset}  {f.rule}　{f.table} · {f.where}")
        print(f"        {f.message}")
        if f.advice:
            print(f"        → {f.advice}")
    print()

    # ── HTML 报告 ──
    html_text = report.render(findings, stats, os.path.abspath(data_dir))
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkup-report.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_text)
    print(f"  报告已生成：{out_path}\n")

    if "--open" in flags:
        webbrowser.open("file://" + out_path.replace("\\", "/"))

    # 有严重问题就返回非 0，方便接进自动化流程
    return 1 if counts[checks.SEVERE] else 0


if __name__ == "__main__":
    sys.exit(main())
