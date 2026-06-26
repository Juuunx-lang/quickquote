# 架构说明

QuickQuote 由 FastAPI 后端和 React 前端组成。

## 后端

主要入口：

- `QuickQuote/app/main.py`
- `QuickQuote/app/api/v1/endpoints/chat.py`
- `QuickQuote/app/workflow/graph.py`

工作流阶段：

```text
extract_stage
  -> multi_source_match_stage
  -> purchase_route_stage
  -> result_stage
```

数据源：

- MySQL 采购记录。
- ERP 商品、库存、成本和采购入库记录。
- SQLite 供应商报价。

## 前端

主要入口：

- `frontend/src/pages/Chat.tsx`
- `frontend/src/components/ChatInput.tsx`
- `frontend/src/components/DatabaseRecords.tsx`
- `frontend/src/components/QuoteExportPanel.tsx`
- `frontend/src/api/index.ts`

前端负责消费 SSE 事件、展示候选卡片、筛选候选分组，并在浏览器端导出 Excel。

## 匹配语义

精确匹配：

- 标准化后字段完全相等。

编码模糊匹配：

- 对编码类字段做标准化后的子串匹配。
- 是否启用由前端“编码模糊”开关控制。

名称匹配：

- 商品名称字段默认允许包含匹配。
