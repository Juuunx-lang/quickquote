# Architecture

QuickQuote is split into a FastAPI backend and a React frontend.

## Backend

Main entry points:

- `QuickQuote/app/main.py`
- `QuickQuote/app/api/v1/endpoints/chat.py`
- `QuickQuote/app/workflow/graph.py`

Workflow stages:

```text
extract_stage
  -> multi_source_match_stage
  -> purchase_route_stage
  -> result_stage
```

Data sources:

- Purchase records from MySQL.
- ERP product, inventory, cost, and purchase-in records.
- Supplier quotes from SQLite.

## Frontend

Main entry points:

- `frontend/src/pages/Chat.tsx`
- `frontend/src/components/ChatInput.tsx`
- `frontend/src/components/DatabaseRecords.tsx`
- `frontend/src/components/QuoteExportPanel.tsx`
- `frontend/src/api/index.ts`

The frontend consumes SSE events, renders candidate cards, filters candidate groups, and exports selected rows to Excel in the browser.

## Matching Semantics

Exact match means normalized full equality.

Fuzzy code match means normalized substring match for code-like fields. This is controlled by the frontend fuzzy-code switch.

Name fields are allowed to use contains-style matching by default.
