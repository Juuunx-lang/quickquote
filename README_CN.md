# QuickQuote

QuickQuote 是一个智能报价工作台，用于解析商品需求、从多源召回候选商品、聚合采购历史、ERP 库存/成本和供应商报价数据，并支持人工复核后导出 Excel。

QuickQuote 是一个可配置的报价工作台模板。数据库连接、ERP 集成、LLM Provider、上传目录和运行凭据都通过本地环境变量或部署环境提供。

## 功能特性

- 支持文本输入和多行商品需求。
- 支持浏览器端解析 Excel 行。
- 支持后端工作流处理文件和图片辅助识别。
- 支持多源候选召回：
  - MySQL 采购历史记录。
  - 聚水潭/ERP 商品、库存、成本和采购入库记录。
  - 本地 SQLite 供应商报价表。
- 支持精确匹配和编码字段可选模糊匹配。
- 商品名称字段默认支持模糊搜索。
- 支持候选结果筛选：
  - 全部候选。
  - 采购记录。
  - 供应商报价列表。
- 支持候选卡片和来源面板折叠。
- 支持最新成本价和近 30 天成本波动展示。
- 支持浏览器端 Excel 导出，可选择候选商品和字段。
- 支持 Docker Compose 部署。

## 架构

```text
quickquote/
├── QuickQuote/             # FastAPI 后端
├── frontend/               # React + TypeScript + Vite 前端
├── brand_item_price/       # 供应商报价表 schema 和说明
├── docs/                   # 技术文档
├── docker-compose.yml
└── .env.docker.example
```

后端技术栈：

- FastAPI
- SQLAlchemy async
- MySQL
- SQLite
- 聚水潭 OpenAPI
- LLM API

前端技术栈：

- React 18
- TypeScript
- Vite
- Zustand
- Tailwind CSS
- xlsx

## 快速开始

复制环境变量模板：

```bash
cp .env.docker.example .env
```

填入你自己的运行配置：

```env
ORDER_DB_HOST=
ORDER_DB_USER=
ORDER_DB_PASSWORD=
ORDER_DB_NAME=

PURCHASE_DB_HOST=
PURCHASE_DB_USER=
PURCHASE_DB_PASSWORD=
PURCHASE_DB_NAME=

LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1

JUSHUITAN_APP_KEY=
JUSHUITAN_APP_SECRET=
JUSHUITAN_ACCESS_TOKEN=
JUSHUITAN_REFRESH_TOKEN=
```

使用 Docker Compose 启动：

```bash
docker compose up -d --build
```

访问：

```text
http://localhost:3000
```

健康检查：

```bash
curl http://127.0.0.1:3000/api/v1/health
```

## 供应商报价 SQLite

供应商报价源默认读取：

```text
brand_item_price/price.db
```

你可以参考 `brand_item_price/schema.sql` 自行创建 SQLite 数据库文件，用于保存自己的供应商报价数据。

Docker Compose 会将目录挂载为：

```yaml
./brand_item_price:/brand_item_price:ro
```

## 本地开发

后端：

```bash
cd QuickQuote
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

前端类型检查：

```bash
cd frontend
npm run check
```

后端语法检查：

```bash
cd QuickQuote
python -m compileall app
```

## 文档

- `README.md`: 英文项目说明
- `README_CN.md`: 中文项目说明
- `docs/architecture.md` / `docs/architecture_CN.md`
- `docs/development.md` / `docs/development_CN.md`
- `docs/deployment.md` / `docs/deployment_CN.md`
- `docs/troubleshooting.md` / `docs/troubleshooting_CN.md`
- `DOCKER_DEPLOY.md` / `DOCKER_DEPLOY_CN.md`

## 运行配置

建议以 .env.docker.example 为起点创建本地 .env。数据库、LLM、ERP 和 SQLite 报价库等运行配置应放在本地环境变量或部署平台的 secret manager 中。
