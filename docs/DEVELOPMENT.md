# 天堂支点开发入口

当前首个主题为沉沦者的黑流树海，项目 Python 包统一为 `fulcrum`。产品名称、版本及程序文件名统一定义在 `data/project_info.json`，由服务、页面和打包配置读取。

## 本地运行

在项目根目录使用 Python 3.11、Node.js 24 和 pnpm 11。Windows 截图库单独安装，避免它额外安装另一份非 headless OpenCV：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-service.txt
.venv\Scripts\python.exe -m pip install --no-deps -r requirements-capture.txt
pnpm install --frozen-lockfile
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
.venv\Scripts\python.exe -m fulcrum.service --port 8766
```

打开 `http://127.0.0.1:8766/`。开发服务的存档默认在 `work/app_data`；新桌面包默认使用 `%LOCALAPPDATA%\CFARA`（macOS 为 `~/Library/Application Support/CFARA`），两者不自动混用。API 调试入口为 `/docs`，先通过 `/api/session` 取得本地会话令牌。

旧版 `BlackFlow`、`Fulcrum` 目录不自动迁移或回退读取，旧局需手动导入；新数据配置使用 `CFARA_APP_DATA`，`FULCRUM_APP_DATA`、`BLACKFLOW_APP_DATA` 显式设置仍兼容，优先级依次降低。`--data-dir` 高于环境变量。API 继续使用 `X-Fulcrum-Token`，旧令牌头由兼容入口接受。浏览器的主题、最近对局及隐藏地图页签会无损复制至 `fulcrum-` 偏好键。黑流树海专属 JSON、手册模板和外部网站地址保留原主题名。

前端热更新可另开 `pnpm --dir frontend dev`，本地服务保持运行。桌面包构建及系统依赖见 [打包文档](../packaging/README.md)。

## 目录职责

| 路径 | 职责 |
| --- | --- |
| `frontend/src/` | 玩家界面、地图展示、识别审核及编辑交互，不复制业务算法。 |
| `fulcrum/service/` | 本地 API、后台任务、存档版本校验与确认更新。 |
| `fulcrum/playtime_*` | 结构化对局快照及阅读视图。更新当前实例，不依赖逐步事件日志。 |
| `fulcrum/map_*`、`vision_*` | 统一二维坐标模型、地图模板和截图识别。 |
| `fulcrum/node_predictor.py`、`node_prediction_beta.py` | 生成规则与统计预测；动态条件来自当前地图实例。 |
| `fulcrum/node_scoring.py`、`route_planner.py` | 节点评分、预测资源状态、路线搜索与结果明细。 |
| `assets/`、`data/` | 运行所需的素材与结构化数据；图标和 CV 模板分别维护。 |
| `tests/`、`frontend/tests/` | Python 与前端逻辑回归。 |
| `samples/`、`experiments/` | 固定识图样本和独立算法实验，不进入程序包。 |
| `scripts/`、`packaging/` | 数据维护、界面验证、桌面构建及锁定依赖。 |
| `work/`、`dist/`、`build/` | 本机数据、测试输出和构建产物，均不提交。 |

根目录仅保留 README、Playtime 模板、规则书和数据手册，Roadmap 位于 `docs/`。技术运行入口集中在本页，构建步骤留在 `packaging/`。旧开发设计笔记已清理，当前状态及待办以 [Roadmap](ROADMAP.md) 为准。

运行时只读取结构化 JSON 作为业务数据；Playtime 模板只用于生成阅读视图，不作为存档解析源。应用不解析玩家手改的 Markdown 来恢复状态。数据采集/文档导出脚本是显式维护工具，不由应用自动调用；采集脚本不得回写正在人工补充的正文，临时审阅和基准报告默认输出到 `work/`。

## 评分与查询数据

- `data/scoring/blackflow/default.json`：资源标尺、零件、券、事件、商店、门槛、揭示、出口及搜索默认参数；非数值决策规则列在 `policies` 中，对应业务代码仍实现其合法性。
- `data/scoring/blackflow/relics.json`：每件藏品的池/场景代理分与指定藏品覆盖。
- `data/blackflow_reward_rules.json`、`blackflow_battle_rewards.json`、`blackflow_node_reward_pools.json`：游戏奖励规则和原始观测统计，不因评分校准改动。
- `data/reward_pool_links.json`：节点/事件到藏品和零件池的关联。不同分支分开查询，持有藏品从候选中剔除，原始概率保留但不展示。
- `data/relic_presentation.json`：未来加成分类、全局排序覆盖和八职业新典训附魔规则。当前分类待补，按内部 ID 排序；附魔不自动进阶。

默认评分配置在启动时载入，修改后须重启。未来玩家可选模板的功能名为“沉沦者手册”，本轮未开放编辑、导入或切换界面。局内追猎、结局目标、战力强制判定和留钱额独立保存在 Playtime，不等同于全局评分权重。

## 验证

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests
pnpm --dir frontend test
pnpm --dir frontend build
```

浏览器验证脚本位于 `scripts/smoke_*_ui.mjs`，需要 Playwright，可通过 `FULCRUM_PLAYWRIGHT` 指定模块位置，并通过 `FULCRUM_URL` 指定测试服务。实际对局测试应复制存档到隔离目录，不能直接修改玩家的原始快照。

程序包的 `--self-test` 会逐个请求并解码目录中的图片，同时测试离线 OCR、地图素材和本地服务；`--window-test` 检查真实 WebView2 页面加载。仅页面构建成功不能证明静态资源已进入程序包。
