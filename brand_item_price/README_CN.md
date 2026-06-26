# 供应商报价数据库

QuickQuote 可以从 SQLite 数据库读取供应商报价候选。

默认路径：

```text
brand_item_price/price.db
```

开源版本不包含私有运行数据库。

请参考：

- `schema.sql`
- `table_info.txt`

自行创建或放置 `price.db`。

Docker Compose 会将此目录挂载到后端容器：

```text
/brand_item_price
```

后端实际读取：

```text
/brand_item_price/price.db
```
