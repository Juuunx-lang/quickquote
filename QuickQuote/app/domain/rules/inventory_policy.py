from typing import Any


def resolve_inventory_status(procurement_type: str, jt_matches: list[dict[str, Any]]) -> dict[str, str]:
    if procurement_type == "外购":
        return {
            "has_stock": "不适用",
            "lead_time": "不适用",
            "inventory_reason": "外购商品按业务规则不走聚水潭库存决策",
        }

    lead_time_days = None
    max_stock = None
    for row in jt_matches or []:
        if lead_time_days is None and isinstance(row.get("lead_time_days"), (int, float)):
            lead_time_days = row.get("lead_time_days")
        qty = row.get("stock_qty")
        if isinstance(qty, (int, float)):
            max_stock = qty if max_stock is None else max(max_stock, qty)

    if isinstance(max_stock, (int, float)) and max_stock > 0:
        has_stock = "有"
        inventory_reason = ""
    elif max_stock == 0:
        has_stock = "无"
        inventory_reason = ""
    else:
        has_stock = "未查询到"
        inventory_reason = "聚水潭未返回可用库存字段或查询失败"

    lead_time = f"{int(lead_time_days)}天" if isinstance(lead_time_days, (int, float)) else "未查询到"
    return {
        "has_stock": has_stock,
        "lead_time": lead_time,
        "inventory_reason": inventory_reason,
    }

