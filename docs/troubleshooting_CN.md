# 排障说明

## 后端容器启动失败

查看日志：

```bash
docker compose logs -f backend
```

常见原因：

- 环境变量缺失。
- 数据库网络不可达。
- LLM API Key 或 base URL 无效。
- ERP API 凭据无效。

## 前端能打开但接口失败

检查：

```bash
curl http://127.0.0.1:3000/api/v1/health
```

如果失败，检查前端 Nginx 代理和后端健康状态。

## 供应商报价为空

确认文件存在：

```text
brand_item_price/price.db
```

预期 schema 见：

```text
brand_item_price/schema.sql
```

## SSE 卡住

检查外层反代：

- 是否关闭 buffering。
- `proxy_read_timeout` 是否足够。

也需要检查后端是否卡在数据库、LLM 或 ERP 请求。

## Excel 无法下载

Excel 由浏览器生成。请检查：

- 浏览器控制台是否报错。
- 导出面板中是否已选择候选商品。
- 是否至少选择了一个导出字段。
