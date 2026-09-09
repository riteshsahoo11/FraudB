"""
ML Models and Prediction Operations for BFSI Transaction Intelligence
"""
import joblib
import pandas as pd
import numpy as np
import os
from datetime import datetime
import logging
from typing import Dict, List, Any, Tuple, Optional

logger = logging.getLogger(__name__)

class TransactionPredictor:
    """Main class for handling fraud prediction operations"""
    
    def __init__(self, model_path: str = None):
        # Prefer specific trained models under ml/models/fraud_models, fallback to ml/models/model.pkl
        self.model_path = model_path or self._find_best_model_path()
        self.encoders_dir = os.path.join("ml", "models")
        self.feature_info_path = os.path.join(self.encoders_dir, "feature_info.pkl")
        
        self.model = None
        self.encoders = {}
        self.feature_info = {}
        self.is_loaded = False
        
    def load_model(self) -> bool:
        """Load trained model and encoders"""
        try:
            # Load main model
            if os.path.exists(self.model_path):
                self.model = joblib.load(self.model_path)
                logger.info(f"Model loaded from {self.model_path}")
            else:
                logger.error(f"Model file not found: {self.model_path}")
                return False
            
            # Load feature info
            if os.path.exists(self.feature_info_path):
                self.feature_info = joblib.load(self.feature_info_path)
                logger.info("Feature info loaded")
            
            # Load encoders
            encoder_files = [f for f in os.listdir(self.encoders_dir) if f.endswith('_encoder.pkl')]
            for encoder_file in encoder_files:
                col_name = encoder_file.replace('_encoder.pkl', '')
                encoder_path = os.path.join(self.encoders_dir, encoder_file)
                self.encoders[col_name] = joblib.load(encoder_path)
            
            logger.info(f"Loaded {len(self.encoders)} encoders")
            self.is_loaded = True
            return True
            
        except Exception as e:
            logger.error(f"Error loading model: {str(e)}")
            return False

    def _find_best_model_path(self) -> str:
        """Resolve model path with a hard preference for Gradient Boosting.
        Order of preference:
        1) ml/models/fraud_models/gradient_boosting_model.pkl
        2) ml/models/fraud_models/fraud_model.pkl (fallback)
        3) ml/models/model.pkl (last resort)
        """
        try:
            base_dir = os.path.join("ml", "models")
            fm_dir = os.path.join(base_dir, "fraud_models")

            # Strict preference for Gradient Boosting as requested
            gb_path = os.path.join(fm_dir, "gradient_boosting_model.pkl")
            if os.path.exists(gb_path):
                logger.info(f"Selected Gradient Boosting model: {gb_path}")
                return gb_path

            # Minimal fallbacks for robustness in non-ideal environments
            fraud_path = os.path.join(fm_dir, "fraud_model.pkl")
            if os.path.exists(fraud_path):
                logger.info(f"Gradient model not found; using fraud_model fallback: {fraud_path}")
                return fraud_path

            logger.warning("No preferred model found; falling back to ml/models/model.pkl")
        except Exception as e:
            logger.warning(f"Model auto-discovery failed: {e}")
        # Fallback
        return os.path.join("ml", "models", "model.pkl")
    
    def preprocess_single_transaction(self, transaction_data: Dict[str, Any]) -> pd.DataFrame:
        """Preprocess a single transaction for prediction"""
        try:
            # Convert to DataFrame
            df = pd.DataFrame([transaction_data])
            
            # Standardize column names
            df.columns = (
                df.columns.str.strip().str.lower().str.replace(r"[^a-z0-9]+", "_", regex=True)
            )
            
            # Coerce known numeric-like inputs early (handle empty strings gracefully)
            numeric_like = [
                'transaction_amount', 'account_balance', 'account_age_days',
                'daily_transaction_count', 'failed_transaction_count_7d',
                'ip_address_flag', 'previous_fraudulent_activity', 'risk_score'
            ]
            for col in numeric_like:
                if col in df.columns:
                    # Strip commas and whitespace commonly seen in user-entered numbers
                    try:
                        df[col] = df[col].astype(str).str.replace(r"[\s,]", "", regex=True)
                    except Exception:
                        pass
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            # Normalize boolean/text flags
            if 'kyc_verified' in df.columns:
                try:
                    df['kyc_verified'] = (
                        df['kyc_verified']
                        .astype(str)
                        .str.strip()
                        .str.lower()
                        .map({'true': 1, '1': 1, 'yes': 1, 'false': 0, '0': 0, 'no': 0})
                        .fillna(0)
                        .astype(int)
                    )
                except Exception:
                    df['kyc_verified'] = 0
            
            # Handle missing values
            numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
            if numeric_cols:
                df[numeric_cols] = df[numeric_cols].fillna(df[numeric_cols].median())
            
            categorical_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
            for col in categorical_cols:
                df[col] = df[col].fillna("Unknown")
            
            # Feature engineering (same as preprocessing)
            df = self._apply_feature_engineering(df)
            
            # Apply encoders
            for col, encoder in self.encoders.items():
                if col in df.columns:
                    try:
                        # Handle unknown categories
                        df[col] = df[col].fillna("Unknown").astype(str)
                        
                        # Transform known values, set unknown to -1
                        known_classes = set(encoder.classes_)
                        df[col] = df[col].apply(
                            lambda x: encoder.transform([x])[0] if x in known_classes else -1
                        )
                    except Exception as e:
                        logger.warning(f"Error encoding {col}: {str(e)}")
                        df[col] = -1
            
            # Ensure all expected features are present with robust fallback
            expected_features = self.feature_info.get('numeric_features') if isinstance(self.feature_info, dict) else None
            if not expected_features:
                expected_features = []

            # Prefer model-declared feature names if available
            model_declared = getattr(self.model, 'feature_names_in_', None)
            selected_features = None
            if model_declared is not None and len(model_declared) > 0:
                selected_features = [str(f) for f in model_declared if str(f) != 'fraud_label']
            elif expected_features:
                selected_features = [f for f in expected_features if f != 'fraud_label']
            else:
                # Fallback to numeric columns present in df
                selected_features = [c for c in df.select_dtypes(include=[np.number]).columns if c != 'fraud_label']
                logger.warning('Feature info missing; using numeric columns as fallback')

            # Add any missing selected features with default 0
            for feature in selected_features:
                if feature not in df.columns:
                    df[feature] = 0

            # Order columns exactly as selected_features
            df = df[selected_features]
            # Final safety: coerce everything to numeric and fill NaNs
            df = df.apply(pd.to_numeric, errors='coerce').fillna(0.0)
            
            return df
            
        except Exception as e:
            logger.error(f"Error preprocessing transaction: {str(e)}")
            raise
    
    def _apply_feature_engineering(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply the same feature engineering as in preprocessing"""
        try:
            # DateTime features
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
                df["hour"] = df["timestamp"].dt.hour
                df["day_of_week"] = df["timestamp"].dt.dayofweek
                df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
                df["is_night"] = ((df["hour"] >= 22) | (df["hour"] <= 5)).astype(int)
                df["is_business_hours"] = ((df["hour"] >= 9) & (df["hour"] <= 17)).astype(int)
                df = df.drop("timestamp", axis=1)
            
            # Transaction amount features
            if "transaction_amount" in df.columns:
                amt = pd.to_numeric(df["transaction_amount"], errors="coerce")
                df["is_small_amount"] = (amt <= 10).astype(int)
                df["is_large_amount"] = (amt >= 500).astype(int)
                df["amount_log"] = np.log1p(amt)
                
                if "account_balance" in df.columns:
                    bal = pd.to_numeric(df["account_balance"], errors="coerce").fillna(0.0)
                    df["amount_to_balance_ratio"] = amt / (bal + 1.0)
                    df["is_high_ratio"] = (df["amount_to_balance_ratio"] > 0.1).astype(int)
            
            # Risk-based features
            if "risk_score" in df.columns:
                risk = pd.to_numeric(df["risk_score"], errors="coerce")
                df["is_high_risk"] = (risk > 0.7).astype(int)
                df["is_low_risk"] = (risk < 0.3).astype(int)
            
            # Transaction pattern features
            if "daily_transaction_count" in df.columns:
                daily_count = pd.to_numeric(df["daily_transaction_count"], errors="coerce")
                df["is_high_frequency"] = (daily_count > 10).astype(int)
            
            if "failed_transaction_count_7d" in df.columns:
                failed_count = pd.to_numeric(df["failed_transaction_count_7d"], errors="coerce")
                df["has_recent_failures"] = (failed_count > 0).astype(int)
            
            # Device and location risk
            if "ip_address_flag" in df.columns:
                df["suspicious_ip"] = pd.to_numeric(df["ip_address_flag"], errors="coerce").fillna(0)
            
            if "previous_fraudulent_activity" in df.columns:
                df["has_fraud_history"] = pd.to_numeric(df["previous_fraudulent_activity"], errors="coerce").fillna(0)
            
            # Interaction features
            if all(col in df.columns for col in ["is_night", "is_large_amount"]):
                df["night_large_transaction"] = df["is_night"] * df["is_large_amount"]
            
            if all(col in df.columns for col in ["is_weekend", "has_recent_failures"]):
                df["weekend_with_failures"] = df["is_weekend"] * df["has_recent_failures"]
            
            return df
            
        except Exception as e:
            logger.error(f"Error in feature engineering: {str(e)}")
            return df
    
    def predict_single(self, transaction_data: Dict[str, Any]) -> Dict[str, Any]:
        """Predict fraud for a single transaction"""
        if not self.is_loaded:
            if not self.load_model():
                return {"error": "Model not loaded"}
        
        try:
            # Preprocess
            processed_df = self.preprocess_single_transaction(transaction_data)
            # Enforce numeric dtype before prediction
            try:
                processed_df = processed_df.apply(pd.to_numeric, errors='coerce').fillna(0.0).astype(float)
            except Exception as _e:
                logger.warning(f"Forcing numeric dtype failed, attempting fallback: {_e}")
                processed_df = processed_df.astype(float)
            # Diagnostic: log any non-float columns if present
            try:
                non_float = [c for c, dt in processed_df.dtypes.items() if dt.kind not in ('f', 'i')]
                if non_float:
                    logger.warning(f"Non-numeric columns before predict: {non_float}")
            except Exception:
                pass
            
            # Predict
            prediction = self.model.predict(processed_df)[0]
            probability = self.model.predict_proba(processed_df)[0]
            
            # Calculate risk score
            fraud_probability = probability[1] if len(probability) > 1 else probability[0]
            
            result = {
                "prediction": int(prediction),
                "fraud_probability": float(fraud_probability),
                "risk_level": self._get_risk_level(fraud_probability),
                "confidence": float(max(probability)),
                "timestamp": datetime.now().isoformat()
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Prediction error: {str(e)}")
            return {"error": str(e)}

    def explain_single(self, transaction_data: Dict[str, Any]) -> Dict[str, Any]:
        """Return top feature contributions for a single prediction.
        Tries SHAP first, falls back to importance-weighted deltas.
        Output schema:
        {
            'base_value': float|None,
            'top_contributors': [
                { 'feature': str, 'contribution': float, 'direction': 'fraud'|'legit', 'value': float|int|None }
            ]
        }
        """
        if not self.is_loaded:
            if not self.load_model():
                return {"base_value": None, "top_contributors": []}

        try:
            X = self.preprocess_single_transaction(transaction_data)
        except Exception:
            return {"base_value": None, "top_contributors": []}

        feat_names = list(X.columns)
        explanation = []
        base_value = None

        # Attempt SHAP
        try:
            import shap  # type: ignore
            explainer = None
            try:
                # Prefer TreeExplainer for tree-based models
                explainer = shap.TreeExplainer(self.model)
            except Exception:
                explainer = shap.Explainer(self.model)
            sv = explainer(X)
            values = None
            if hasattr(sv, 'values'):
                vals = sv.values
                if isinstance(vals, np.ndarray):
                    if vals.ndim == 1:
                        values = vals
                    elif vals.ndim == 2:
                        # shape: (samples, features)
                        values = vals[0]
                    elif vals.ndim == 3:
                        # shape: (samples, classes, features) -> use class 1 if exists
                        cls = 1 if vals.shape[1] > 1 else 0
                        values = vals[0, cls, :]
                else:
                    try:
                        values = np.array(vals).squeeze()
                    except Exception:
                        values = None
            base_value = getattr(sv, 'base_values', None)
            try:
                if isinstance(base_value, np.ndarray):
                    base_value = float(np.array(base_value).ravel()[0])
            except Exception:
                base_value = None

            if values is not None:
                pairs = list(zip(feat_names, list(values)))
                pairs.sort(key=lambda t: abs(t[1]), reverse=True)
                top5 = pairs[:5]
                for name, val in top5:
                    direction = 'fraud' if float(val) >= 0 else 'legit'
                    v = None
                    try:
                        v = float(X.iloc[0][name])
                    except Exception:
                        v = None
                    explanation.append({
                        'feature': str(name),
                        'contribution': float(val),
                        'direction': direction,
                        'value': v,
                    })
                return {"base_value": base_value, "top_contributors": explanation}
        except Exception:
            pass

        # Fallback: importance-weighted deltas against baseline means
        try:
            imp = getattr(self.model, 'feature_importances_', None)
            if imp is None or len(imp) != len(feat_names):
                return {"base_value": None, "top_contributors": []}
            imp = np.array(imp, dtype=float)
            if not np.isfinite(imp).any() or imp.sum() <= 0:
                return {"base_value": None, "top_contributors": []}
            baseline = None
            if isinstance(self.feature_info, dict):
                baseline = self.feature_info.get('feature_means')
            if isinstance(baseline, dict):
                base_vec = np.array([float(baseline.get(f, 0.0) or 0.0) for f in feat_names], dtype=float)
            else:
                base_vec = np.zeros(len(feat_names), dtype=float)
            xvec = X.iloc[0].values.astype(float)
            diffs = xvec - base_vec
            norm_imp = imp / (imp.sum() + 1e-12)
            contribs = diffs * norm_imp
            pairs = list(zip(feat_names, list(contribs)))
            pairs.sort(key=lambda t: abs(t[1]), reverse=True)
            top5 = pairs[:5]
            for name, val in top5:
                direction = 'fraud' if float(val) >= 0 else 'legit'
                explanation.append({
                    'feature': str(name),
                    'contribution': float(val),
                    'direction': direction,
                    'value': float(X.iloc[0][name]) if name in X.columns else None,
                })
            return {"base_value": None, "top_contributors": explanation}
        except Exception:
            return {"base_value": None, "top_contributors": []}
    
    def predict_batch(self, transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Predict fraud for multiple transactions"""
        results = []
        
        for i, transaction in enumerate(transactions):
            try:
                result = self.predict_single(transaction)
                result["transaction_id"] = i + 1
                results.append(result)
            except Exception as e:
                logger.error(f"Error processing transaction {i+1}: {str(e)}")
                results.append({
                    "transaction_id": i + 1,
                    "error": str(e)
                })
        
        return results
    
    def _get_risk_level(self, probability: float) -> str:
        """Convert probability to risk level"""
        if probability >= 0.8:
            return "VERY_HIGH"
        elif probability >= 0.6:
            return "HIGH"
        elif probability >= 0.4:
            return "MEDIUM"
        elif probability >= 0.2:
            return "LOW"
        else:
            return "VERY_LOW"
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get model information and statistics"""
        if not self.is_loaded:
            return {"error": "Model not loaded"}
        
        return {
            "model_type": type(self.model).__name__,
            "feature_count": self.feature_info.get('total_features', 0),
            "fraud_rate": self.feature_info.get('fraud_rate', 0),
            "encoders_loaded": len(self.encoders),
            "model_loaded": self.is_loaded,
            "last_updated": datetime.now().isoformat()
        }

# Global predictor instance
predictor = TransactionPredictor()

def initialize_predictor():
    """Initialize the global predictor"""
    return predictor.load_model()

def predict_transaction(transaction_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function for single prediction"""
    return predictor.predict_single(transaction_data)

def predict_transactions_batch(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convenience function for batch prediction"""
    return predictor.predict_batch(transactions)

def get_predictor_info() -> Dict[str, Any]:
    """Get predictor information"""
    return predictor.get_model_info()