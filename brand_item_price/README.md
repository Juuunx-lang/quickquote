# Supplier Quote Database

QuickQuote can read supplier quote candidates from a SQLite database at:

```text
brand_item_price/price.db
```

The private runtime database is intentionally not included in this open-source edition.

Use this SQL file as a schema reference:

- `schema.sql`
- `table_info.txt`

At runtime, create or place your own `price.db` in this directory.

Docker Compose mounts this directory into the backend container as:

```text
/brand_item_price
```

The backend service resolves:

```text
/brand_item_price/price.db
```
