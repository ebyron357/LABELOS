"""Canonical product / label data model with schema validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..errors import INPUT_ERROR, LabelosException
from ..security import sanitize_revision, sanitize_sku, sanitize_token


class ProductInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand: str
    name: str
    sku: str
    revision: str

    @field_validator("sku")
    @classmethod
    def _sku(cls, value: str) -> str:
        return sanitize_sku(value)

    @field_validator("revision")
    @classmethod
    def _revision(cls, value: str) -> str:
        return sanitize_revision(value)

    @field_validator("brand", "name")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty")
        return cleaned


class LabelGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    bleed_mm: float = Field(default=0, ge=0)
    safe_area_mm: float = Field(default=0, ge=0)
    min_dpi: int = Field(default=300, gt=0)

    @field_validator("template")
    @classmethod
    def _template(cls, value: str) -> str:
        return sanitize_token(value, field="template")


class CopyBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_name: str | None = None
    flavor: str | None = None
    net_weight: str | None = None
    ingredients: str | None = None
    legal_copy: list[str] = Field(default_factory=list)
    nutrition_panel: str | None = None
    lot_area: str | None = None
    extras: dict[str, str] = Field(default_factory=dict)


class CodesBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    barcode: str | None = None
    qr: str | None = None

    @field_validator("barcode", "qr")
    @classmethod
    def _optional_nonempty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("code values cannot be empty strings")
        return cleaned


class PrinterBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str | None = None


class ProductRecord(BaseModel):
    """Canonical structured product data for Illustrator + LABELOS."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    product: ProductInfo
    label: LabelGeometry
    label_copy: CopyBlock = Field(default_factory=CopyBlock, alias="copy")
    codes: CodesBlock = Field(default_factory=CodesBlock)
    printer: PrinterBlock = Field(default_factory=PrinterBlock)

    def required_copy_list(self) -> list[str]:
        values: list[str] = []
        for candidate in (
            self.label_copy.product_name,
            self.label_copy.flavor,
            self.label_copy.net_weight,
            self.label_copy.ingredients,
            self.label_copy.nutrition_panel,
            self.label_copy.lot_area,
        ):
            if candidate:
                values.append(candidate)
        values.extend(item for item in self.label_copy.legal_copy if item)
        values.extend(value for value in self.label_copy.extras.values() if value)
        return values

    def to_label_spec_dict(self, artwork_path: str) -> dict[str, Any]:
        """Map product record into existing LabelSpec configuration shape."""
        payload: dict[str, Any] = {
            "artwork": artwork_path,
            "width_mm": self.label.width_mm,
            "height_mm": self.label.height_mm,
            "bleed_mm": self.label.bleed_mm,
            "safe_area_mm": self.label.safe_area_mm,
            "min_dpi": self.label.min_dpi,
            "required_copy": self.required_copy_list(),
        }
        if self.codes.barcode:
            payload["barcode_value"] = self.codes.barcode
        if self.codes.qr:
            payload["qr_value"] = self.codes.qr
        return payload

    def variable_map(self) -> dict[str, str]:
        """Named Illustrator placeholder → replacement text."""
        mapping: dict[str, str] = {
            "PRODUCT_NAME": self.label_copy.product_name or self.product.name,
            "FLAVOR": self.label_copy.flavor or "",
            "NET_WEIGHT": self.label_copy.net_weight or "",
            "INGREDIENTS": self.label_copy.ingredients or "",
            "NUTRITION_PANEL": self.label_copy.nutrition_panel or "",
            "UPC": self.codes.barcode or "",
            "QR_CODE": self.codes.qr or "",
            "LOT_AREA": self.label_copy.lot_area or "",
            "LEGAL_COPY": "\n".join(self.label_copy.legal_copy),
            "BRAND_MARK": self.product.brand,
        }
        mapping.update({key.upper(): value for key, value in self.label_copy.extras.items()})
        return {key: value for key, value in mapping.items() if value != ""}


def parse_product_record(data: dict[str, Any]) -> ProductRecord:
    try:
        return ProductRecord.model_validate(data)
    except Exception as error:
        raise LabelosException(
            f"Malformed product record: {error}",
            code="PRODUCT_SCHEMA_INVALID",
            category=INPUT_ERROR,
            details={"error": str(error)},
        ) from error
