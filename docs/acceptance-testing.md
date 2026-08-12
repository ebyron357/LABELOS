# Acceptance testing

Automated suite: `tests/test_acceptance_e2e.py`

```bash
python -m pytest tests/test_acceptance_e2e.py -q
```

Covers:

1. Product data → bridge dry-run artwork
2. LABELOS validate
3. Package + verify
4. Checksum-bound approval + release
5. Defect gating (dimensions, missing copy, corrupted package)

## Live Illustrator gate

Replace dry-run with live `/generate` on the Illustrator workstation using an approved `.ai` template.
Until that template and workstation exist, live generation remains **BLOCKED**.

## Manual checklist for a real SKU

- [ ] Approved copy / regulatory content
- [ ] Approved barcode + QR payloads
- [ ] Approved Illustrator template in `templates/`
- [ ] Printer profile approved
- [ ] Human approver identified
- [ ] n8n workflow pointed at live `LABELOS_API_BASE_URL`
