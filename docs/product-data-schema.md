# Product data schema

Canonical JSON model validated by Pydantic before Illustrator or packaging.

See example: [`examples/product-mango-syrup.json`](../examples/product-mango-syrup.json)

## Shape

```json
{
  "product": { "brand": "", "name": "", "sku": "", "revision": "" },
  "label": {
    "template": "file.ai",
    "width_mm": 100,
    "height_mm": 50,
    "bleed_mm": 3,
    "safe_area_mm": 2,
    "min_dpi": 300
  },
  "copy": {
    "product_name": "",
    "flavor": "",
    "net_weight": "",
    "ingredients": "",
    "legal_copy": [],
    "nutrition_panel": null,
    "lot_area": null,
    "extras": {}
  },
  "codes": { "barcode": null, "qr": null },
  "printer": { "profile": null }
}
```

## Rules

- `sku` / `revision` / `template` are sanitized; path separators are rejected
- Empty barcode/QR strings are invalid (omit or provide real values)
- Malformed records never reach Illustrator (`PRODUCT_SCHEMA_INVALID`)
- `ProductRecord.to_label_spec_dict()` maps into the existing LABELOS `LabelSpec` config
