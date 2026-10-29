"""Publish completed acceptance receipts without touching unrelated work."""
from pathlib import Path
import json
import subprocess

HERE = Path(__file__).resolve().parent
summary = json.loads((HERE / "results/final-summary.json").read_text(encoding="utf-8"))
comparisons = json.loads((HERE / "results/final-comparisons.json").read_text(encoding="utf-8"))
identity = json.loads((HERE / "final-identity.json").read_text(encoding="utf-8"))
weekly, daily = (summary[key] for key in ("week_1_growth", "day_1_growth"))
assert weekly["all_pairs_faster"]
assert weekly["baseline_median"] - weekly["candidate_median"] > weekly["baseline_range"][1] - weekly["baseline_range"][0]
assert daily["all_pairs_faster"], "Inspect first-day variation before completing acceptance"
assert len(comparisons) == 6
baseline_identity = json.loads((HERE / "baseline-identity.json").read_text(encoding="utf-8"))
for row in comparisons:
    for variant, expected in (("baseline", baseline_identity), ("combined", identity)):
        receipt = json.loads((HERE / "results" / f'{row["tag"]}-{variant}-{row["scenario"]}.json').read_text(encoding="utf-8"))
        runtime = receipt["source_runtime"]
        assert runtime["code_sha256"] == expected["source"]
        assert runtime["integration_code_sha256"] == expected["adapter"]
        assert runtime["selected_export_sha256"] == expected["data"]
assert json.loads((HERE / "results/negative-control.json").read_text())["detected"]
full_suite = (HERE / "logs/full-python.log").read_text(encoding="utf-8")
assert "1667 passed, 8 skipped, 16 deselected" in full_suite

lines = ["# Fish 状态观察与推进性能验收", "",
         "状态：实现、技术验收与双轴审查完成，等待用户验收。", "",
         "本轮保留 Python + 同源 Lua，接入变化状态传输、内部稳定投影复用及会话独立的冻结生产计算。导表、玩家策略、随机、大数精度、观察时点与采样保持不变。", "",
         "## 最终性能", "",
         "三组整周与两组首日均按基线 → 候选串行执行，无剖析或逐次诊断记录，也未并行执行测试或其他模拟。整机测速开始前 CPU 为 15%，既有后台服务未停止，因此结论是该机器同一时段配对结果。", "",
         "| 场景/组 | 基线秒 | 候选秒 |", "| --- | ---: | ---: |"]
for row in comparisons:
    if not row["diagnostic_only"]:
        lines.append(f'| {row["scenario"]} / {row["tag"]} | {row["baseline_seconds"]:.3f} | {row["candidate_seconds"]:.3f} |')
