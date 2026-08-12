# Illustrator template standard

Designers must construct templates so LABELOS can automate variable replacement without relying on object stacking order.

## Required practice

1. **Named text frames / objects** for every variable field.
2. **Named layers** separating brand, variable copy, codes, dieline, and production.
3. **Locked layers** for assets automation must never alter.
4. **Documented artboard size** matching product data (`width_mm`, `height_mm`, bleed).

## Stable identifiers

Use these object names exactly (case-sensitive):

| Name | Content |
| --- | --- |
| `PRODUCT_NAME` | Product display name |
| `FLAVOR` | Flavor / variant |
| `NET_WEIGHT` | Net quantity statement |
| `INGREDIENTS` | Ingredients statement |
| `NUTRITION_PANEL` | Nutrition text/panel placeholder |
| `UPC` | Barcode human-readable / linked value |
| `QR_CODE` | QR payload / linked value |
| `LOT_AREA` | Lot / batch overprint area |
| `LEGAL_COPY` | Mandatory legal lines |
| `BRAND_MARK` | Brand logo/mark (prefer locked layer) |
| `PRODUCT_IMAGE` | Product imagery |
| `BACKGROUND_ART` | Background artwork |

## Required layers

| Layer | Editable by automation? |
| --- | --- |
| `VARIABLE_COPY` | Yes |
| `CODES` | Yes (barcode/QR artwork updates) |
| `BRAND_MARK` | No — keep locked |
| `DIELINE` | No — keep locked |
| `PRODUCTION` | No — keep locked |
| `BACKGROUND_ART` | No — keep locked unless explicitly approved |

## File naming

- Template file names must be filesystem-safe: `alternative-syrup.ai`
- Product data `label.template` must match the template filename

## Export expectations

Automation exports PDF (default), optional AI and PNG. Trim size + bleed must match the product record. Safe area must remain clear of mandatory copy.

## Designer checklist

- [ ] Artboard = trim + bleed agreed with printer
- [ ] All variable text frames named from the table above
- [ ] Brand / dieline / production layers locked
- [ ] Fonts licensed and outlined or embedded per printer policy
- [ ] Barcode/QR placeholders exist and are named
- [ ] Template saved to `templates/` and checksum recorded in the job
