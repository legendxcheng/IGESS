# Fish 玩家存档模拟模型

实现依据：

- `E:\fish-oasis\gdd\03-存档结构设计.md`
- `E:\fish-oasis\proj\Script\Domain\Player\PlayerArchiveSchema.lua`
- `E:\fish-oasis\proj\Script\Domain\Player\BigNumberSaveAdapter.lua`

## 落点

| 文件 | 职责 |
| --- | --- |
| `src/igess/fish_state.py` | `PlayerState`、Fish 大数 DTO、业务校验、真实存档信封和 Fish checkpoint codec |
| `src/igess/checkpoint.py` | 引擎无关的 `SimulationCheckpoint`、规范化 JSON、边界检查、原子写入 |
| `tests/test_fish_state.py` | 新档、完整存档、引用完整性、配置 ID、大数、深拷贝和 Fish checkpoint 回归 |
| `tests/test_checkpoint.py` | checkpoint 外壳、digest、规范化重写、损坏 JSON 和原子写入回归 |

## 模型边界

`PlayerState` 与正式业务存档的 `data` 一一对应：

```text
meta / production / wallet
torpedo / barbell
fishHall / fish
trashMan
rebirth / collection / automation / statistics
```

序列化时使用正式存档的 `camelCase` 字段。Python 内部使用
`snake_case`，避免把 Lua 命名习惯扩散到模拟逻辑。

这里的一一对应只服务于存档兼容，不代表所有字段都属于 IGESS 模拟范围。
`collection` 等非数值体验字段只做结构校验和原样透传；领域命令、策略和
报表不得读取或修改图鉴、查看状态或图鉴奖励领取状态。

以下内容明确不进入 `PlayerState`：

- FishLuck、TrashLuck、鱼厅 CPS、材料速度和当前容量等推导值。
- 正在飞行的鱼雷、未完成投掷结果和表现状态。
- 玩家策略、模拟统计报告和 RNG 内部状态。
- `model_digest`、模拟时间、随机种子和下一个投掷 ID。

最后一组属于 `SimulationCheckpoint`。checkpoint 的 `engine_state`
就是正式业务存档的 `data`，不维护第二份 Fish 状态结构。

## 与旧模拟计划的口径收敛

正式 GDD 和游戏 Schema 是玩家事实的权威来源：

- 鱼位置只保存 `FishInstance.hallSlot`，不另存部署引用列表。
- 鱼重量保存整数克，鱼实例同时保存等级。
- 大数保存 `{sign, coeff, exp}` 四位有效数字 DTO，不保存十进制字符串。
- 废料处理保存正式 Schema 的当前目标和累计处理秒数。
- 当前投掷结果不保存；落水结算成功后才原子写入奖励事实。
- `statistics.totalThrows` 是长期业务统计；checkpoint 的
  `next_throw_id` 是模拟 RNG 位置，两者不强制相等。新 checkpoint
  默认用前者初始化后者。

## 校验保证

读取存档或 checkpoint 时会拒绝：

- 非规范大数和负资产。
- 未拥有却被选择的鱼雷或杠铃。
- 重复鱼实例 ID、重复鱼厅栏位、超容量栏位和倒退的
  `nextInstanceId`。
- 重复废料、升级或图鉴奖励 ID。
- 已查看但未解锁的图鉴项。
- 当前境界高于历史最高境界。
- 未解锁却启用的自动炸鱼。
- 不存在的配置 ID、异常未来时间戳、未知字段和缺失字段。
- engine ID 或 `model_digest` 不匹配的 checkpoint。

当前版本存档严格校验，不静默补字段。`normalize_player_state()` 只供
新档初始化和显式迁移使用。

## 最小用法

```python
from igess.fish_state import (
    FishCheckpointCodec,
    PlayerState,
)

first_torpedo_id = generated_tables.TbTorpedo.getDataList()[0].id
state = PlayerState.new(
    server_unix_seconds=1_000,
    initial_torpedo_id=first_torpedo_id,
)
checkpoint = FishCheckpointCodec.new(
    state,
    model_digest="sha256:" + "0" * 64,
    scenario_id="day_1_progression",
    profile_id="max_income",
    root_random_seed=20260720,
)

FishCheckpointCodec.write(checkpoint, "player.checkpoint.json")
checkpoint, state = FishCheckpointCodec.read(
    "player.checkpoint.json",
    expected_model_digest="sha256:" + "0" * 64,
)
```

后续经济状态迁移只操作这个 `PlayerState`；策略层只能选择命令，不能
直接绕过领域迁移修改存档字段。
