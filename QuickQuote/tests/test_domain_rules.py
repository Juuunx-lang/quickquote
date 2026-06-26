from app.domain.rules.inventory_policy import resolve_inventory_status
from app.domain.rules.pricing_policy import resolve_price_policy
from app.domain.rules.sku_classifier import is_external_purchase_item


def test_sku_classifier_detects_wg_marker() -> None:
    assert is_external_purchase_item({"sku": "WG-001"}) is True
    assert is_external_purchase_item({"product_code": "wg9988"}) is True
    assert is_external_purchase_item({"sku_id": "SP-WG-9"}) is False
    assert is_external_purchase_item({"sku": "ABC-001"}) is False


def test_pricing_policy_prefers_db_or_manual() -> None:
    assert resolve_price_policy("体系内", [{"final_purchase_price": 10}])["price_source"] == "数据库"
    manual = resolve_price_policy("外购", [])
    assert manual["price_source"] == "人工评估"
    assert "人工评估" in manual["fallback_text"]


def test_inventory_policy_returns_reason_for_unknown() -> None:
    external = resolve_inventory_status("外购", [])
    assert external["has_stock"] == "不适用"
    assert external["inventory_reason"]

    unknown = resolve_inventory_status("体系内", [{"stock_qty": None}])
    assert unknown["has_stock"] == "未查询到"
    assert unknown["inventory_reason"]

    in_stock = resolve_inventory_status("体系内", [{"stock_qty": 2, "lead_time_days": 3}])
    assert in_stock["has_stock"] == "有"
    assert in_stock["lead_time"] == "3天"

