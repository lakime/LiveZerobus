"""Train + register the seed-house supplier-scoring model.

Registers `supplier_scoring_model` in Unity Catalog with alias `prod`.

The model takes these features (in order) — matching the Lakeflow
pipeline `auto_procurement_scoring.py`:

    usd_per_gram, pack_size_g, lead_time_days, min_qty,
    on_time_pct, quality_score,
    demand_1h_trays, input_pct_24h, organic_cert_int

and returns a score in [0, 1] — "buy this SKU from this seed house now,
under current grow-input conditions".

Run via direct python or as a notebook:
    python ml/train_supplier_model.py
"""
from __future__ import annotations

import os

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


FEATURES = [
    "usd_per_gram",
    "pack_size_g",
    "lead_time_days",
    "min_qty",
    "on_time_pct",
    "quality_score",
    "demand_1h_trays",
    "input_pct_24h",
    "organic_cert_int",
]


def _synth(n: int = 20_000, seed: int = 7) -> pd.DataFrame:
    """Synthesize a labelled training set.

    Label is a hand-crafted "ideal procurement score" that rewards:
      - low $/gram (normalized)
      - pack size close to real-order size (not too small, not too bulky)
      - short lead time
      - high supplier reliability (on_time_pct, quality_score)
      - high planting urgency (demand_1h_trays)
      - rising grow-input trend (buy before it goes up more)
      - organic certification (small nudge; weighted by crop/buyer prefs)
    """
    rng = np.random.default_rng(seed)

    # Seed $/gram spans microgreens (~$0.12) to herbs (~$1.10)
    usd_per_gram = np.clip(rng.lognormal(mean=-0.8, sigma=0.6, size=n), 0.05, 4.0)
    price_norm = usd_per_gram / usd_per_gram.mean()

    # Pack sizes: microgreens 100–2000g bulk, regular seed 1–100g
    is_mg = rng.random(n) < 0.4
    pack_size_g = np.where(
        is_mg,
        rng.choice([100, 250, 500, 1000, 2000], size=n),
        rng.choice([1, 5, 25, 100], size=n),
    ).astype(float)

    lead = rng.integers(1, 30, size=n)
    min_qty = rng.choice([1, 2, 5, 10], size=n)
    on_time = np.clip(rng.normal(0.92, 0.06, size=n), 0.4, 1.0)
    quality = np.clip(rng.normal(0.90, 0.06, size=n), 0.3, 1.0)
    demand = rng.poisson(lam=20, size=n)  # trays/hour
    trend = rng.normal(0, 0.02, size=n)
    organic = (rng.random(n) < 0.55).astype(float)

    # "ideal" score — what we want the model to learn
    price_term = np.exp(-1.2 * (price_norm - 0.9).clip(min=0))

    # penalise very small packs (waste of ordering) AND ultra-bulk packs (shelf-life risk)
    ps_log = np.log10(pack_size_g)
    pack_term = np.exp(-0.35 * (ps_log - 2.0) ** 2)     # sweet spot ~100g

    lead_term = np.exp(-lead / 15.0)
    rel_term = 0.6 * on_time + 0.4 * quality
    urgency_term = np.tanh(demand / 40.0)
    trend_term = 0.5 + 0.5 * np.tanh(trend * 20)
    organic_term = 0.5 + 0.5 * organic                   # 0.5 or 1.0

    score = (
        0.30 * price_term
        + 0.10 * pack_term
        + 0.15 * lead_term
        + 0.20 * rel_term
        + 0.10 * urgency_term
        + 0.10 * trend_term
        + 0.05 * organic_term
    )
    score = np.clip(score + rng.normal(0, 0.02, size=n), 0, 1)

    return pd.DataFrame({
        "usd_per_gram": usd_per_gram,
        "pack_size_g": pack_size_g,
        "lead_time_days": lead,
        "min_qty": min_qty,
        "on_time_pct": on_time,
        "quality_score": quality,
        "demand_1h_trays": demand,
        "input_pct_24h": trend,
        "organic_cert_int": organic,
        "label": score,
    })


def main() -> None:
    catalog = os.environ.get("UC_CATALOG", "livezerobus")
    schema = os.environ.get("UC_SCHEMA", "procurement")
    model_name = f"{catalog}.{schema}.supplier_scoring_model"

    mlflow.set_registry_uri("databricks-uc")
    mlflow.set_experiment(f"/Shared/{catalog}.{schema}.supplier_scoring")

    df = _synth()
    X_train, X_test, y_train, y_test = train_test_split(
        df[FEATURES], df["label"], test_size=0.2, random_state=7
    )

    pipe = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("gbr", GradientBoostingRegressor(
                n_estimators=250,
                max_depth=4,
                learning_rate=0.05,
                random_state=7,
            )),
        ]
    )

    with mlflow.start_run(run_name="supplier_scoring_seed_gbr") as run:
        pipe.fit(X_train, y_train)
        preds = pipe.predict(X_test).clip(0, 1)
        mae = mean_absolute_error(y_test, preds)
        mlflow.log_param("features", FEATURES)
        mlflow.log_param("domain", "vertical-farm-seed-procurement")
        mlflow.log_metric("mae", mae)

        signature = mlflow.models.infer_signature(X_train.head(100), preds[:100])

        info = mlflow.sklearn.log_model(
            sk_model=pipe,
            artifact_path="model",
            signature=signature,
            registered_model_name=model_name,
            input_example=X_train.head(5),
        )
        print(f"✔ Registered {model_name} v{info.registered_model_version} — MAE={mae:.4f}")

        # Promote to @prod alias
        client = mlflow.tracking.MlflowClient()
        client.set_registered_model_alias(
            name=model_name,
            alias="prod",
            version=info.registered_model_version,
        )
        print(f"✔ Alias 'prod' → v{info.registered_model_version}")


if __name__ == "__main__":
    main()
