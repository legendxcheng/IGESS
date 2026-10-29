"""Publish approved tickets and freeze this round without changing existing work."""
from pathlib import Path
import json
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=Path('.tmp/fish-state-advance').resolve()
SOURCE=Path('E:/fish-oasis')
tickets=[
('baseline','冻结新基线与建立逐次观察差分','None (can start immediately)',
 '正式运行可输出本轮基线及逐次完整逻辑观察，准确区分业务差异与代码身份差异。',
 ['冻结实际源码、适配器、配置和导表，保留现有工作区及历史证据。','完成首日/整周基线；记录完整最终状态、核心产物、源历史及恢复字段。','逐次观察差分不添加业务操作，诊断与无探针测速分开；负例能发现篡改。']),
('inventory-observation','背包状态按变化传输，打通完整流程','01：冻结新基线与建立逐次观察差分',
 '背包未变化时避免重复传输，正式策略和报告仍在原有观察点消费完整独立状态。',
 ['保留完整查询与能力回退，显式区分完整基准与变化响应。','覆盖首次观察、基准错配、删除/空集合、查询选项、对象隔离及恢复重建。','观察操作不进入业务历史，不改变时间、随机数或 revision。','通过源接口及正式运行差分；先记录失败测试，再实现。']),
('stable-observation','扩展稳定状态复用，验证查询路线收益','02：背包状态按变化传输，打通完整流程',
 '将有实测收益的稳定状态部分纳入复用，保持动态余额和成长观察及时更新。',
 ['依据真实依赖覆盖鱼厅、图鉴等有收益的投影；不机械扩大缓存。','捕获、出售、升级、装备、重生、解锁和领取后观察立即正确。','逐次完整状态、核心产物、源历史及恢复行为一致。','独立查询候选完成整周正式性能对照，不用局部编码成绩替代。']),
('production-reuse','复用稳定生产计算，减少重复结算开销','01：冻结新基线与建立逐次观察差分',
 '真实推进中复用输入未变化的纯生产结果，结算金额、回执与事务行为保持精确。',
 ['归因生产计算成本；按真实依赖隔离会话/规则及返回大数。','鱼、神兽参考鱼、倍率和重生变化立即生效；错误不被旧成功缓存掩盖。','不跳过校验、不改变舍入、不缓存整份结算回执。','准确模式对照、恢复及独立整周收益有证据；无收益候选不接入。']),
('event-boundaries','按真实事件边界分段推进','01：冻结新基线与建立逐次观察差分',
 '减少定时事件导致的不必要逐秒回落，保持事件时点、同刻顺序及截断恢复行为。',
 ['先确认回落来源，按真实定时器、孵化、buff 和观察边界分段。','覆盖边界前/上/后、非整数时间、满包与容量恢复及待完成副作用。','准确模式的完整状态、最终回执、revision 和随机结果一致。','记录独立性能和等价证据；无法证明等价或收益时保留原路径并明确结论。']),
('acceptance','组合优化与最终整周验收','03：稳定状态复用；04：生产计算复用；05：事件边界推进',
 '整合已证实的候选，用实际交付字节证明整周更快且业务结果不变。',
 ['三组同机串行无探针整周配对均更快，中位收益超出基线波动；首日无稳定回退。','全部逻辑观察、核心产物、完整最终状态、源历史与恢复等价；完成所需全套回归和类型检查。','完成 Standards/Spec 双轴审查，修复阻塞问题并同步说明、技能和代码导航。','只提交本次精确文件或补丁，保留用户工作，不推送或发布执行工具包。'])]
for i,(slug,title,blockers,delivery,criteria) in enumerate(tickets,1):
    path=HERE/'issues'/f'{i:02d}-{slug}.md'
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        path.write_text(f'# {i:02d}: {title}\n\n**What to build:** {delivery}\n\n**Blocked by:** {blockers}\n\nStatus: ready-for-agent\n\n'+''.join(f'- [ ] {c}\n' for c in criteria),encoding='utf-8')
if ROOT.exists():
    raise SystemExit('Freeze already exists; refusing to overwrite')
ROOT.mkdir()
for part in ('proj/Script','simulation','igess_export/json','tests'):
    shutil.copytree(SOURCE/part,ROOT/'baseline-source'/part)
shutil.copytree(ROOT/'baseline-source',ROOT/'candidate-source')
shutil.copytree('src',ROOT/'baseline-igess-src',ignore=shutil.ignore_patterns('__pycache__'))
shutil.copytree(ROOT/'baseline-igess-src',ROOT/'candidate-igess-src')
project=ROOT/'project'; project.mkdir()
for name in ('Datas','luban_exports'):
    shutil.copytree(Path('projects/fish_source')/name,project/name)
shutil.copy2('projects/fish_source/economy.yaml',project/'economy.yaml')
for name,repo in [('igess',Path.cwd()),('source',SOURCE)]:
    prefix=['git','-c',f'safe.directory={repo.as_posix()}','-C',str(repo)]
    (ROOT/f'{name}-before.diff').write_bytes(subprocess.check_output(prefix+['diff','--binary']))
    (ROOT/f'{name}-status.txt').write_bytes(subprocess.check_output(prefix+['status','--short']))
    (ROOT/f'{name}-head.txt').write_bytes(subprocess.check_output(prefix+['rev-parse','HEAD']))
sys.path.insert(0,str(ROOT/'baseline-igess-src'))
from igess.fish_source_runtime import source_code_digest,data_snapshot_digest
from igess.fish_source_engine import _integration_code_digest
identity=dict(source=source_code_digest(SOURCE),adapter=_integration_code_digest(),
              data=data_snapshot_digest(SOURCE/'igess_export/json'))
(HERE/'baseline-identity.json').write_text(json.dumps(identity,indent=2),encoding='utf-8')
shutil.copyfile('.scratch/fish-source-query-performance/benchmark.py',HERE/'benchmark.py')
shutil.copyfile('.scratch/fish-source-query-performance/compare.py',HERE/'compare.py')
print(json.dumps(identity))
