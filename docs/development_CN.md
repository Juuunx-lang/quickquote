# 开发说明

## 后端

```bash
cd QuickQuote
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

语法检查：

```bash
python -m compileall app
```

测试：

```bash
python -m pytest
```

## 前端

```bash
cd frontend
npm install
npm run dev
```

类型检查：

```bash
npm run check
```

构建：

```bash
npm run build
```

## 新增候选字段

建议按以下顺序修改：

1. 在后端来源服务中查询或生成字段。
2. 在 `app/workflow/graph.py` 中保留并合并字段。
3. 在 `frontend/src/api/index.ts` 中补充 TypeScript 类型。
4. 如果需要展示，在 `DatabaseRecords.tsx` 中渲染。
5. 如果需要导出，在 `QuoteExportPanel.tsx` 中加入导出字段。
6. 更新文档。

## 新增数据源

建议新建服务：

```text
QuickQuote/app/services/<source>_service.py
```

返回按商品分组的数据：

```python
{
    "idx": 1,
    "item": item,
    "candidates": [],
    "provider_error": ""
}
```

候选中应保留：

- `source`
- `matched_source`
- `matched_sources`

这样前端可以正确判断来源和筛选页。
