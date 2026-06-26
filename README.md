# QuickQuote

QuickQuote is an intelligent quotation workbench for product quote review. It parses product requirements, recalls candidate products from multiple sources, merges purchase history, ERP inventory/cost information, and supplier quote data, then lets users review candidates and export selected fields to Excel.

QuickQuote is distributed as a configurable workbench template. Runtime credentials, database connections, ERP integrations, uploaded files, and provider tokens are supplied through local environment variables or your own deployment secrets.

## Features

- Text input and multi-line product requests.
- Excel row parsing in the browser.
- File and image-assisted extraction through the backend workflow.
- Multi-source candidate recall:
  - Purchase records from MySQL.
  - Jushuitan ERP product, inventory, cost, and purchase-in records.
  - Supplier quote data from a local SQLite database.
- Exact matching and optional fuzzy matching for code-like fields.
- Name fields support fuzzy search by default.
- Candidate result filters:
  - All candidates.
  - Purchase records.
  - Supplier quote list.
- Collapsible candidate cards and source panels.
- Jushuitan latest cost and 30-day cost fluctuation view.
- Browser-side Excel export with selectable candidates and fields.
- Docker Compose deployment.

## Architecture

```text
quickquote/
├── QuickQuote/             # FastAPI backend
├── frontend/               # React + TypeScript + Vite frontend
├── brand_item_price/       # Supplier quote schema and sample placement notes
├── docs/                   # Public technical notes
├── docker-compose.yml
└── .env.docker.example
```

Backend:

- FastAPI
- SQLAlchemy async
- MySQL
- SQLite
- Jushuitan OpenAPI
- LLM API

Frontend:

- React 18
- TypeScript
- Vite
- Zustand
- Tailwind CSS
- xlsx

## Quick Start

Copy the environment template:

```bash
cp .env.docker.example .env
```

Fill in your own runtime configuration:

```env
ORDER_DB_HOST=
ORDER_DB_USER=
ORDER_DB_PASSWORD=
ORDER_DB_NAME=

PURCHASE_DB_HOST=
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

Start with Docker Compose:

```bash
docker compose up -d --build
```

Open:

```text
http://localhost:3000
```

Health check:

```bash
curl http://127.0.0.1:3000/api/v1/health
```

## Supplier Quote SQLite

The supplier quote source expects:

```text
brand_item_price/price.db
```

Use the SQL files in `brand_item_price/` to understand the expected schema and create your own SQLite database file for quotation data.

Docker Compose mounts:

```yaml
./brand_item_price:/brand_item_price:ro
```

## Local Development

Backend:

```bash
cd QuickQuote
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Type checks:

```bash
cd frontend
npm run check
```

Backend syntax check:

```bash
cd QuickQuote
python -m compileall app
```

## Documentation

- `docs/项目全景手册.md`
- `docs/开发细节备忘.md`
- `docs/部署与环境备忘.md`
- `docs/排障与回归用例.md`
- `DOCKER_DEPLOY.md`

## Runtime Configuration

Use .env.docker.example as the starting point for local configuration. Keep runtime values in .env or in your deployment secret manager, and create your own SQLite quotation database from the schema files when needed.

## License

Add a license before publishing the repository publicly.
