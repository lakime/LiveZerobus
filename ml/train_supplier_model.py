"""Train + register the supplier-scoring model.

Registers `supplier_scoring_model` in Unity Catalog with alias `prod`.

The model takes these features (in order):
    unit_price_usd, lead_time_days, min_qty,
    on_time_pct, quality_score,
    demand_1h_qty, commodity_pct_24h

and returns a score in [0, 1] — the higher the better for "buy from this
supplier now, for this SKU, under current market conditions".

Run via the bundle:
    databricks bundle run train_supplier_model -t dev
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
    "unit_price_usd",
    "lead_time_days",
    "min_qty",
    "on_time_pct",
    "quality_score",
    "demand_1h_qty",
    "commodity_pct_24h",
]


def _synth(n: int = 20_000, seed: int = 7) -> pd.DataFrame:
    """Synthesize a labelled training set.

    Label is a hand-crafted "ideal procurement score" that rewards:
      - low price (normalized per SKU)
      - short lead time
      - high supplier reliability (on_time_pct, quality_score)
      - high demand (urgency)
      - rising commodity trend (buy before it goes up more)
    """
    rng = np.random.default_rng(seed)

    unit_price = rng.lognormal(mean=1.8, sigma=0.5, size=n)
    price_norm = unit_price / unit_price.mean()

    lead = rng.integers(1, 30, size=n)
    min_qty = rng.choice([100, 250, 500, 1000], size=n)
    on_time = np.clip(rng.normal(0.9, 0.07, size=n), 0.4, 1.0)
    quality = np.clip(rng.normal(0.88, 0.08, size=n), 0.3, 1.0)
    demand = rng.poisson(lam=30, size=n)
    trend = rng.normal(0, 0.02, size=n)

    # "ideal" score — what we want the model to learn
    price_term = np.exp(-1.2 * (price_norm - 0.9).clip(min=0))
    lead_term = np.exp(-lead / 15.0)
    rel_term = 0.6 * on_time + 0.4 * quality
    urgency_term = np.tanh(demand / 40.0)
    trend_term = 0.5 + 0.5 * np.tanh(trend * 20)

    score = (
        0.35 * price_term
        + 0.20 * lead_term
        + 0.20 * rel_term
        + 0.15 * urgency_term
        + 0.10 * trend_term
    )
    score = np.clip(score + rng.normal(0, 0.02, size=n), 0, 1)

    return pd.DataFrame({
        "unit_price_usd": unit_price,
        "lead_time_days": lead,
        "min_qty": min_qty,
        "on_time_pct": on_time,
        "quality_score": quality,
        "demand_1h_qty": demand,
        "commodity_pct_24h": trend,
        "label": score,
    })


def main() -> None:
    catalog = os.environ.get("UC_CATALOG", "main")
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

    with mlflow.start_run(run_name="supplier_scoring_gbr") as run:
        pipe.fit(X_train, y_train)
        preds = pipe.predict(X_test).clip(0, 1)
        mae = mean_absolute_error(y_test, preds)
        mlflow.log_param("features", FEATURES)
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
