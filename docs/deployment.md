# Deployment

Use Docker Compose for a single-machine deployment.

```bash
cp .env.docker.example .env
docker compose up -d --build
```

Check the deployment:

```bash
docker compose ps
curl http://127.0.0.1:3000/api/v1/health
```

## Runtime Data

The backend uses:

- `/app/uploads` for uploaded files.
- `/app/data` for token cache and quote archives.

The supplier quote SQLite database should be placed at:

```text
brand_item_price/price.db
```

This repository does not include private runtime data.

## Reverse Proxy

If you put another Nginx, Caddy, or panel proxy in front of the frontend service, make sure SSE buffering is disabled and the read timeout is long enough.

Nginx example:

```nginx
proxy_buffering off;
proxy_read_timeout 300s;
```
