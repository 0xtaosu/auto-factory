# Auto Factory Inventory Health Demo

本仓库是“库存健康度分析报告”的本地前后端分离 demo。

## 功能范围

- React 前端上传 ERP Excel。
- FastAPI 后端解析库存进出库明细。
- SQLite 保存分析任务和计算结果，不保存原始 Excel。
- 按 PRD 核心算法输出 4 个指标：
  - 库存总资金
  - 呆滞物料占比
  - 出入库平衡度
  - 异常物料检测
- 前端展示 L1 概览和 4 个 L2 下钻详情。

## Backend

```bash
cd backend
python3 -m pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API 地址：

- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/overview`
- `GET /api/jobs/{job_id}/details/{indicator_id}`

## Frontend

```bash
cd frontend
npm install
npm run dev
```

默认前端地址：`http://localhost:5173`

默认后端地址：`http://localhost:8000`

如需修改后端地址：

```bash
VITE_API_BASE=http://localhost:8000 npm run dev
```

## Test

```bash
python3 -m pytest backend/tests
```

样表路径：

`PRD/01-原始数据模板/机械装备企业ERP报表_4亿产值.xlsx`

## Docker Compose Deploy

服务器需要安装 Docker 和 Docker Compose。

### 首次部署

```bash
git clone git@github.com:0xtaosu/auto-factory.git
cd auto-factory
docker compose up -d --build
```

默认访问地址：

`http://服务器IP/`

如果服务器 80 端口已被占用，可以改用其他端口：

```bash
WEB_PORT=8080 docker compose up -d --build
```

访问：

`http://服务器IP:8080/`

### 服务结构

- `frontend`：Nginx 容器，托管 React 静态文件，并把 `/api/*` 代理到后端。
- `backend`：FastAPI 容器，提供 Excel 上传、分析任务、概览和下钻 API。
- `backend_data`：Docker volume，保存 SQLite 数据库。

生产环境前端默认使用同源 `/api`，不需要暴露后端 `8000` 端口。

### 常用命令

查看状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f
```

只看后端日志：

```bash
docker compose logs -f backend
```

停止服务：

```bash
docker compose down
```

停止并删除 SQLite 数据卷：

```bash
docker compose down -v
```

### 更新部署

```bash
git pull
docker compose up -d --build
```

### 反向代理建议

如果服务器前面还有 Nginx、宝塔、1Panel 或云厂商负载均衡，把域名代理到本服务的 `WEB_PORT` 即可。外部只需要开放前端端口，后端通过 Compose 内网访问。
