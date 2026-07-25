#!/usr/bin/env python3
"""
Response Time Predictor — LightGBM models for paris response time prediction.

Trains two separate models:
  1. Mobilization model: predicts time from selection to departure (wake-up, dressing, reach vehicle)
  2. Travel model: predicts actual travel time from departure to arrival on scene

Features follow the ds4es/unit-response-oracle approach, adapted for the CMS platform.

Usage:
    python response_time_model.py train [--db-host HOST] [--db-name NAME]
    python response_time_model.py predict --lat LAT --lon LON --hour HOUR [--station STATION]

Models are saved to /app/models/ (or ./models/) for reuse.
"""

import os
import sys
import json
import pickle
import numpy as np
import pandas as pd
import lightgbm as lgb
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, median_absolute_error, r2_score


# ============================================================================
# Configuration
# ============================================================================

MODELS_DIR = Path(os.getenv("MODELS_DIR", "./models"))
MOBILIZATION_MODEL_FILE = MODELS_DIR / "mobilization_model.pkl"
TRAVEL_MODEL_FILE = MODELS_DIR / "travel_model.pkl"
MODEL_METADATA_FILE = MODELS_DIR / "model_metadata.json"

# Features for mobilization prediction (time-dependent, not distance-dependent)
MOBILIZATION_FEATURES = [
    "hour_of_day",
    "day_of_week",
    "is_night",         # derived: 22-6h
    "is_weekend",       # derived: sat/sun
    "station_id",
    "unit_category",
    "intervention_type",
]

# Features for travel prediction (distance-dependent)
TRAVEL_FEATURES = [
    "hour_of_day",
    "day_of_week",
    "is_night",
    "is_weekend",
    "is_rush_hour",     # derived: 7-9h, 17-19h
    "station_id",
    "unit_category",
    "intervention_type",
    "road_distance_m",
    "road_travel_time_sec",     # CH theoretical (speed limit)
    "straight_line_distance_m",
    "departure_lat",
    "departure_lon",
    "intervention_lat",
    "intervention_lon",
]

CATEGORICAL_FEATURES_MOBIL = ["station_id", "unit_category", "intervention_type"]
CATEGORICAL_FEATURES_TRAVEL = ["station_id", "unit_category", "intervention_type"]


# ============================================================================
# Data Loading
# ============================================================================

def load_data(db_host="localhost", db_name="ems", db_user="postgres", db_password="postgres"):
    """Load response_metrics from PostgreSQL."""
    import psycopg2

    conn = psycopg2.connect(host=db_host, database=db_name, user=db_user, password=db_password)
    df = pd.read_sql("""
        SELECT *
        FROM response_metrics
        WHERE mobilization_sec IS NOT NULL
          AND travel_sec IS NOT NULL
          AND road_distance_m IS NOT NULL
          AND road_distance_m > 0
          AND road_travel_time_sec > 0
          AND mobilization_sec > 0
          AND mobilization_sec < 600
          AND travel_sec > 10
          AND travel_sec < 3600
          AND response_time_sec > 10
          AND response_time_sec < 3600
    """, conn)
    conn.close()

    print(f"[model] Loaded {len(df)} records from response_metrics")
    return df


def engineer_features(df):
    """Add derived features."""
    df = df.copy()
    df["is_night"] = df["hour_of_day"].isin([22, 23, 0, 1, 2, 3, 4, 5]).astype(int)
    df["is_weekend"] = df["day_of_week"].isin([0, 6]).astype(int)  # 0=Sun, 6=Sat
    df["is_rush_hour"] = df["hour_of_day"].isin([7, 8, 9, 17, 18, 19]).astype(int)

    # Convert decimal coords to float
    for col in ["departure_lat", "departure_lon", "intervention_lat", "intervention_lon"]:
        df[col] = df[col].astype(float)

    # Cast categoricals
    for col in ["station_id", "unit_category", "intervention_type"]:
        df[col] = df[col].astype("category")

    return df


# ============================================================================
# Training
# ============================================================================

