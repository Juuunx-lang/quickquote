from typing import Any


def is_external_purchase_item(
    item: dict[str, Any], db_matches: list[dict[str, Any]] | None = None, jt_matches: list[dict[str, Any]] | None = None
) -> bool:
    """Return True when sku_id/product_code starts with WG (case-insensitive)."""
    candidates: list[str] = []
    candidates.append(str(item.get("sku", "")).strip())
    candidates.append(str(item.get("product_code", "")).strip())
    candidates.append(str(item.get("sku_id", "")).strip())
    for row in db_matches or []:
        candidates.append(str(row.get("sku", "")).strip())
        candidates.append(str(row.get("product_code", "")).strip())
        candidates.append(str(row.get("sku_id", "")).strip())
    for row in jt_matches or []:
        candidates.append(str(row.get("sku", "")).strip())
        candidates.append(str(row.get("sku_code", "")).strip())
        candidates.append(str(row.get("sku_id", "")).strip())
    for token in candidates:
        normalized = token.strip().upper()
        if normalized.startswith("WG"):
            return True
    return False

