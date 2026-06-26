# QuickQuote Docker 部署说明

本项目建议使用 Docker Compose 在单机上启动两个容器：

- `quickquote-backend`：FastAPI 后端，容器内监听 `8000`。
- `quickquote-frontend`：Nginx 前端静态站点，同时将 `/api/` 反向代理到后端。

默认对外端口是 `3000`：

```text
http://<server-ip>:3000
```

## 1. 服务器准备

Ubuntu / Debian 示例：

```bash
sudo apt update
sudo apt install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
docker version
docker compose version
```

## 2. 获取项目

```bash
git clone <your-repository-url> quickquote
cd quickquote
```

当前版本文档入口：

- `README_CN.md`：中文项目说明。
- `DOCKER_DEPLOY_CN.md`：中文 Docker 部署说明。
- `docs/architecture_CN.md`：中文架构说明。
- `docs/development_CN.md`：中文开发说明。
- `docs/deployment_CN.md`：中文部署备忘。
- `docs/troubleshooting_CN.md`：中文排障说明。

## 3. 配置环境变量

```bash
cp .env.docker.example .env
nano .env
```

至少需要填写：

```env
ORDER_DB_HOST=
ORDER_DB_PORT=3306
ORDER_DB_USER=
ORDER_DB_PASSWORD=
ORDER_DB_NAME=

PURCHASE_DB_HOST=
PURCHASE_DB_PORT=3306
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

建议保留：

```env
UPLOAD_DIR=/app/uploads
QUOTE_ARCHIVE_DIR=/app/data
JUSHUITAN_TOKEN_CACHE_FILE=/app/data/.jushuitan_token_cache.json
```

如果数据库、LLM 或聚水潭接口有 IP 白名单，需要把服务器公网 IP 加入白名单。

## 4. 供应商报价数据库

供应商报价源需要 SQLite 文件：

```text
brand_item_price/price.db
```

开源仓库不包含私有 `price.db`。请参考：

```text
brand_item_price/schema.sql
```

自行创建或放置 SQLite 文件。

Docker Compose 会将目录只读挂载到后端容器：

```text
/brand_item_price
```

## 5. 启动

```bash
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f backend
docker compose logs -f frontend
```

健康检查：

```bash
curl http://127.0.0.1:3000/
curl http://127.0.0.1:3000/api/v1/health
```

## 6. 域名和 HTTPS

如果使用外层 Nginx、Caddy、宝塔、1Panel 或 Nginx Proxy Manager，反代目标通常是：

```text
http://127.0.0.1:3000
```

SSE 流式接口需要关闭缓冲：

```nginx
location / {
    proxy_pass http://127.0.0.1:3000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 300s;
}
```

## 7. 数据持久化

Compose 中有两个数据卷：

- `quickquote_uploads`：上传文件。
- `quickquote_data`：token 缓存和报价归档。

不要随意执行：

```bash
docker compose down -v
```

这会删除数据卷。

## 8. 更新部署

```bash
git pull
docker compose up -d --build
```

只重启：

```bash
docker compose restart
```

## 9. 常见问题

后端健康检查失败：

```bash
docker compose logs -f backend
```

前端能打开但接口失败：

```bash
curl http://127.0.0.1:3000/api/v1/health
```

SSE 卡住：

- 检查外层反代是否 `proxy_buffering off`。
- 检查 `proxy_read_timeout` 是否足够。
- 检查后端是否卡在数据库、LLM 或聚水潭请求。

供应商报价为空：

- 检查 `brand_item_price/price.db` 是否存在。
- 检查 schema 是否与 `brand_item_price/schema.sql` 一致。