def train_models(df, test_size=0.2, random_state=42):
    """Train mobilization and travel models."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    df = engineer_features(df)

    # ---- Mobilization Model ----
    print("\n" + "=" * 60)
    print("Training MOBILIZATION model (selection → departure)")
    print("=" * 60)

    X_mob = df[MOBILIZATION_FEATURES]
    y_mob = df["mobilization_sec"]

    X_train_m, X_test_m, y_train_m, y_test_m = train_test_split(
        X_mob, y_mob, test_size=test_size, random_state=random_state
    )

    mob_model = lgb.LGBMRegressor(
        n_estimators=500,
        learning_rate=0.05,
        max_depth=6,
        num_leaves=31,
        min_child_samples=50,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=0.1,
        random_state=random_state,
        verbose=-1,
    )
    mob_model.fit(
        X_train_m, y_train_m,
        eval_set=[(X_test_m, y_test_m)],
        callbacks=[lgb.log_evaluation(100)],
        categorical_feature=CATEGORICAL_FEATURES_MOBIL,
    )

    y_pred_m = mob_model.predict(X_test_m)
    mob_metrics = evaluate(y_test_m, y_pred_m, "Mobilization")

    # ---- Travel Model ----
    print("\n" + "=" * 60)
    print("Training TRAVEL model (departure → arrival)")
    print("=" * 60)

    X_trv = df[TRAVEL_FEATURES]
    y_trv = df["travel_sec"]

    X_train_t, X_test_t, y_train_t, y_test_t = train_test_split(
        X_trv, y_trv, test_size=test_size, random_state=random_state
    )

    trv_model = lgb.LGBMRegressor(
        n_estimators=800,
        learning_rate=0.05,
        max_depth=8,
        num_leaves=63,
        min_child_samples=30,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,
        reg_lambda=0.1,
        random_state=random_state,
        verbose=-1,
    )
    trv_model.fit(
        X_train_t, y_train_t,
        eval_set=[(X_test_t, y_test_t)],
        callbacks=[lgb.log_evaluation(100)],
        categorical_feature=CATEGORICAL_FEATURES_TRAVEL,
    )

    y_pred_t = trv_model.predict(X_test_t)
    trv_metrics = evaluate(y_test_t, y_pred_t, "Travel")

    # ---- Combined prediction ----
    print("\n" + "=" * 60)
    print("COMBINED response time (mobilization + travel)")
    print("=" * 60)

    # Predict on test set (use same indices)
    test_idx = X_test_t.index
    y_mob_pred_combined = mob_model.predict(df.loc[test_idx, MOBILIZATION_FEATURES])
    y_trv_pred_combined = trv_model.predict(df.loc[test_idx, TRAVEL_FEATURES])
    y_total_pred = y_mob_pred_combined + y_trv_pred_combined
    y_total_actual = df.loc[test_idx, "response_time_sec"]
    combined_metrics = evaluate(y_total_actual, y_total_pred, "Combined (mob+travel)")

    # ---- Feature importance ----
    print("\n--- Mobilization feature importance ---")
    for feat, imp in sorted(zip(MOBILIZATION_FEATURES, mob_model.feature_importances_),
                             key=lambda x: -x[1]):
        print(f"  {feat:25s} {imp:6d}")

    print("\n--- Travel feature importance ---")
    for feat, imp in sorted(zip(TRAVEL_FEATURES, trv_model.feature_importances_),
                             key=lambda x: -x[1]):
        print(f"  {feat:30s} {imp:6d}")

    # ---- Save models ----
    with open(MOBILIZATION_MODEL_FILE, "wb") as f:
        pickle.dump(mob_model, f)
    with open(TRAVEL_MODEL_FILE, "wb") as f:
        pickle.dump(trv_model, f)

    metadata = {
        "train_records": len(df),
        "test_size": test_size,
        "mobilization_metrics": mob_metrics,
        "travel_metrics": trv_metrics,
        "combined_metrics": combined_metrics,
        "mobilization_features": MOBILIZATION_FEATURES,
        "travel_features": TRAVEL_FEATURES,
    }
    with open(MODEL_METADATA_FILE, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"\n[model] Models saved to {MODELS_DIR}/")
    return mob_model, trv_model, metadata


def evaluate(y_true, y_pred, name):
    """Print and return evaluation metrics."""
    mae = mean_absolute_error(y_true, y_pred)
    median_ae = median_absolute_error(y_true, y_pred)
    r2 = r2_score(y_true, y_pred)
    rmse = np.sqrt(np.mean((y_true - y_pred) ** 2))

    print(f"  R² score:        {r2:.4f}")
    print(f"  MAE:             {mae:.1f}s")
    print(f"  Median AE:       {median_ae:.1f}s")
    print(f"  RMSE:            {rmse:.1f}s")
    print(f"  Mean actual:     {y_true.mean():.1f}s")
    print(f"  Mean predicted:  {y_pred.mean():.1f}s")

    return {"r2": round(r2, 4), "mae": round(mae, 1), "median_ae": round(median_ae, 1), "rmse": round(rmse, 1)}


# ============================================================================
# Prediction API
# ============================================================================

_mob_model = None
_trv_model = None


def load_models():
    """Load trained models from disk."""
    global _mob_model, _trv_model
    if _mob_model is None:
        with open(MOBILIZATION_MODEL_FILE, "rb") as f:
            _mob_model = pickle.load(f)
    if _trv_model is None:
        with open(TRAVEL_MODEL_FILE, "rb") as f:
            _trv_model = pickle.load(f)
    return _mob_model, _trv_model


def predict_response_time(
    departure_lat, departure_lon,
    intervention_lat, intervention_lon,
    road_distance_m, road_travel_time_sec,
    hour_of_day, day_of_week=1,
    station_id=0, unit_category=2, intervention_type=3,
    straight_line_distance_m=None,
):
    """Predict total response time (mobilization + travel) for a single dispatch."""
    mob_model, trv_model = load_models()

    if straight_line_distance_m is None:
        # Haversine approximation
        import math
        dlat = (intervention_lat - departure_lat) * 111000
        dlon = (intervention_lon - departure_lon) * 111000 * math.cos(math.radians(departure_lat))
        straight_line_distance_m = int(math.sqrt(dlat**2 + dlon**2))

    is_night = 1 if hour_of_day in [22, 23, 0, 1, 2, 3, 4, 5] else 0
    is_weekend = 1 if day_of_week in [0, 6] else 0
    is_rush_hour = 1 if hour_of_day in [7, 8, 9, 17, 18, 19] else 0

    mob_input = pd.DataFrame([{
        "hour_of_day": hour_of_day,
        "day_of_week": day_of_week,
        "is_night": is_night,
        "is_weekend": is_weekend,
        "station_id": station_id,
        "unit_category": unit_category,
        "intervention_type": intervention_type,
    }])

    trv_input = pd.DataFrame([{
        "hour_of_day": hour_of_day,
        "day_of_week": day_of_week,
        "is_night": is_night,
        "is_weekend": is_weekend,
        "is_rush_hour": is_rush_hour,
        "station_id": station_id,
        "unit_category": unit_category,
        "intervention_type": intervention_type,
        "road_distance_m": road_distance_m,
        "road_travel_time_sec": road_travel_time_sec,
        "straight_line_distance_m": straight_line_distance_m,
        "departure_lat": departure_lat,
        "departure_lon": departure_lon,
        "intervention_lat": intervention_lat,
        "intervention_lon": intervention_lon,
    }])

    mobilization = max(0, mob_model.predict(mob_input)[0])
    travel = max(0, trv_model.predict(trv_input)[0])

    return {
        "mobilization_sec": round(mobilization),
        "travel_sec": round(travel),
        "total_sec": round(mobilization + travel),
    }


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] == "train":
        db_host = os.getenv("DB_HOST", "localhost")
        db_name = os.getenv("DB_NAME", "ems")
        db_user = os.getenv("DB_USER", "postgres")
        db_password = os.getenv("DB_PASSWORD", "postgres")

        # CLI overrides
        for i, arg in enumerate(sys.argv):
            if arg == "--db-host" and i + 1 < len(sys.argv): db_host = sys.argv[i + 1]
            if arg == "--db-name" and i + 1 < len(sys.argv): db_name = sys.argv[i + 1]

        df = load_data(db_host, db_name, db_user, db_password)
        train_models(df)

    elif sys.argv[1] == "predict":
        # Quick prediction test
        result = predict_response_time(
            departure_lat=48.907, departure_lon=6.121,
            intervention_lat=48.870, intervention_lon=2.335,
            road_distance_m=2000, road_travel_time_sec=200,
            hour_of_day=14,
        )
        print(json.dumps(result, indent=2))
