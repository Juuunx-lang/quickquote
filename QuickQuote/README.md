# QuickQuote 后端当前版说明

更新日期：2026-06-23

后端是 FastAPI 服务，负责商品解析、多源候选召回、聚水潭查询、供应商报价表查询、结果合并和报价上下文归档。

## 1. 技术栈

- Python 3.12
- FastAPI
- SQLAlchemy async
- MySQL
- SQLite
- 聚水潭 OpenAPI
- LLM API

## 2. 关键入口

```text
app/main.py
app/api/v1/endpoints/chat.py
app/workflow/graph.py
```

接口：

- `GET /api/v1/health`
- `POST /api/v1/chat/stream`
- `POST /api/v1/chat/jobs`
- `GET /api/v1/chat/jobs/{job_id}/stream`
- `POST /api/v1/chat/ask`

前端当前不展示追问 UI，但后端接口仍保留。

## 3. 主工作流

当前主流程：

```text
extract_stage
  -> multi_source_match_stage
  -> purchase_route_stage
  -> result_stage
```

说明：

- `extract_stage`：解析输入商品，失败时规则兜底。
- `multi_source_match_stage`：并行查询采购表、聚水潭、供应商报价表。
- `purchase_route_stage`：补齐采购历史、聚水潭库存/成本、动态成本。
- `result_stage`：组装 `items[].candidates[]`。

## 4. 主要服务

```text
app/services/extract_service.py
app/services/order_goods_service.py
app/services/purchase_record_service.py
app/services/jushuitan_service.py
app/services/supplier_quote_service.py
app/services/quote_archive_service.py
app/services/chat_job_service.py
```

## 5. 数据源

### 5.1 采购历史

MySQL 表：

```text
purchase_records
```

用途：

- 最新采购信息
- 历史采购价
- 售价
- 结算价
- 供应商、店铺、订单号、税率、商品链接

### 5.2 聚水潭

用途：

- 商品资料
- 库存
- 最新成本价
- 近 30 天采购入库成本波动

### 5.3 供应商报价表

SQLite 文件：

```text
../brand_item_price/price.db
```

容器内路径：

```text
/brand_item_price/price.db
```

服务代码默认通过 `supplier_quote_service.py` 从项目根目录的 `brand_item_price/price.db` 查找。Docker 部署通过只读挂载满足该路径。

## 6. 匹配规则

精确匹配：

- 标准化后字段完整相等。

编码模糊匹配：

- 开启 `enable_fuzzy_code_match` 后，编码、型号、SKU 字段允许包含匹配。

名称匹配：

- 商品名称默认支持包含匹配。

供应商报价表可独立返回，不要求采购表或聚水潭也存在同一产品。

## 7. 本地启动

```powershell
cd C:\Users\admin\Desktop\work\workspace\QuickQuote\QuickQuote
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

健康检查：

```powershell
curl http://127.0.0.1:8000/api/v1/health
```

## 8. 质量检查

```powershell
..\.venv\Scripts\python.exe -m compileall app
```

已有测试：

```powershell
..\.venv\Scripts\python.exe -m pytest
```

## 9. 环境变量

生产环境必须通过 `.env` 注入真实配置，不要依赖 `config.py` 中的历史默认值。

关键变量：

- `ORDER_DB_*`
- `PURCHASE_DB_*`
- `LLM_API_KEY`
- `LLM_BASE_URL`
- `MODEL_NAME`
- `MODEL_THINK`
- `JUSHUITAN_*`
- `UPLOAD_DIR`
- `QUOTE_ARCHIVE_DIR`

Docker 推荐：

```env
UPLOAD_DIR=/app/uploads
QUOTE_ARCHIVE_DIR=/app/data
JUSHUITAN_TOKEN_CACHE_FILE=/app/data/.jushuitan_token_cache.json
```

## 10. 注意事项

- 后台任务和追问上下文是进程内状态，重启会丢失。
- 供应商报价表是 SQLite 文件，更新后需要替换文件并重启后端。
- 聚水潭动态成本只代表近 30 天采购入库记录，不等同于所有历史成本。
