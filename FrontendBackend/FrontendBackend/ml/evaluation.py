"""Model evaluation utilities for BFSI Transaction Intelligence.
Computes metrics from the processed training data and the trained model.
Prefers the Gradient Boosting model if available.
"""

import os
import pandas as pd
import numpy as np
import joblib
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, confusion_matrix, classification_report,
)
from sklearn.model_selection import cross_val_score

# Optional plotting libs; not required for metric computation in API context
try:  # noqa: SIM105
    import matplotlib.pyplot as plt  # noqa: F401
    import seaborn as sns  # noqa: F401
except Exception:  # pragma: no cover
    plt = None
    sns = None

# Paths
DATA_PATH = os.path.join("./ml", "data", "transactions_processed.csv")
FALLBACK_MODEL_PATH = os.path.join("./ml", "models", "fraud_models", "fraud_model.pkl")


def _resolve_model_path() -> str:
    """Prefer gradient boosting model; then fallback to other known locations."""
    gb = os.path.join("./ml", "models", "fraud_models", "gradient_boosting_model.pkl")
    if os.path.exists(gb):
        return gb
    if os.path.exists(FALLBACK_MODEL_PATH):
        return FALLBACK_MODEL_PATH
    return os.path.join("./ml", "models", "model.pkl")


def evaluate_model() -> dict:
    """Load processed data/model; compute metrics, CM, and feature importance.

    Returns a dict with keys: accuracy, precision, recall, f1, auc, confusion_matrix,
    feature_importance (pandas.DataFrame or None).
    """
    # Load data
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(f"DATA_PATH not found: {DATA_PATH}")
    df = pd.read_csv(DATA_PATH)

    # Identify target column
    y = None
    for tgt in ("fraud_label", "label", "is_fraud"):
        if tgt in df.columns:
            y = df[tgt].astype(int)
            break
    if y is None:
        raise ValueError("No target column found (expected one of: fraud_label, label, is_fraud)")

    # Select numeric features and drop target if present
    X = df.select_dtypes(include=["number"]).copy()
    if "fraud_label" in X.columns:
        X = X.drop(columns=["fraud_label"])  # keep compatibility

    # Load model
    model_path = _resolve_model_path()
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"Model file not found: {model_path}")
    model = joblib.load(model_path)

    # Align features to model's expected inputs if available
    feat_names = getattr(model, "feature_names_in_", None)
    if feat_names is not None and len(feat_names) > 0:
        # Ensure all expected features exist
        for f in feat_names:
            if f not in X.columns:
                X[f] = 0.0
        # Keep only expected features in correct order
        X = X[[c for c in feat_names if c != 'fraud_label']]
    # Final coercion
    X = X.apply(pd.to_numeric, errors='coerce').fillna(0.0)

    # Predict
    y_pred = model.predict(X)
    # Proba/decision function
    y_proba = None
    try:
        y_proba = model.predict_proba(X)[:, 1]
    except Exception:
        try:
            s = model.decision_function(X)
            # Scale to [0,1]
            s = (s - np.min(s)) / (np.max(s) - np.min(s) + 1e-9)
            y_proba = s
        except Exception:
            y_proba = None

    # Metrics
    accuracy = float(accuracy_score(y, y_pred))
    precision = float(precision_score(y, y_pred, zero_division=0))
    recall = float(recall_score(y, y_pred, zero_division=0))
    f1 = float(f1_score(y, y_pred, zero_division=0))
    try:
        auc = float(roc_auc_score(y, y_proba)) if y_proba is not None else None
    except Exception:
        auc = None

    # Confusion matrix
    cm = confusion_matrix(y, y_pred)

    # ROC Curve data
    roc_curve_data = None
    if y_proba is not None:
        try:
            from sklearn.metrics import roc_curve
            fpr, tpr, thresholds = roc_curve(y, y_proba)
            # Sample points to avoid too much data
            indices = np.linspace(0, len(fpr)-1, min(20, len(fpr)), dtype=int)
            roc_curve_data = {
                'fpr': fpr[indices].tolist(),
                'tpr': tpr[indices].tolist(), 
                'thresholds': thresholds[indices].tolist()
            }
        except Exception as e:
            print(f"ROC curve generation failed: {e}")
            roc_curve_data = None

    # CV (optional, can be heavy) -> keep result for logging only
    try:
        _ = cross_val_score(model, X, y, cv=3, scoring="f1")
    except Exception:
        pass

    # Feature importance (if available)
    fi_df = None
    if hasattr(model, "feature_importances_"):
        try:
            fi_df = pd.DataFrame({
                "feature": X.columns,
                "importance": model.feature_importances_,
            }).sort_values("importance", ascending=False)
        except Exception:
            fi_df = None

    # Verbose prints for standalone use
    try:
        print("\n" + "=" * 50)
        print("MODEL PERFORMANCE METRICS")
        print("=" * 50)
        print(f"Accuracy:  {accuracy:.4f} ({accuracy * 100:.2f}%)")
        print(f"Precision: {precision:.4f} ({precision * 100:.2f}%)")
        print(f"Recall:    {recall:.4f} ({recall * 100:.2f}%)")
        print(f"F1-Score:  {f1:.4f} ({f1 * 100:.2f}%)")
        if auc is not None:
            print(f"ROC-AUC:   {auc:.4f} ({(auc * 100):.2f}%)")
        print("\nCONFUSION MATRIX:")
        print(cm)
        print("\nDETAILED CLASSIFICATION REPORT:")
        print(classification_report(y, y_pred))
    except Exception:
        pass

    return {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "auc": auc,
        "confusion_matrix": cm,
        "roc_curve": roc_curve_data,
        "feature_importance": fi_df,
    }


if __name__ == "__main__":
    try:
        _ = evaluate_model()
        print("\n[SUCCESS] Evaluation completed successfully!")
    except Exception as e:  # pragma: no cover
        print(f"[ERROR] Evaluation failed: {str(e)}")