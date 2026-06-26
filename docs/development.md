# Development

## Backend

```bash
cd QuickQuote
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Syntax check:

```bash
python -m compileall app
```

Tests:

```bash
python -m pytest
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Type check:

```bash
npm run check
```

Build:

```bash
npm run build
```

## Adding a Candidate Field

1. Add it in the backend source service.
2. Preserve it in `app/workflow/graph.py`.
3. Add the TypeScript field in `frontend/src/api/index.ts`.
4. Render it in `DatabaseRecords.tsx` if needed.
5. Add it to `QuoteExportPanel.tsx` if it should be exportable.
