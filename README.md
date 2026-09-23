# Inventory Activity MVP

基于真实 ERP 出入库流水计算物料活跃度，输出可追溯的“长期无交易物料候选”。
默认观察日与数据窗口来自 `config/inventory-activity.yaml`，策略来自
`config/slow-moving-policy.yaml`。新分析链不调用 LLM，也不要求 API Key。

## 范围与口径

- DaysSinceLastMovement：观察日减最后一次有效入库或出库日期。
- MovementFrequency：明确窗口内的有效独立事件数。
- AnnualOutboundQuantity：观察年份截至观察日的出库数量，按物料、同单位汇总。
- 可选指标包括年度进出库金额、入库数量、进出库频率和分别的末次进出库天数。
- 默认策略 `>= 180 天`，阈值只存在于配置中；可通过 CLI/API 覆盖，结果保存独立策略快照。
- 只有流水，没有可靠库存余额，因此候选不等于有库存，也不代表真实积压或报废。
- 数据存在左截断，365 天以上状态无法完整观测，全年没有流水的物料可能不在样本中。

旧 `analysis.py`、`excel_parser.py`、`llm_agent.py` 和历史 PRD 留作历史参考，
默认 API 已切换到独立模块 `backend/app/inventory_activity/`，不再运行旧健康度算法。
历史 `/api/jobs` 接口已退役，新接口统一使用 `/api/activity`。

## 安装与运行

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
PYTHONPATH=backend .venv/bin/python -m app.inventory_activity \
  'PRD/01-原始数据模板/机械装备企业ERP报表_4亿产值.xlsx'
```

默认生成：

- `data/processed/materials.{json,jsonl,csv}`
- `data/processed/movement_events.{json,jsonl,csv}`
- `data/processed/metric_observations.{json,jsonl,csv}`
- `data/processed/activity_assessments.{json,jsonl,csv}`
- Department、Supplier 和 source_records 的同格式文件
- `data/processed/inventory-activity.ttl`、`result.json`、`manifest.json`、`policy.json`
- `data/processed/source.xlsx`：原始文件副本
- `reports/inventory-activity-mvp.md`：质量报告、EXPECTED/ACTUAL/DIFF、语义冲突处理

生成数据已加入 `.gitignore`，避免将大体积 ERP 衍生产物提交到 Git。
保留数据目录即可复核；按相同输入与配置重跑会得到相同实体 ID。

```bash
# 调整阈值并打印某个物料的证据链
PYTHONPATH=backend .venv/bin/python -m app.inventory_activity \
  'PRD/01-原始数据模板/机械装备企业ERP报表_4亿产值.xlsx' \
  --threshold-days 90 --explain GC010 --output /tmp/activity-90d \
  --report /tmp/activity-90d/report.md
```

其他参数：`--policy PATH`、`--settings PATH`、`--observation-date YYYY-MM-DD`。
观察日必须位于声明的数据覆盖范围内。频率窗口与年度统计窗口分别记录，
观察日后的事件保留为事实但不参与当次计算。日期范围来自输入包覆盖声明，
实际首末事件日期另外记录，不把两者混为一谈。

## API

```bash
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --reload --port 8000
```

OpenAPI：`http://127.0.0.1:8000/docs`。

| 接口 | 用途 |
|---|---|
| `GET /api/activity/config` | 默认日期、窗口、策略 |
| `POST /api/activity/jobs` | multipart 上传 file；可带 observation_date、threshold_days |
| `GET /api/activity/jobs/{id}` | 任务状态和质量概览 |
| `GET /api/activity/jobs/{id}/overview` | 统计、分布、策略、观察边界 |
| `GET /api/activity/jobs/{id}/assessments` | q 搜索、inactive_only 筛选、offset/limit 分页 |
| `GET /api/activity/jobs/{id}/materials/{code}/explanation` | 原始行、末次事件、指标和策略证据 |
| `GET /api/activity/jobs/{id}/download/{format}` | json、csv、ttl、report 下载 |

上述接口现在需要管理员会话或 API Key，详见下方 MCP 与凭据管理。
任务默认保存至 `backend/data/activity/`：SQLite 索引、原始 Excel、不可混用的每次任务产物。
可用 `ACTIVITY_DATA_DIR` 修改位置。失败任务返回 failed，不能读取为健康或零候选结果。
MVP 为同步处理，完整 RDF 导出包含全部原始行证据，上传分析可能需要数十秒。
API 契约见 [设计文档](docs/inventory-activity-design.md)。

## 数据处理与可追溯性

- 原始值与标准化值分开保存；日期、编码、交易类型、数值逐行校验。
- 非空来源序号及整行原始值均相同才去重；疑似重复仍保留独立事件。
- 无效行、明确重复行仍在 source_records 中保留，附错误、警告或 duplicate_of。
- 金额缺失/非法时保留可用交易事实，但相关金额指标为 null，绝不补零。
- 同一物料的年度事件单位冲突时，数量合计为 null，不擅自换算。
- 同日末次事件全部关联；单条展示按 Excel 行号稳定选取，不伪造时序。
- 文件 SHA256、工作表、Excel 行号、原始序号构成来源定位证据。
- 策略快照和运行 ID 绑定输入、时间窗口及策略，调整配置不改变旧评估。
- CSV 防止公式注入；精确原值和嵌套证据请使用 JSON/RDF。

应用本体定义在 `ontology/inventory-activity.ttl`。IOF 仅作参考关系，不完整导入，
不对 ERP 记录与物理过程声明强等价。M6-01-02 仅以应用命名空间的诊断支持目标关联，
未新增或重编号 L1；后续获得正式指标图谱 IRI 后可配置统一映射。

