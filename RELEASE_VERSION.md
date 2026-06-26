# QuickQuote Release Version

Version: v0.2.0-current
Date: 2026-06-23

Scope:
- Current usable version for the intelligent quotation workflow.
- Three-source candidate recall is supported: purchase records, Jushuitan, and supplier quote SQLite.
- Exact and fuzzy-code matching semantics are clarified.
- Jushuitan latest cost and 30-day purchase-in cost fluctuation display are available.
- Result UI supports candidate, purchase-record, and quote-list filters.
- Candidate cards and source panels support expand/collapse.
- Browser-side Excel export supports selecting candidate records, products, and fields.
- Docker deployment files are updated for supplier quote database mounting and `/app/data` runtime persistence.
- Project manuals are rewritten to replace earlier outdated documents.

Notes:
- The initial backup marker remains documented in `.codex_backups/releases/QuickQuote_v0.1.0_initial_20260610`.
- Runtime secrets must be provided through `.env`; `.env.docker.example` is only a placeholder template.
- `brand_item_price/price.db` is required for supplier quote results in Docker deployments.
