# QuickQuote 版本说明

Version: v0.2.0-current
Date: 2026-06-23

## 范围

- 当前可用的智能报价工作流版本。
- 支持三源候选召回：采购记录、聚水潭/ERP、供应商报价 SQLite。
- 明确精确匹配和编码模糊匹配语义。
- 支持最新成本价和近 30 天采购入库成本波动展示。
- 支持候选记录、采购记录、报价列表筛选。
- 候选卡片和来源面板支持展开/折叠。
- 支持浏览器端 Excel 导出，可选择候选记录、具体商品和字段。
- Docker 部署文件支持供应商报价数据库挂载和 `/app/data` 持久化。
- 开源版已清理私有凭据、私有 SQLite 数据和运行产物。

## 注意

- `.env.docker.example` 只是占位模板。
- 真实 `.env`、数据库密码、LLM Key、聚水潭 token 不应提交仓库。
- 开源版不包含私有 `brand_item_price/price.db`，请根据 `brand_item_price/schema.sql` 自行创建。
