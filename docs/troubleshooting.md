# Troubleshooting

## Backend Container Fails

Check logs:

```bash
docker compose logs -f backend
```

Common causes:

- Missing environment variables.
- Database network is not reachable.
- LLM API key or base URL is invalid.
- ERP API credentials are invalid.

## Frontend Opens But API Fails

Check:

```bash
curl http://127.0.0.1:3000/api/v1/health
```

If it fails, inspect the frontend Nginx proxy and backend health status.

## Supplier Quotes Are Empty

Confirm that this file exists:

```text
brand_item_price/price.db
```

The expected schema is documented in:

```text
brand_item_price/schema.sql
```

## SSE Hangs

Check reverse proxy buffering and timeout settings.

## Excel Export Does Not Download

The export is generated in the browser. Check the browser console and ensure candidates are selected in the export panel.
