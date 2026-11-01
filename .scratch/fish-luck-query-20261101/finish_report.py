from pathlib import Path
import json
HERE=Path(__file__).resolve().parent
summary=json.loads((HERE/'final-summary.json').read_text())
assert summary['candidate_range'][1] < summary['baseline_range'][0], 'Timing ranges overlap; review uncertainty before adoption'
assert summary['short']['candidate'] < summary['short']['baseline'], 'Short scenario regressed'
checks=json.loads((HERE/'registry-checks.json').read_text())
comparisons=json.loads((HERE/'pinned-final-comparisons.json').read_text())
assert len(comparisons)==4 and all(c['core_bytes_identical'] and c['checkpoint_and_ordered_history_identical'] for c in comparisons)
accepted=[row for row in checks if row['accepted_for_performance']]
assert len(accepted)==8
report=HERE/'verification.md'
content=report.read_text(encoding='utf-8')
content=content.replace('实现与功能等价验证已完成；三组隔离、串行 Week1 正式计时进行中。本文中的早期耗时不构成最终性能结论。',
    f"实现、功能等价和三组固定性能核的串行 Week1 对照已完成。端到端中位数 {summary['baseline_median']:.3f} → {summary['candidate_median']:.3f} 秒，耗时降低 {summary['reduction_percent']:.2f}%（速度比 {summary['speedup']:.3f} 倍）。这是本次固定输入场景与受控运行条件下的测量，不是全部运行环境的保证。")
table=['## 最终正式配对','', '| 顺序 | 基线（秒） | 候选（秒） | 耗时降低 |', '| --- | ---: | ---: | ---: |']
for pair,order in zip(summary['pairs'],('基线→候选','候选→基线','基线→候选')):
    table.append(f"| {pair['pair']}：{order} | {pair['baseline_seconds']:.3f} | {pair['candidate_seconds']:.3f} | {pair['reduction_percent']:.2f}% |")
b=summary['baseline_range'];c=summary['candidate_range'];short=summary['short']
table.extend(['',f"基线范围 {b[0]:.3f}～{b[1]:.3f} 秒；候选范围 {c[0]:.3f}～{c[1]:.3f} 秒。短场景 Day1 {short['baseline']:.3f} → {short['candidate']:.3f} 秒，耗时降低 {(1-short['candidate']/short['baseline'])*100:.2f}%。",'',
    '八条最终正式运行均通过公共 `igess runs show/artifacts --json` 复核：success、identity_complete、登记产物齐全，源代码/导表/适配器身份符合冻结记录，完整执行窗口正确。三组 Week1 与一组 Day1 核心字节、checkpoint 全部业务状态和有序历史均一致；比较器负例均被拒绝。最终进程监控记录未发现外部 Lua 重叠。', '',
    '原始回执见 `pinned-*.json`；最终统计见 [final-summary.json](final-summary.json)，运行顺序见 [pinned-final-order.json](pinned-final-order.json)，等价比较见 [pinned-final-comparisons.json](pinned-final-comparisons.json)，运行登记核验见 [registry-checks.json](registry-checks.json)。', '',
    '## 最终运行 ID','', '| 场景与组 | 基线 | 候选 |','| --- | --- | --- |'])
for tag,scenario in [('pinned-final1','week_1_growth'),('pinned-final2','week_1_growth'),('pinned-final3','week_1_growth'),('pinned-short','day_1_growth')]:
    rows=[json.loads((HERE/f'{tag}-{v}-{scenario}.json').read_text()) for v in ('baseline','candidate')]
    table.append(f"| {tag} / {scenario} | `{rows[0]['response']['result']['run_id']}` | `{rows[1]['response']['result']['run_id']}` |")
content=content.replace('## 交付范围','\n'.join(table)+'\n\n## 交付范围')
content=content.replace('性能结论待正式配对完成后填入。','本次采用该优化：受控配对证明整周收益，原查询/抛投业务行为与恢复历史保持等价。')
report.write_text(content,encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k!='cpu_condition'},indent=2))
