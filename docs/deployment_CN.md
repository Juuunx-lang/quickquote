# 部署备忘

推荐使用 Docker Compose 单机部署。

```bash
cp .env.docker.example .env
docker compose up -d --build
```

检查部署：

```bash
docker compose ps
curl http://127.0.0.1:3000/api/v1/health
```

## 运行数据

后端使用：

- `/app/uploads`：上传文件。
- `/app/data`：token 缓存和报价归档。

供应商报价 SQLite 数据库应放在：

```text
brand_item_price/price.db
```

本开源仓库不包含私有运行数据。

## 反向代理

如果在前端服务前面再加 Nginx、Caddy 或面板反代，需要关闭 SSE 缓冲并设置足够的读取超时。

Nginx 示例：

```nginx
proxy_buffering off;
proxy_read_timeout 300s;
```

## 不要提交的文件

- `.env`
- `brand_item_price/price.db`
- token 缓存
- 上传文件
- 构建产物
- 依赖目录
