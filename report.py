# -*- coding: utf-8 -*-
"""HTML 报告生成：把体检结果渲染成一个可以直接发给同事看的单页报告。

不引用任何外部 CSS/JS/字体，单个文件拷走就能打开。
"""

import datetime
import html

from checks import INFO, LEVEL_ORDER, SEVERE, WARN

COLORS = {
    SEVERE: ("#A32D2D", "#FCEBEB", "#791F1F"),
    WARN: ("#854F0B", "#FAEEDA", "#633806"),
    INFO: ("#185FA5", "#E6F1FB", "#0C447C"),
}


def _esc(text):
    return html.escape(str(text or ""))


def render(findings, stats, source):
    counts = {SEVERE: 0, WARN: 0, INFO: 0}
    for f in findings:
        counts[f.level] = counts.get(f.level, 0) + 1

    total = len(findings)
    health = 100 if not stats["rows"] else max(0, 100 - round(
        (counts[SEVERE] * 10 + counts[WARN] * 3 + counts[INFO]) / max(1, stats["rows"] / 5)
    ))

    findings = sorted(findings, key=lambda f: (LEVEL_ORDER.get(f.level, 9), f.table, f.rule))

    head = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>数据体检报告 · {_esc(source)}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 40px 20px;
    font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
    background: #F7F6F3; color: #2C2C2A; line-height: 1.65;
  }}
  .wrap {{ max-width: 880px; margin: 0 auto; }}
  h1 {{ font-size: 24px; font-weight: 500; margin: 0 0 6px; }}
  .meta {{ font-size: 13px; color: #5F5E5A; margin-bottom: 28px; }}
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 28px; }}
  .card {{ background: #fff; border: 1px solid #E4E2DC; border-radius: 12px; padding: 16px 18px; }}
  .card .num {{ font-size: 26px; font-weight: 500; line-height: 1.2; }}
  .card .label {{ font-size: 12px; color: #5F5E5A; margin-top: 2px; }}
  .sec {{ font-size: 15px; font-weight: 500; margin: 30px 0 12px; }}
  .item {{
    background: #fff; border: 1px solid #E4E2DC; border-left-width: 3px;
    border-radius: 10px; padding: 14px 18px; margin-bottom: 10px;
  }}
  .item .top {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }}
  .badge {{ font-size: 11px; padding: 2px 8px; border-radius: 20px; }}
  .rule {{ font-size: 14px; font-weight: 500; }}
  .loc {{ font-size: 12px; color: #5F5E5A; }}
  .msg {{ font-size: 14px; }}
  .advice {{ font-size: 13px; color: #5F5E5A; margin-top: 6px; }}
  .ok {{ background: #EAF3DE; border: 1px solid #C0DD97; border-radius: 12px; padding: 20px; font-size: 14px; color: #27500A; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; background: #fff; border-radius: 12px; overflow: hidden; }}
  th, td {{ text-align: left; padding: 10px 14px; border-bottom: 1px solid #EFEDE8; }}
  th {{ background: #FAFAF8; font-weight: 500; color: #5F5E5A; }}
  footer {{ margin-top: 36px; font-size: 12px; color: #888780; text-align: center; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>数据体检报告</h1>
  <div class="meta">
    数据来源：{_esc(source)}　·　
    生成时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}　·　
    共检查 {stats['rows']} 条记录
  </div>

  <div class="cards">
    <div class="card"><div class="num" style="color:#A32D2D">{counts[SEVERE]}</div><div class="label">严重（必须处理）</div></div>
    <div class="card"><div class="num" style="color:#854F0B">{counts[WARN]}</div><div class="label">警告（建议核对）</div></div>
    <div class="card"><div class="num" style="color:#185FA5">{counts[INFO]}</div><div class="label">提示（格式问题）</div></div>
    <div class="card"><div class="num">{health}</div><div class="label">数据健康度（满分 100）</div></div>
  </div>
"""

    body = []
    if not findings:
        body.append('<div class="ok">未发现问题。所有规则均通过。</div>')
    else:
        for level in (SEVERE, WARN, INFO):
            group = [f for f in findings if f.level == level]
            if not group:
                continue
            stroke, fill, text = COLORS[level]
            body.append(f'<div class="sec">{level}问题 · {len(group)} 项</div>')
            for f in group:
                body.append(f"""
  <div class="item" style="border-left-color:{stroke}">
    <div class="top">
      <span class="badge" style="background:{fill};color:{text}">{level}</span>
      <span class="rule">{_esc(f.rule)}</span>
      <span class="loc">{_esc(f.table)} · {_esc(f.where)}</span>
    </div>
    <div class="msg">{_esc(f.message)}</div>
    {f'<div class="advice">建议：{_esc(f.advice)}</div>' if f.advice else ''}
  </div>""")

    table_rows = "".join(
        f"<tr><td>{_esc(t)}</td><td>{n}</td></tr>" for t, n in stats["tables"].items()
    )

    tail = f"""
  <div class="sec">数据概览</div>
  <table>
    <tr><th>数据表</th><th>记录数</th></tr>
    {table_rows}
  </table>

  <footer>由 data-checkup 生成 · 规则可扩展，见 checks.py</footer>
</div>
</body>
</html>
"""
    return head + "".join(body) + tail
