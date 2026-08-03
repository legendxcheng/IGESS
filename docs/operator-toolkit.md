# 执行策划工具包发布手册

执行策划工具包是 IGESS 的只读、离线调优入口。领域边界见根目录 `CONTEXT.md`，分发与无源码决策见 `docs/adr/0001-*` 和 `docs/adr/0002-*`。

## 导出

准备一个独立 Git 仓库的工作树作为输出目录，并确保本机有 Python 3.11 x64。若当前 IGESS 开发环境本身就是 Python 3.11：

```powershell
python -m igess.cli export-operator-toolkit `
  --project projects/fish `
  --out E:\path\to\igess-operator
```

若当前开发环境不是 Python 3.11，通过 `--python` 指定用于编译字节码的 Python 3.11 x64：

```powershell
python -m igess.cli export-operator-toolkit `
  --project projects/fish `
  --out E:\path\to\igess-operator `
  --python C:\Path\To\Python311\python.exe
```

导出器会：

1. 解析 `operator_cli` 的 IGESS 内部依赖闭包，只复制工作台与正式模拟/报表所需模块。
2. 将 IGESS 与 Fish 生成 schema 编译为 Python 3.11 optimized sourceless `.pyc`。
3. 将 `report.min.js` 作为分发版 `report.js`，不携带第一方未压缩 JS 或 source map。
4. 生成 `operator-manifest.json`、`.igess-delivery-manifest.json`、`start.bat`、依赖清单和执行策划说明。
5. 对临时候选执行不可绕过的白名单和源码路径检查。
6. 按上一版交付清单同步输出目录，不触碰清单外文件。

导出器不会调用 Git。导出成功后必须在分发仓库人工检查：

```powershell
git status --short
git diff
```

确认没有意外交付内容后，再由所有者自行提交和推送。

## 更新报表前端

编辑 `src/igess/reporting/assets/report.js` 后，必须重新生成提交到源码仓库的生产资产：

```powershell
bun build src/igess/reporting/assets/report.js `
  --outfile=src/igess/reporting/assets/report.min.js `
  --minify
```

导出器若找不到 `report.min.js` 会直接失败。

## 执行策划首次安装

分发仓库内的 `使用说明.md` 是执行策划唯一需要的说明。首次安装依赖：

```powershell
py -3.11 -m pip install -r requirements.txt
```

之后双击 `start.bat`。工作台只监听随机的 `127.0.0.1` 端口，历史位于 `%LOCALAPPDATA%\IGESS Operator`。

## 发布验证

仓库测试覆盖输入只读、临时快照、报表/比较/回归、跨版本拒绝、诊断附件选择、源码扫描和受控同步。发布前至少运行：

```powershell
pytest tests/test_operator_toolkit.py -q
```

建议再用实际分发产物与 Fish 生产 JSON 运行一次 `smoke`。

