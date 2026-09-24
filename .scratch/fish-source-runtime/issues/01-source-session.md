# Fish 源工程统一 Lua 会话接口

Status: ready-for-agent
Implementation: completed

在源项目维护独立于 DS 的薄宿主，复用生产 Application/Domain 服务，支持创建、查询、显式操作、时间推进、随机输入、回执和拒绝码。业务存档仅由源 Lua 修改，JSON Lines 协议区分拒绝与故障。

验收：鱼厅待领/领取/升级、背包鱼、鱼雷、杠铃、投掷全生命周期、垃圾处理、突破/重生和离线奖励都能经统一会话入口驱动；源服务交易与幂等逻辑不能由 IGESS 复制。

## Comments

- 2026-09-24：实现于 `E:\fish-oasis\simulation` 及 FishThrowService/ServerThrowSeedProvider 的隔离实例接缝；`tests/simulation_host_test.lua` 和 `tests/simulation_cli_test.py` 已验证。
