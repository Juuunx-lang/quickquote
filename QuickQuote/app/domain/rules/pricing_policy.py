from typing import Any


def resolve_price_policy(procurement_type: str, db_matches: list[dict[str, Any]]) -> dict[str, str]:
    """
    Define price source policy:
    - 体系内/外购均优先数据库
    - 数据库无价时转人工评估
    """
    if db_matches:
        return {"price_source": "数据库", "fallback_text": ""}
    if procurement_type == "外购":
        return {"price_source": "人工评估", "fallback_text": "外购商品无历史数据，需人工评估采购价与售价"}
    return {"price_source": "人工评估", "fallback_text": "数据库未查询到有效价格，需人工评估"}


def has_db_price(rows: list[dict[str, Any]]) -> bool:
    for row in rows or []:
        value = row.get("final_purchase_price")
        if isinstance(value, (int, float)) and float(value) > 0:
            return True
        try:
            if value is not None and float(value) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False

