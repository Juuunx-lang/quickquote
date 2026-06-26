# QuickQuote Docker 部署说明

更新日期：2026-06-23

本项目建议用一套 `docker compose` 在云服务器启动两个容器：

- `quickquote-backend`：FastAPI 后端，监听容器内 `8000`。
- `quickquote-frontend`：Nginx 托管前端静态文件，同时把 `/api/` 反向代理到后端。

默认对外端口是 `3000`，访问地址：

```bash
http://<服务器公网 IP>:3000
```

## 1. 云服务器准备

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

如果使用宝塔、1Panel、阿里云镜像市场等面板，只要确认服务器已经安装 Docker 和 Docker Compose 即可。

## 2. 上传项目

任选一种方式。

方式 A：用 Git 拉取：

```bash
git clone <你的仓库地址> QuickQuote-v2
cd QuickQuote-v2
```

方式 B：本地打包上传：

```bash
cd /opt
mkdir -p QuickQuote-v2
```

然后把本地 `D:\work\QuickQuote\v2` 目录上传到服务器 `/opt/QuickQuote-v2`。

不要上传这些目录：

- `QuickQuote/qqenv`
- `frontend/node_modules`
- `frontend/dist`
- `.idea`

Docker 构建时会重新安装依赖和重新构建前端。

当前版手册入口：

- `智能报价系统交接文档.md`：项目总览、业务流程、接口、数据源和开发注意事项。
- `DOCKER_DEPLOY.md`：服务器 Docker 部署。
- `QuickQuote/README.md`：后端说明。
- `frontend/README.md`：前端说明。

必须保留这些部署文件和数据：

- `docker-compose.yml`
- `.env.docker.example`
- `QuickQuote/Dockerfile`
- `frontend/Dockerfile`
- `frontend/nginx.conf`
- `frontend/docker-entrypoint.sh`
- `brand_item_price/price.db`

其中 `brand_item_price/price.db` 是供应商报价表 SQLite 数据源，`docker-compose.yml` 会把根目录下的 `brand_item_price` 只读挂载到后端容器的 `/brand_item_price`。如果缺少这个文件，系统仍可启动，但供应商报价列表会返回空或 provider_error。

## 3. 配置环境变量

在服务器项目根目录执行：

```bash
cp .env.docker.example .env
nano .env
```

必须填写这些值：

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

建议确认这些运行路径保持默认值：

```env
UPLOAD_DIR=/app/uploads
QUOTE_ARCHIVE_DIR=/app/data
JUSHUITAN_TOKEN_CACHE_FILE=/app/data/.jushuitan_token_cache.json
```

`QUOTE_ARCHIVE_DIR=/app/data` 会把报价归档写到 Docker 数据卷 `quickquote_data`，容器重建后不会丢失。

如果数据库、LLM 代理、聚水潭 API 有 IP 白名单，需要把云服务器公网 IP 加进去，否则容器能启动但业务查询会失败。

## 4. 构建并启动

在项目根目录执行：

```bash
docker compose up -d --build
```

查看容器状态：

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

公网访问：

```bash
http://<服务器公网 IP>:3000
```

云服务器安全组需要放行 `FRONTEND_PORT`，默认是 `3000`。

## 5. 使用域名和 HTTPS

推荐做法：

1. 域名解析到云服务器公网 IP。
2. 在云厂商安全组放行 `80` 和 `443`。
3. 用宝塔 / 1Panel / Nginx Proxy Manager / Caddy 做外层反代。
4. 外层反代目标填写：

```text
http://127.0.0.1:3000
```

如果用外层 Nginx，SSE 流式接口需要关闭缓冲：

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

## 6. 更新部署

上传或拉取新代码后：

```bash
docker compose up -d --build
```

如果只想重启：

```bash
docker compose restart
```

如果需要停止：

```bash
docker compose down
```

注意：`docker compose down -v` 会删除上传文件和聚水潭 token 缓存对应的数据卷，除非你明确要清空数据，否则不要执行。

## 7. 数据持久化

`docker-compose.yml` 里有两个数据卷：

- `quickquote_uploads`：保存上传文件。
- `quickquote_data`：保存聚水潭 token 缓存和报价归档，例如 `/app/data/.jushuitan_token_cache.json` 和 `/app/data/yyyy-mm-dd/quote_*.json`。

这样容器重建后 token 缓存和上传目录不会丢失。

供应商报价表 `brand_item_price/price.db` 默认来自项目目录本身，不在 Docker 数据卷里。如果服务器上后续更新报价表，请替换宿主机项目目录中的 `brand_item_price/price.db`，然后重启后端：

```bash
docker compose restart backend
```

## 8. 常见问题

后端健康检查失败：

```bash
docker compose logs -f backend
```

重点看是否缺少环境变量、数据库连不上、LLM Key 无效、聚水潭鉴权失败。

前端页面能打开但接口失败：

```bash
curl http://127.0.0.1:3000/api/v1/health
```

如果这个失败，说明 Nginx 到 backend 容器的代理或后端健康状态有问题。

SSE 一直等待：

- 检查外层反代是否设置 `proxy_buffering off`。
- 检查 `proxy_read_timeout` 是否至少 `300s`。
- 检查后端日志是否卡在聚水潭或数据库查询。

数据库连不上：

- 检查 `.env` 里的 `ORDER_DB_*` 和 `PURCHASE_DB_*`。
- 检查云数据库安全组 / 白名单是否允许云服务器 IP。
- 在服务器上测试端口连通性。
