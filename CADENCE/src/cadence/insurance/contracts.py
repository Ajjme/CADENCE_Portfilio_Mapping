"""Direct user-supplied wind roof policy terms and their availability contract."""

from __future__ import annotations

from typing import Optional

import polars as pl
from pydantic import BaseModel


class PolicyRecord(BaseModel):
    asset_id: str
    policy_id: Optional[str]
    insured_value: Optional[float]
    deductible_amount: Optional[float]
    deductible_type: Optional[str]
    peril: Optional[str]
    current_premium: Optional[float]
    policy_issue: Optional[str]
    source_deductible_type: Optional[str]
    source_peril: Optional[str]


POLICY_COLUMNS = tuple(PolicyRecord.model_fields)


def normalize_policies(source: pl.DataFrame) -> pl.DataFrame:
    """Keep one policy per asset; unsupported or incomplete terms remain visible."""
    if "asset_id" not in source.columns:
        raise ValueError("insurance source is missing asset_id")
    policies = source.select(
        *(
            pl.col(name).cast(pl.String, strict=False).str.strip_chars().alias(name)
            if name in source.columns
            else pl.lit(None, dtype=pl.String).alias(name)
            for name in POLICY_COLUMNS
            if name != "policy_issue"
        )
    )
    if (policies["asset_id"].null_count()
            or policies.filter(pl.col("asset_id") == "").height
            or policies["asset_id"].n_unique() != policies.height):
        raise ValueError("insurance asset_id must be unique and nonblank")
    for name in ("insured_value", "deductible_amount", "current_premium"):
        policies = policies.with_columns(pl.col(name).cast(pl.Float64, strict=False))
    policies = policies.with_columns(
        pl.col("deductible_type").alias("source_deductible_type"),
        pl.col("peril").alias("source_peril"),
    ).with_columns(
        pl.col("deductible_type").str.to_lowercase(),
        pl.col("peril").str.to_lowercase(),
    )
    issue = pl.coalesce(
        *(
            pl.when(pl.col(name).is_null() | ~pl.col(name).is_finite())
            .then(pl.lit(f"Missing or invalid {name}"))
            .otherwise(None)
            for name in ("insured_value", "deductible_amount", "current_premium")
        ),
        pl.when(pl.col("insured_value") <= 0).then(pl.lit("Insured value must be positive")),
        pl.when(pl.col("deductible_amount") < 0).then(pl.lit("Deductible must be nonnegative")),
        pl.when(pl.col("current_premium") < 0).then(pl.lit("Premium must be nonnegative")),
        pl.when(pl.col("policy_id").is_null() | (pl.col("policy_id") == ""))
        .then(pl.lit("Missing policy_id")),
        pl.when(pl.col("deductible_type").is_null() | (pl.col("deductible_type") != "standard"))
        .then(pl.lit("Unsupported deductible type (Standard only)")),
        pl.when(pl.col("peril").is_null() | (pl.col("peril") != "wind"))
        .then(pl.lit("Unmodeled peril (wind only)")),
    )
    policies = policies.with_columns(issue.alias("policy_issue"))
    return policies.with_columns(
        *(
            pl.when(pl.col(name).is_finite()).then(pl.col(name))
            .otherwise(None).alias(name)
            for name in ("insured_value", "deductible_amount", "current_premium")
        )
    ).select(POLICY_COLUMNS).sort("asset_id")