## SPARQL 与测试

`queries/` 下四个 `.rq` 文件可直接用于导出的 Turtle：候选阈值查询、GC010 末次事件、
评估使用的策略、候选完整原因。跨多次运行合并图谱时，应再按 observationDate/run 过滤。

```bash
.venv/bin/python -m pytest backend/tests -q --disable-warnings
```

测试覆盖 179/180/181 天、只有入库/出库、同日交易、12 月 31 日、异常字段、
金额/供应商缺失、重复、单位冲突、未来交易、策略有效期、原始证据、RDF 查询和 API 持久化。
真实数据基线为 12,794 笔、820 个物料、13 个 >=180 天候选；报告不强制对齐旧统计。
GC010 实际末次交易日是 2025-12-08，末次动用 23 天。
真实输入另有 816 个编码存在主数据属性冲突，531 个存在单位冲突；这些物料的
年度出库总量标记不可用，并保留分单位数量。该问题不通过补造换算关系解决。

## 前端与部署

前端已由 Grok 实现，接入 `/api/activity`：上传、日期/阈值、概览、搜索分页、
候选筛选、原始行追溯和四种格式下载。单位冲突以不可用总量和分单位数量展示。
主代理使用真实 ERP 文件完成浏览器联调，包含桌面和移动端检查。

```bash
cd frontend
npm install
npm run dev
```

默认前端地址 `http://localhost:5173`，开发 API 使用当前页面主机名的 8000 端口，
可用 `VITE_API_BASE` 覆盖；显式配置时请保持前后端主机名一致。

```bash
cp .env.example .env
docker compose up -d --build
```

Compose 的 backend_data 卷持久保存原始 Excel、SQLite 和任务产物，
Nginx 将 `/api/*` 转发后端。默认 WEB_PORT=80，无需 DeepSeek 配置。
生产构建：在 `frontend` 目录运行 `npm run build`。本次验证为本地验证，未部署到远端。

## MCP 与独立 API Key

服务提供 `/mcp` Streamable HTTP 接口，使用官方 MCP Python SDK 2.2.0。
支持自定义 Authorization 请求头的客户端；本版本不是 OAuth 登录服务，
不能直接承诺支持仅接受 OAuth 的客户端。

首次启动会在 `backend/data/activity/auth/admin-token` 创建本机管理员凭据，
文件权限为 0600，不在服务器日志或 API 中展示。在项目根目录本机终端读取：

```bash
PYTHONPATH=backend .venv/bin/python -m app.security show-admin-token
```

Docker 部署读取方法：

```bash
docker compose exec backend python -m app.security show-admin-token
```

在网页用该凭据登录，打开 **MCP / API Keys** 创建 Key。完整 Key 仅创建时显示一次，
之后只能查看前缀、权限、到期时间、最近使用时间或撤销；数据库只保存高熵 Key 的摘要。
独立 Key 不能签发其他 Key，撤销一个不会影响其他 Key。

- `activity:read`：默认必选；读取本项目全部任务、评估、追溯和导出。
- `activity:analyze`：可选；另外允许通过 REST API 上传 ERP 并创建分析任务。
- 管理员网页会话有效期 8 小时，HttpOnly Cookie，不把凭据存入 localStorage。
- MCP 只接受 API Key，不接受管理员登录凭据或浏览器 Cookie。
- 这是单项目权限，不是按 Key 隔离的数据集；所有 Key 均可读取已有项目数据。
- 到期/撤销 Key 在后续 MCP 和 REST 请求中都立即失效，不允许 URL 查询参数传 Key。

六个只读 MCP 工具：`list_jobs`、`get_job`、`get_overview`、`list_assessments`、
`explain_material`、`get_export_info`。最后一个返回文件信息与鉴权下载路径，
不会把大型 RDF 塞进模型上下文，也不会生成带密钥的 URL。

通用连接配置（具体字段以所用客户端为准）：

```json
{
  "mcpServers": {
    "inventory-activity": {
      "url": "https://your-host.example/mcp",
      "headers": {"Authorization": "Bearer <YOUR_API_KEY>"}
    }
  }
}
```

官方 Python 客户端示例见 `backend/mcp_client_example.py`；通过环境变量
`INVENTORY_API_KEY` 和可选 `INVENTORY_MCP_URL` 配置，不把真实 Key 写入代码。
同一个 Key 可通过 `Authorization: Bearer <YOUR_API_KEY>` 调用现有 REST 接口。

管理员接口：`POST /api/auth/login`、`GET /api/auth/session`、`POST /api/auth/logout`；
`GET/POST /api/admin/keys`、`DELETE /api/admin/keys/{key_id}`、`GET /api/admin/mcp`。
Key 管理仅接受管理员会话，浏览器写入请求必须带受信任的 Origin。

远端部署时，在 `.env` 配置实际的 `INVENTORY_ALLOWED_ORIGINS`（完整 HTTPS origin，含非默认端口）
和 `INVENTORY_ALLOWED_HOSTS`（MCP 请求 Host，可用 `example.com:*`），设置
`INVENTORY_COOKIE_SECURE=true` 并由 HTTPS 反向代理提供服务。不要填通配 Origin。
本地浏览器请保持同一主机名访问前后端（如都用 localhost），以便 SameSite Cookie 生效。
可选 `INVENTORY_ADMIN_TOKEN` 覆盖随机本机凭据，必须至少 32 字符；更换它会使现有管理员会话失效。
`INVENTORY_AUTH_DIR` 可覆盖凭据存储目录；该目录与 ERP 数据一样需要持久化并保持私有。
API Key 不因管理员登录凭据轮换自动撤销，需要在管理页单独撤销。
