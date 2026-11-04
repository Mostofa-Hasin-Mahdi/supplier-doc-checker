"""Configuration models and loader for procurement rules."""

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class RulesConfig(BaseModel):
    """Externalized procurement rules configuration loaded from config/rules.yaml."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    price_tolerance_pct: Decimal = Field(default=Decimal("3.0"))
    quantity_tolerance_pct: Decimal = Field(default=Decimal("5.0"))
    max_advance_pct: Decimal = Field(default=Decimal("20.0"))
    max_delivery_days: int = Field(default=45)
    review_delivery_days_min: int = Field(default=31)
    review_delivery_days_max: int = Field(default=45)
    min_payment_days: int = Field(default=30)
    max_payment_days: int = Field(default=60)
    min_penalty_pct_per_week: Decimal = Field(default=Decimal("0.5"))
    penalty_base_unstated_policy: str = Field(default="review")  # "review" | "accept"
    tin_bin_policy: str = Field(default="reject_if_either_missing")  # "reject_if_either_missing" | "reject_if_both_missing" | "review_if_one_missing"
    required_vat_percent: Decimal = Field(default=Decimal("15.0"))
    min_validity_days: int = Field(default=30)
    math_tolerance: Decimal = Field(default=Decimal("1.00"))
    strict_currency_match: bool = Field(default=True)

    @classmethod
    def from_yaml(cls, path: str | Path = "config/rules.yaml") -> "RulesConfig":
        """Load and parse rules config from YAML file."""
        file_path = Path(path)
        if not file_path.exists():
            return cls()
        with open(file_path, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
        raw_rules = data.get("rules", {})
        return cls(
            price_tolerance_pct=Decimal(str(raw_rules.get("price_tolerance_pct", "3.0"))),
            quantity_tolerance_pct=Decimal(str(raw_rules.get("quantity_tolerance_pct", "5.0"))),
            max_advance_pct=Decimal(str(raw_rules.get("max_advance_pct", "20.0"))),
            max_delivery_days=int(raw_rules.get("max_delivery_days", 45)),
            review_delivery_days_min=int(raw_rules.get("review_delivery_days_min", 31)),
            review_delivery_days_max=int(raw_rules.get("review_delivery_days_max", 45)),
            min_payment_days=int(raw_rules.get("min_payment_days", 30)),
            max_payment_days=int(raw_rules.get("max_payment_days", 60)),
            min_penalty_pct_per_week=Decimal(str(raw_rules.get("min_penalty_pct_per_week", "0.5"))),
            penalty_base_unstated_policy=str(raw_rules.get("penalty_base_unstated_policy", "review")).strip().lower(),
            tin_bin_policy=str(raw_rules.get("tin_bin_policy", "reject_if_either_missing")).strip().lower(),
            required_vat_percent=Decimal(str(raw_rules.get("required_vat_percent", "15.0"))),
            min_validity_days=int(raw_rules.get("min_validity_days", 30)),
            math_tolerance=Decimal(str(raw_rules.get("math_tolerance", "1.00"))),
            strict_currency_match=bool(raw_rules.get("strict_currency_match", True)),
        )
