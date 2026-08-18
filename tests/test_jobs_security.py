"""Product schema, security, and revision/idempotency unit tests."""

from __future__ import annotations

import pytest

from labelos.errors import LabelosException
from labelos.jobs import ProductionService, checksum_json, compute_identity
from labelos.schemas.product import parse_product_record
from labelos.security import resolve_under, sanitize_revision, sanitize_sku
from labelos.storage import LocalStorage


def test_product_schema_accepts_canonical_record():
    record = parse_product_record(
        {
            "product": {
                "brand": "ALTERNATIVE",
                "name": "Mango Syrup",
                "sku": "ALT-SYR-MANGO-001",
                "revision": "1.0",
            },
            "label": {"template": "alternative-syrup.ai", "width_mm": 100, "height_mm": 50},
            "copy": {"product_name": "Mango Syrup", "net_weight": "NET 750 mL"},
            "codes": {"barcode": "0123456789012", "qr": "https://example.com"},
            "printer": {"profile": None},
        }
    )
    assert record.product.sku == "ALT-SYR-MANGO-001"
    assert "PRODUCT_NAME" in record.variable_map()


def test_product_schema_rejects_bad_sku():
    with pytest.raises(LabelosException):
        parse_product_record(
            {
                "product": {
                    "brand": "X",
                    "name": "Y",
                    "sku": "../etc/passwd",
                    "revision": "1.0",
                },
                "label": {"template": "t.ai", "width_mm": 1, "height_mm": 1},
            }
        )


def test_sanitize_helpers():
    assert sanitize_sku("ALT-1") == "ALT-1"
    assert sanitize_revision("2.0") == "2.0"
    with pytest.raises(LabelosException):
        sanitize_sku("bad/sku")
    with pytest.raises(LabelosException):
        sanitize_revision("v1")


def test_resolve_under_blocks_traversal(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(LabelosException) as exc:
        resolve_under(root, "../secret")
    assert exc.value.error.code == "PATH_TRAVERSAL"


def test_revision_identity_changes(tmp_path):
    storage = LocalStorage(tmp_path / "storage")
    service = ProductionService(storage)
    config = {
        "artwork": "missing.svg",
        "width_mm": 10,
        "height_mm": 10,
    }
    product_v1 = {
        "product": {"brand": "A", "name": "N", "sku": "SKU-1", "revision": "1.0"},
        "label": {"template": "t.ai", "width_mm": 10, "height_mm": 10},
    }
    product_v2 = {
        "product": {"brand": "A", "name": "N", "sku": "SKU-1", "revision": "1.1"},
        "label": {"template": "t.ai", "width_mm": 10, "height_mm": 10},
    }
    job1 = service.create_or_get_job(product_data=product_v1, config=config, mode="NORMAL")
    job2 = service.create_or_get_job(product_data=product_v2, config=config, mode="NEW_REVISION")
    assert job1["job_id"] != job2["job_id"]
    assert job1["revision"] == "1.0"
    assert job2["revision"] == "1.1"

    identity = compute_identity(
        sku="SKU-1",
        revision="1.0",
        template_checksum="a",
        product_data_checksum=checksum_json(product_v1),
        artwork_checksum=None,
        config_checksum=checksum_json(config),
    )
    assert len(identity) == 64