lines += ["", f'整周中位数 {weekly["baseline_median"]:.3f} → {weekly["candidate_median"]:.3f} 秒，耗时减少 **{weekly["median_reduction_percent"]:.2f}%**。中位耗时下降 {weekly["baseline_median"] - weekly["candidate_median"]:.3f} 秒，高于基线极差 {weekly["baseline_range"][1] - weekly["baseline_range"][0]:.3f} 秒；候选范围 {weekly["candidate_range"][0]:.3f}–{weekly["candidate_range"][1]:.3f} 秒也整体低于基线范围 {weekly["baseline_range"][0]:.3f}–{weekly["baseline_range"][1]:.3f} 秒。',
          f'首日中位数 {daily["baseline_median"]:.3f} → {daily["candidate_median"]:.3f} 秒，耗时减少 {daily["median_reduction_percent"]:.2f}%，两组均无回退。',
          "", "原始耗时与范围见 [汇总](results/final-summary.json)，顺序见 [运行顺序](results/final-order.json)。分母是本轮实施前已交付优化版，不使用上一轮优化前数据。", "",
          "## 等价与身份", "",
          "- 独立诊断比较 7,573 次完整逻辑状态及 includeLuck 选项，序列一致。篡改首个状态哈希的负例被比较器拒绝。诊断耗时未计入性能成绩。",
          "- 所有最终配对的四份核心业务产物逐字节相等，完整最终 Query DTO、checkpoint 行为字段及源操作/回执历史相等（整周 7,573 条，首日 1,099 条）；只放行代码身份、路径和耗时元数据。",
          "- 源实现及全部参与摘要的适配文件已核对工作区与最终冻结副本逐字节一致。测试使用同一工作区已有用户改动，专属提交只包含本轮补丁。",
          f'- 源摘要：`{identity["source"]}`', f'- 适配摘要：`{identity["adapter"]}`', f'- 导表摘要：`{identity["data"]}`',
          "", "## 回归与审查", "",
          "- 全套 Python：1667 passed、8 skipped、16 deselected，耗时 1211.64 秒。收集测试后新增的同进程重复会话拒绝边界，连同其他观察测试另跑 8 项全部通过。",
          "- 源侧选定回归：14 项通过；鱼潮测试的高阶枪成本断言在冻结基线与最终候选同一行失败，为已有夹具问题，未修改生产数值或原断言。不是完整源仓测试全绿。",
          "- 新增冻结生产与普通计算器对照，覆盖依赖变化、神兽参考鱼、非法输入后的拒绝/恢复、大数返回隔离及独立倍率实例。",
          "- 新模块、运行时、测试与本轮工具类型检查通过。engine 的两处 Mapping 类型错误在冻结原文件也复现，保留为已有问题。",
          "- [Standards/Spec 双轴审查](review.md)：公开动作查询的全局变量误用已修复，两项验收证据缺口已补齐，无剩余审查问题。",
          "", "## 独立候选与取舍", "",
          "| 候选 | 单次整周秒 | 结论 |", "| --- | ---: | --- |",
          "| 本轮基线 | 197.157 | 冻结对照 |", "| 状态观察 | 177.382 | 最终采用 |",
          "| 冻结生产复用 | 190.133 | 最终采用 |", "| 事件分段 | 202.712 | 核心产物/最终状态/历史相等，但未证明收益，丢弃 |",
          "", "独立候选数据仅用于筛选，不相加推断组合收益。事件分段在收益筛选处停止，未完成全部边界测试，不进入交付；最终仍使用原准确/批量推进算法。", "",
          "## 交付边界", "",
          "说明、RoadMap、Fish 技能和代码导航已同步。用户既有修改保留，22 份无关原有差异逐块核对不变。未推送，未构建或发布 GameBalancer，未进行 UE/PIE/DS 验收。", "",
          "详细回执见 `results/`，测试日志见 `logs/`，原始冻结源码和正式产物留在 `.tmp/fish-state-advance/`。", ""]
(HERE / "verification.md").write_text("\n".join(lines), encoding="utf-8")

for issue in sorted((HERE / "issues").glob("*.md")):
    body = issue.read_text(encoding="utf-8")
    if issue.name.startswith("05-"):
        body = body.replace("Status: ready-for-agent", "Status: wontfix")
        body = body.replace("- [ ] 先确认", "- [x] 先确认").replace("- [ ] 记录独立", "- [x] 记录独立")
        comment = "事件分段原型整周 202.712 秒，基线 197.157 秒，未证明收益。核心产物、最终状态和源历史相等；依据规格停止该候选，未继续完成边界专项验收，未接入交付。准确/批量推进保留原实现。"
    else:
        body = body.replace("Status: ready-for-agent", "Status: ready-for-human").replace("- [ ]", "- [x]")
        comment = "本票实现与技术验收完成；状态转为用户验收，运行结果、已有失败边界和审查修正见 [验收记录](../verification.md)。"
    issue.write_text(body.rstrip() + "\n\n## Comments\n\n2026-10-29：" + comment + "\n", encoding="utf-8")
spec = HERE / "spec.md"
body = spec.read_text(encoding="utf-8").replace("Status: ready-for-agent", "Status: ready-for-human", 1)
spec.write_text(body.rstrip() + "\n\n## Implementation Result\n\n2026-10-29：用户已授权实施，技术验收完成，等待用户验收。状态观察与冻结生产复用已交付；事件分段未证明收益而丢弃。最终证据见 [验收记录](verification.md)。\n", encoding="utf-8")
commits = {label: subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
           for label, repo in (("igess_implementation", "E:/IGESS"), ("source", "E:/fish-oasis"))}
(HERE / "implementation-commits.json").write_text(json.dumps(commits, indent=2), encoding="utf-8")
print(json.dumps(summary, indent=2))
