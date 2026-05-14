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
