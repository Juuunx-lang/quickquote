# QuickQuote 前端当前版说明

更新日期：2026-06-23

前端是 React + TypeScript + Vite 工作台，负责输入采集、SSE 报价流消费、候选结果展示、结果筛选和 Excel 导出。

## 1. 技术栈

- React 18
- TypeScript
- Vite
- Zustand
- Tailwind CSS
- lucide-react
- xlsx

## 2. 关键文件

```text
src/pages/Chat.tsx
src/components/ChatInput.tsx
src/components/DatabaseRecords.tsx
src/components/QuoteExportPanel.tsx
src/components/ProgressIndicator.tsx
src/api/index.ts
src/store/useChatStore.ts
src/lib/excelParser.ts
```

## 3. 当前页面结构

左侧：

- 输入框
- 编码模糊匹配开关
- 候选记录 / 采购记录 / 报价列表三个筛选按钮
- 检索进度

右侧：

- 当前状态：等待提交 / 正在检索 / 本轮结束 / 需要重试
- Excel 导出面板
- 候选结果卡片

## 4. 筛选规则

候选记录：

- 展示所有候选。

采购记录：

- 候选 `matched_sources` 包含 `purchase_records` 或 `jushuitan`。

报价列表：

- 候选存在供应商报价字段或 `supplier_quote_records`。

注意：聚水潭近 30 天入库动态成本记录不能作为“采购记录”筛选依据，它只用于成本波动按钮。

## 5. 候选卡片

基础字段：

- 产品名
- 品牌
- 型号（sku_id）
- 规格

来源面板：

- 最新采购信息
- 聚水潭来源
- 供应商报价

面板规则：

- 默认打开第一个有内容的来源。
- 无内容来源只显示“无”，不可展开。
- 每条候选卡片本身支持展开和闭合。

## 6. Excel 导出

组件：

```text
src/components/QuoteExportPanel.tsx
```

能力：

- 选择候选记录分组
- 选择具体候选产品
- 选择导出字段
- 下载 `.xlsx`

导出文件名：

```text
QuickQuote报价_YYYYMMDD_HHmm.xlsx
```

字段分组：

- 基本字段
- 采购历史记录
- 聚水潭来源
- 供应商报价

默认字段包括：

- 候选记录
- 产品名
- 品牌
- 型号
- 规格
- 采购日期
- 数量
- 采购价
- 售价
- 结算单价
- 结算金额
- 采购供应商
- 店铺名
- 库存
- 最新成本价
- 成本价日期
- 报价供应商
- 报价
- 报价更新时间

## 7. API 对接

封装文件：

```text
src/api/index.ts
```

默认 API 前缀：

```text
/api/v1
```

主接口：

```text
POST /chat/stream
```

表单字段：

- `product_info`
- `excel_rows`
- `input_text`
- `enable_fuzzy_code_match`
- `images`
- `files`
- `raw_files`

前端大批量 Excel 行会走后台任务接口：

```text
POST /chat/jobs
GET /chat/jobs/{job_id}/stream
```

## 8. 本地开发

```powershell
cd C:\Users\admin\Desktop\work\workspace\QuickQuote\frontend
npm install
npm run dev
```

默认访问：

```text
http://localhost:5173
```

## 9. 检查和构建

```powershell
npm run check
npm run build
```

## 10. Docker 运行

前端 Docker 镜像由 `frontend/Dockerfile` 构建，Nginx 配置在：

```text
frontend/nginx.conf
```

Nginx 会将 `/api/` 代理到后端容器：

```text
http://backend:8000
```

`docker-entrypoint.sh` 会把构建产物中的 API 地址替换为运行时的 `API_BASE_URL`，默认 `/api/v1`。
