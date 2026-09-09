from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from accounts.mongo_models import MongoConnection, MongoUser
from bson import ObjectId
from ml.models import predict_transaction, predict_transactions_batch, get_predictor_info, initialize_predictor, predictor
from .notifications import send_to_n8n
from api.rules import RuleEngine
import hashlib
import uuid
import json
import csv
import io
import os
import time
import logging
import pandas as pd
from datetime import datetime, timedelta
# Additional analytics/evaluation imports
import numpy as np
import joblib
import random
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, confusion_matrix, roc_curve as _roc_curve
)
from django.core.cache import cache
from django.contrib.auth import logout
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ========== Authentication APIs ==========

@csrf_exempt
def signup_api(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        username = request.POST.get('username')
        password = request.POST.get('password')
        if not email or not username or not password:
            return JsonResponse({'error': 'Missing fields'}, status=400)
        
        # Check if user already exists using MongoDB
        if MongoUser.find_by_email(email):
            return JsonResponse({'error': 'Email already exists'}, status=400)
        
        # Create user using MongoDB
        user = MongoUser.create_user(
            username=username,
            email=email,
            password=password
        )
        
        return JsonResponse({'status': 'success', 'message': 'User registered'})
    return JsonResponse({'error': 'Invalid request'}, status=400)

@csrf_exempt
def signin_api(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        if not email or not password:
            return JsonResponse({'error': 'Missing fields'}, status=400)
        
        # Authenticate user using Django's authentication system
        user = authenticate(request, username=email, password=password)
        if user is not None:
            return JsonResponse({'status': 'success', 'message': 'Login successful'})
        
        return JsonResponse({'error': 'Invalid credentials'}, status=401)
    return JsonResponse({'error': 'Invalid request'}, status=400)

@csrf_exempt
def forgot_password_api(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        if not email:
            return JsonResponse({'error': 'Missing email'}, status=400)
        
        # Check if user exists using MongoDB
        user = MongoUser.find_by_email(email)
        if not user:
            return JsonResponse({'error': 'Email not found'}, status=404)
        
        # Generate a reset token
        reset_token = str(uuid.uuid4())
        
        # Update user in MongoDB directly since we don't have a reset_token field in Django model
        collection = MongoConnection.get_collection('users')
        collection.update_one({'email': email}, {'$set': {'reset_token': reset_token}})
        
        # For demo, return token in response
        return JsonResponse({'status': 'success', 'reset_token': reset_token})
    return JsonResponse({'error': 'Invalid request'}, status=400)

@csrf_exempt
def reset_password_api(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        reset_token = request.POST.get('reset_token')
        new_password = request.POST.get('new_password')
        if not email or not reset_token or not new_password:
            return JsonResponse({'error': 'Missing fields'}, status=400)
        
        # Check if user exists with valid reset token using MongoDB directly
        collection = MongoConnection.get_collection('users')
        user_data = collection.find_one({'email': email, 'reset_token': reset_token})
        if not user_data:
            return JsonResponse({'error': 'Invalid token or email'}, status=401)
        
        # Get user from MongoDB and update password
        user = MongoUser.find_by_email(email)
        if not user:
            return JsonResponse({'error': 'User not found'}, status=404)
        
        user.set_password(new_password)
        user.save()
        
        # Clear reset token in MongoDB
        collection.update_one(
            {'email': email},
            {'$unset': {'reset_token': ""}}
        )
        
        return JsonResponse({'status': 'success', 'message': 'Password reset successful'})
    return JsonResponse({'error': 'Invalid request'}, status=400)

# ========== ML Prediction APIs ==========

@csrf_exempt
@login_required
@require_http_methods(["POST"])
def predict_single_transaction_api(request):
    """API endpoint for single transaction prediction"""
    try:
        # Initialize predictor if needed
        if not initialize_predictor():
            return JsonResponse({
                'error': 'Model not available',
                'message': 'Please ensure model.pkl is in ml/models/ directory'
            }, status=500)
        
        # Parse JSON data
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON data'}, status=400)
        
        # Validate required fields
        required_fields = ['transaction_amount', 'account_balance']
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            return JsonResponse({
                'error': 'Missing required fields',
                'missing_fields': missing_fields
            }, status=400)
        
        # Make prediction
        result = predict_transaction(data)
        
        if 'error' in result:
            return JsonResponse(result, status=500)
        
        # Store prediction in MongoDB
        try:
            predictions_collection = MongoConnection.get_collection('predictions')
            prediction_record = {
                'user_id': str(request.user.id),
                'user_email': request.user.email,
                'input_data': data,
                'prediction_result': result,
                'created_at': datetime.now(),
                'prediction_type': 'single'
            }
            predictions_collection.insert_one(prediction_record)
        except Exception as e:
            logger.warning(f"Failed to store prediction: {str(e)}")
        
        return JsonResponse({
            'status': 'success',
            'prediction': result
        })
        
    except Exception as e:
        logger.error(f"Single prediction API error: {str(e)}")
        return JsonResponse({'error': 'Prediction failed', 'details': str(e)}, status=500)


# ========== New REST API (Production) ==========

def _model_version() -> str:
    try:
        path = getattr(predictor, 'model_path', None) or ''
        if path and os.path.exists(path):
            st = os.stat(path)
            return f"{os.path.basename(path)}:{int(st.st_mtime)}:{st.st_size}"
    except Exception:
        pass
    return "unknown"

def _risk_level_from_score(score: float) -> str:
    if score >= 0.8:
        return "VERY_HIGH"
    if score >= 0.6:
        return "HIGH"
    if score >= 0.4:
        return "MEDIUM"
    if score >= 0.2:
        return "LOW"
    return "VERY_LOW"



def _parse_date(v):
    try:
        if not v:
            return None
        return datetime.fromisoformat(v.replace('Z', '+00:00'))
    except Exception:
        return None

@csrf_exempt
@login_required
@require_http_methods(["POST"])
def predict_api(request):
    """POST /api/predict - Single transaction prediction with rules and persistence"""
    logger.debug(">>> PREDICT API CALLED - NEW VERSION 2.0 <<<")
    try:
        if not initialize_predictor():
            return JsonResponse({'error': 'Model not available'}, status=500)

        try:
            data = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        start = time.time()
        ml_result = predict_transaction(data)
        if 'error' in ml_result:
            # Propagate details so UI can show actionable reason
            err_msg = str(ml_result.get('error') or 'Unknown error')
            logger.error(f"Predict API model error: {err_msg}")
            return JsonResponse({'error': 'Prediction failed', 'details': err_msg}, status=500)

        # Evaluate rules using centralized policy
        policy = getattr(settings, 'PREDICTION_POLICY', {}) or {}
        engine = RuleEngine(policy)
        rules, adjust = engine.evaluate(data)
        fraud_prob = float(ml_result.get('fraud_probability', 0.0) or 0.0)
        combined_risk = max(0.0, min(1.0, fraud_prob + adjust))
        risk_level = _risk_level_from_score(combined_risk)
        # Final decision based on combined risk and configurable threshold
        try:
            threshold = float(policy.get('decision_threshold', getattr(settings, 'PREDICTION_DECISION_THRESHOLD', 0.5)))
        except Exception:
            threshold = 0.5
        final_pred = 1 if combined_risk >= threshold else 0

        txn_id = str(uuid.uuid4())
        processing_ms = int((time.time() - start) * 1000)
        model_ver = _model_version()

        # Local explanation (top-5 contributions)
        try:
            explanation = predictor.explain_single(data)
        except Exception:
            explanation = {'base_value': None, 'top_contributors': []}

        # Construct record per required schema
        # Helper to safely coerce numeric inputs
        def _safe_numeric(val, default=None):
            if val is None or val == '':
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                return default
        
        def _safe_int(val, default=0):
            if val is None or val == '':
                return default
            try:
                return int(float(val))  # Convert via float first to handle '1.0' strings
            except (ValueError, TypeError):
                return default
        
        record = {
            'transaction_id': txn_id,
            'timestamp': _parse_date(data.get('timestamp')) or datetime.now(),
            # Minimal context for analytics (no raw inputs)
            'channel': data.get('channel'),
            'transaction_amount': _safe_numeric(data.get('transaction_amount')),
            # Model and decision metadata
            'model_prediction': _safe_int(ml_result.get('prediction', 0)),
            'model_fraud_probability': fraud_prob,
            'prediction': final_pred,
            'risk_score': combined_risk,
            'confidence_level': float(ml_result.get('confidence', 0.0) or 0.0),
            'risk_level': risk_level,
            'rules_triggered': [r.name for r in rules if r.triggered],
            'reason': '; '.join([r.reason for r in rules if r.triggered]) or 'ML prediction',
            'model_version': model_ver,
            'processing_time_ms': processing_ms,
            'user_id': str(request.user.id),
            'created_at': datetime.now(),
            'updated_at': datetime.now(),
            'source': 'single',
            'explanation': explanation,
            'decision_threshold': threshold,
        }

        # Save to Mongo
        try:
            coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
            coll.insert_one(record)
            
            # Clear dashboard cache so new prediction shows immediately
            from django.core.cache import cache
            cache_key = f'dashboard_stats_{request.user.id}'
            cache.delete(cache_key)
            logger.info(f"Cleared dashboard cache for user {request.user.id}")
        except Exception as e:
            logger.warning(f"Failed to store fraud prediction: {e}")

        # Alert generation
        try:
            if combined_risk >= 0.6:
                alerts = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('system_alerts', 'system_alerts'))
                severity = 'CRITICAL' if combined_risk >= 0.8 else 'HIGH'
                alerts.insert_one({
                    'alert_type': 'FRAUD_RISK',
                    'severity': severity,
                    'transaction_id': txn_id,
                    'triggered_rules': [r.name for r in rules if r.triggered],
                    'alert_timestamp': datetime.now(),
                    'resolved_status': False,
                    'assigned_to': None,
                    'notification_sent': False,
                    'escalation_level': 0,
                    'user_id': str(request.user.id),
                })
        except Exception as e:
            logger.warning(f"Failed to create alert: {e}")

        # N8N notify
        try:
            send_to_n8n('prediction', {
                'transaction_id': txn_id,
                'risk_level': risk_level,
                'risk_score': combined_risk,
                'prediction': _safe_int(ml_result.get('prediction', 0)),
                'fraud_probability': float(ml_result.get('fraud_probability', 0.0) or 0.0),
                'model_version': model_ver,
                'processing_time_ms': processing_ms,
                'rules_triggered': [r.name for r in rules if r.triggered],
                'explanation': explanation,
            }, request.user)
        except Exception:
            pass

        return JsonResponse({
            'status': 'success',
            'transaction_id': txn_id,
            'prediction': {
                **ml_result,
                'risk_score': combined_risk,
                'risk_level': risk_level,
                'rules_triggered': [r.name for r in rules if r.triggered],
                'reason': '; '.join([r.reason for r in rules if r.triggered]) or 'ML prediction',
                'model_version': model_ver,
                'processing_time_ms': processing_ms,
                'explanation': explanation,
                # Overwrite/augment with final decision and metadata so UI uses it
                'prediction': final_pred,
                'model_prediction': _safe_int(ml_result.get('prediction', 0)),
                'model_fraud_probability': fraud_prob,
                'decision_threshold': threshold,
            }
        })
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f">>> PREDICT API EXCEPTION <<<\n{error_details}")
        return JsonResponse({
            'status': 'error',
            'error': str(e),
            'details': str(e),
            'message': f'Prediction failed: {str(e)}'
        }, status=500)


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def upload_api(request):
    """POST /api/upload - Batch processing with file metadata only and per-row persistence"""
    try:
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'No file uploaded'}, status=400)

        file = request.FILES['file']
        fname = file.name
        fsize = getattr(file, 'size', 0)
        ftype = 'csv' if fname.endswith('.csv') else 'xlsx' if fname.endswith('.xlsx') else 'json' if fname.endswith('.json') else 'unknown'

        # Create file metadata doc
        fu_coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('file_uploads', 'file_uploads'))
        upload_doc = {
            'filename': fname,
            'file_size': fsize,
            'file_type': ftype,
            'upload_timestamp': datetime.now(),
            'total_records': 0,
            'processed_records': 0,
            'fraud_count': 0,
            'legit_count': 0,
            'processing_status': 'processing',
            'error_logs': [],
            'user_id': str(request.user.id)
        }
        upload_id = fu_coll.insert_one(upload_doc).inserted_id

        # Ensure model
        if not initialize_predictor():
            fu_coll.update_one({'_id': upload_id}, {'$set': {'processing_status': 'failed', 'error_logs': ['Model not available']}})
            return JsonResponse({'error': 'Model not available'}, status=500)

        policy = getattr(settings, 'PREDICTION_POLICY', {}) or {}
        engine = RuleEngine(policy)
        results = []
        errors = 0
        fraud = 0
        legit = 0
        processed = 0

        def process_row(row_dict):
            nonlocal fraud, legit, processed
            ml_res = predict_transaction(row_dict)
            if 'error' in ml_res:
                return {'error': ml_res['error']}
            rules, adjust = engine.evaluate(row_dict)
            fraud_prob = float(ml_res.get('fraud_probability', 0.0) or 0.0)
            combined = max(0.0, min(1.0, fraud_prob + adjust))
            rlevel = _risk_level_from_score(combined)
            try:
                threshold = float(policy.get('decision_threshold', getattr(settings, 'PREDICTION_DECISION_THRESHOLD', 0.5)))
            except Exception:
                threshold = 0.5
            final_pred = 1 if combined >= threshold else 0
            txn_id = str(uuid.uuid4())
            
            # Safe numeric coercion for storage
            def _safe_num(v):
                if v is None or v == '':
                    return None
                try:
                    return float(v)
                except (ValueError, TypeError):
                    return None
            
            def _safe_int_batch(v, default=0):
                if v is None or v == '':
                    return default
                try:
                    return int(float(v))
                except (ValueError, TypeError):
                    return default
            
            rec = {
                'transaction_id': txn_id,
                'timestamp': _parse_date(row_dict.get('timestamp')) or datetime.now(),
                # Minimal context for analytics (no raw inputs)
                'channel': row_dict.get('channel'),
                'transaction_amount': _safe_num(row_dict.get('transaction_amount')),
                # Model and decision metadata
                'model_prediction': _safe_int_batch(ml_res.get('prediction', 0)),
                'model_fraud_probability': fraud_prob,
                'prediction': final_pred,
                'risk_score': combined,
                'risk_level': rlevel,
                'confidence_level': float(ml_res.get('confidence', 0.0) or 0.0),
                'rules_triggered': [r.name for r in rules if r.triggered],
                'reason': '; '.join([r.reason for r in rules if r.triggered]) or 'ML prediction',
                'model_version': _model_version(),
                'processing_time_ms': None,
                'user_id': str(request.user.id),
                'created_at': datetime.now(),
                'updated_at': datetime.now(),
                'batch_id': str(upload_id),
                'source': 'batch',
                'decision_threshold': threshold,
            }
            if final_pred == 1:
                fraud += 1
            else:
                legit += 1
            processed += 1
            return {
                'transaction_id': txn_id,
                **ml_res,
                'prediction': final_pred,
                'model_prediction': _safe_int_batch(ml_res.get('prediction', 0)),
                'model_fraud_probability': fraud_prob,
                'risk_score': combined,
                'risk_level': rlevel,
                'rules_triggered': rec['rules_triggered'],
                'reason': rec['reason'],
                'decision_threshold': threshold,
            }, rec

        # Parse and stream
        pred_coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        to_insert = []

        try:
            if ftype == 'csv':
                content = file.read().decode('utf-8', errors='ignore')
                reader = csv.DictReader(io.StringIO(content))
                for i, row in enumerate(reader):
                    out, rec = process_row(row)
                    if 'error' in out:
                        errors += 1
                    else:
                        results.append(out)
                        to_insert.append(rec)
                    if len(to_insert) >= 500:
                        pred_coll.insert_many(to_insert)
                        to_insert.clear()
            elif ftype == 'xlsx':
                df = pd.read_excel(file)
                for _, row in df.iterrows():
                    out, rec = process_row({k: row[k] for k in df.columns})
                    if 'error' in out:
                        errors += 1
                    else:
                        results.append(out)
                        to_insert.append(rec)
                    if len(to_insert) >= 500:
                        pred_coll.insert_many(to_insert)
                        to_insert.clear()
            elif ftype == 'json':
                data = json.loads(file.read().decode('utf-8'))
                rows = data if isinstance(data, list) else [data]
                for row in rows:
                    out, rec = process_row(row)
                    if 'error' in out:
                        errors += 1
                    else:
                        results.append(out)
                        to_insert.append(rec)
                    if len(to_insert) >= 500:
                        pred_coll.insert_many(to_insert)
                        to_insert.clear()
            else:
                raise ValueError('Unsupported file type')
        except Exception as e:
            logger.error(f"Upload processing error: {e}")
            errors += 1

        if to_insert:
            try:
                pred_coll.insert_many(to_insert)
            except Exception as e:
                logger.warning(f"Bulk insert warning: {e}")

        # Update file upload summary
        fu_coll.update_one({'_id': upload_id}, {'$set': {
            'total_records': processed + errors,
            'processed_records': processed,
            'fraud_count': fraud,
            'legit_count': legit,
            'processing_status': 'completed' if errors == 0 else 'completed_with_errors'
        }})

        summary = {
            'total_transactions': processed + errors,
            'fraud_detected': fraud,
            'legitimate_transactions': legit,
            'errors': errors,
            'fraud_rate': (fraud / max(1, processed)) * 100.0
        }

        # N8N notify
        try:
            send_to_n8n('batch_summary', {
                'file_id': str(upload_id),
                'filename': fname,
                'summary': summary,
            }, request.user)
        except Exception:
            pass

        return JsonResponse({
            'status': 'success',
            'summary': summary,
            'results': results[:100],
            'total_results': processed + errors,
            'file_id': str(upload_id),
        })
    except Exception as e:
        logger.error(f"Upload API error: {e}")
        return JsonResponse({'error': 'Upload failed', 'details': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def transactions_bulk_delete_api(request):
    """POST /api/transactions/bulk-delete
    Body: {"ids": ["...ObjectId...", ...]}
    Deletes predictions owned by the user. Clears dashboard cache.
    """
    try:
        try:
            body = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        ids = body.get('ids') or []
        if not isinstance(ids, list) or not ids:
            return JsonResponse({'error': 'No ids provided'}, status=400)
        try:
            obj_ids = [ObjectId(x) for x in ids]
        except Exception:
            return JsonResponse({'error': 'Invalid ids'}, status=400)
        coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        res = coll.delete_many({'_id': {'$in': obj_ids}, 'user_id': str(request.user.id)})
        # Clear dashboard cache
        cache.delete(f'dashboard_stats_{request.user.id}')
        return JsonResponse({'status': 'success', 'deleted': int(getattr(res, 'deleted_count', 0))})
    except Exception as e:
        logger.error(f"Bulk delete error: {e}")
        return JsonResponse({'error': 'Bulk delete failed'}, status=500)


@login_required
@require_http_methods(["POST"])
def upload_delete_api(request, upload_id: str):
    """POST /api/uploads/<upload_id>/delete
    Deletes the file upload doc and any predictions linked via batch_id.
    Clears dashboard cache.
    """
    try:
        fu_coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('file_uploads', 'file_uploads'))
        try:
            _id = ObjectId(upload_id)
        except Exception:
            return JsonResponse({'error': 'Invalid id'}, status=400)
        doc = fu_coll.find_one({'_id': _id})
        if not doc:
            return JsonResponse({'error': 'Not found'}, status=404)
        if str(doc.get('user_id')) != str(request.user.id):
            return JsonResponse({'error': 'Forbidden'}, status=403)
        # Delete associated predictions
        pred_coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        pred_coll.delete_many({'batch_id': str(_id), 'user_id': str(request.user.id)})
        fu_coll.delete_one({'_id': _id})
        # Clear cache so stale data disappears
        cache.delete(f'dashboard_stats_{request.user.id}')
        return JsonResponse({'status': 'success'})
    except Exception as e:
        logger.error(f"Upload delete error: {e}")
        return JsonResponse({'error': 'Delete failed'}, status=500)

@login_required
@require_http_methods(["POST"])
def account_delete_api(request):
    """POST /api/account/delete - Permanently delete the current user's account and all related data.
    Deletes Mongo documents in fraud_predictions, file_uploads, system_alerts for this user,
    clears caches, logs out the session, and removes the Django user account.
    """
    try:
        user_id = str(request.user.id)
        db = MongoConnection.get_database()
        pred = db.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        uploads = db.get_collection(settings.MONGO_COLLECTIONS.get('file_uploads', 'file_uploads'))
        alerts = db.get_collection(settings.MONGO_COLLECTIONS.get('system_alerts', 'system_alerts'))
        users_coll = db.get_collection(settings.MONGO_COLLECTIONS.get('users', 'users'))
        activities = db.get_collection(settings.MONGO_COLLECTIONS.get('user_activities', 'user_activities'))

        # Delete docs
        try:
            pred.delete_many({'user_id': user_id})
        except Exception:
            pass
        try:
            uploads.delete_many({'user_id': user_id})
        except Exception:
            pass
        try:
            alerts.delete_many({'user_id': user_id})
        except Exception:
            pass
        try:
            # Remove user profile in Mongo 'users' by multiple keys
            users_coll.delete_many({'$or': [
                {'user_id': user_id},
                {'email': request.user.email},
                {'email1': request.user.email},
                {'username': request.user.username},
            ]})
        except Exception:
            pass
        try:
            activities.delete_many({'user_id': user_id})
        except Exception:
            pass

        # Clear dashboard cache for this user
        try:
            cache.delete(f'dashboard_stats_{request.user.id}')
        except Exception:
            pass

        # Log out before deleting the Django user to invalidate session
        try:
            logout(request)
        except Exception:
            pass

        # Remove Django user
        try:
            request.user.delete()
        except Exception:
            # If deletion fails, still return success for data wipe and logout
            pass

        return JsonResponse({'status': 'success'})
    except Exception as e:
        logger.error(f"Account delete error: {e}")
        return JsonResponse({'error': 'Account deletion failed', 'details': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])  # bootstrap without needing login for local demo via secret
def bootstrap_demo_api(request):
    """POST /api/bootstrap-demo?secret=demo
    - Creates/updates a test user and seeds exactly 100 demo predictions for that user only
    - Removes any previous demo data from everyone else (safe, pattern-based)
    - Populates model_performance with a minimal metrics document
    Returns credentials for the test user
    """
    secret = request.GET.get('secret') or request.POST.get('secret')
    if secret not in (os.environ.get('DEMO_BOOTSTRAP_SECRET') or 'demo',):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    try:
        email = 'test@fraudb.ai'
        username = 'testuser'
        password = 'password123'

        # Ensure Mongo user exists (project uses Mongo-backed users)
        try:
            mu = MongoUser.find_by_email(email)
        except Exception:
            mu = None
        if not mu:
            try:
                mu = MongoUser.find_by_username(email)
            except Exception:
                mu = None
        if not mu:
            mu = MongoUser.create_user(username=username, email=email, password=password)
        else:
            # Reset password and ensure flags
            mu.set_password(password)
            mu.first_name = getattr(mu, 'first_name', '') or 'Test'
            mu.last_name = getattr(mu, 'last_name', '') or 'User'
            mu.is_active = True
            mu.is_email_verified = True
            if not getattr(mu, 'date_joined', None):
                mu.date_joined = datetime.now()
            mu.last_login = datetime.now()
            mu.save()

        user_id = str(mu.id)
        db = MongoConnection.get_database()
        pred_coll = db.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        up_coll = db.get_collection(settings.MONGO_COLLECTIONS.get('file_uploads', 'file_uploads'))
        perf_coll = db.get_collection(settings.MONGO_COLLECTIONS.get('model_performance', 'model_performance'))
        users_coll = db.get_collection(settings.MONGO_COLLECTIONS.get('users', 'users'))

        # Remove previous demo data for everyone
        pred_coll.delete_many({'reason': {'$regex': 'Demo data', '$options': 'i'}})
        up_coll.delete_many({'filename': {'$regex': 'demo_', '$options': 'i'}})

        # Remove any existing data for the test user as well
        pred_coll.delete_many({'user_id': user_id})
        up_coll.delete_many({'user_id': user_id})

        # Ensure a Users profile document exists for Compass visibility
        users_coll.update_one(
            {'$or': [ {'user_id': user_id}, {'email': email}, {'email1': email} ]},
            {'$set': {
                'user_id': user_id,
                'username': username,
                'email': email,
                'email1': email,
                'password': mu.password,  # hashed via Django hasher
                'first_name': getattr(mu, 'first_name', '') or 'Test',
                'last_name': getattr(mu, 'last_name', '') or 'User',
                'role': 'viewer',
                'is_active': True,
                'is_email_verified': True,
                'date_joined': getattr(mu, 'date_joined', None) or datetime.now(),
                'last_login': getattr(mu, 'last_login', None) or datetime.now(),
            }},
            upsert=True
        )

        # Prune any other user documents so Compass only shows the test user
        try:
            users_coll.delete_many({
                '$and': [
                    { 'user_id': { '$ne': user_id } },
                    { 'email': { '$ne': email } },
                    { 'email1': { '$ne': email } },
                ]
            })
        except Exception:
            pass

        # Create one upload
        up_id = up_coll.insert_one({
            'filename': 'demo_data.csv',
            'file_size': 2048,
            'file_type': 'csv',
            'upload_timestamp': datetime.now(),
            'total_records': 100,
            'processed_records': 100,
            'fraud_count': 0,
            'legit_count': 0,
            'processing_status': 'completed',
            'error_logs': [],
            'user_id': user_id,
        }).inserted_id

        # Seed 100 predictions
        import random
        channels = ['ONLINE','BRANCH','ATM','MOBILE','THIRD_PARTY','P2P']

        def risk_level(s: float) -> str:
            if s >= 0.8: return 'VERY_HIGH'
            if s >= 0.6: return 'HIGH'
            if s >= 0.4: return 'MEDIUM'
            if s >= 0.2: return 'LOW'
            return 'VERY_LOW'

        docs = []
        fraud_ct = 0
        for i in range(100):
            score = random.random()
            if random.random() < 0.3:
                score = 0.6 + random.random()*0.4
            else:
                score = random.random()*0.5
            pred = 1 if score >= 0.5 else 0
            if pred == 1:
                fraud_ct += 1
            ts = datetime.now() - timedelta(days=random.randint(0, 13), hours=random.randint(0,23))
            docs.append({
                'transaction_id': str(uuid.uuid4()),
                'timestamp': ts,
                'channel': random.choice(channels),
                'transaction_amount': round(random.random()*2000, 2),
                'model_prediction': pred,
                'model_fraud_probability': round(score, 4),
                'prediction': pred,
                'risk_score': score,
                'risk_level': risk_level(score),
                'confidence_level': round(random.uniform(0.5, 0.99), 2),
                'rules_triggered': [],
                'reason': 'Demo data for visualization',
                'model_version': 'demo',
                'processing_time_ms': random.randint(20, 120),
                'user_id': user_id,
                'created_at': ts,
                'updated_at': ts,
                'batch_id': str(up_id),
                'source': 'batch',
                'decision_threshold': 0.5,
            })
        if docs:
            pred_coll.insert_many(docs)
        up_coll.update_one({'_id': up_id}, {'$set': {'fraud_count': fraud_ct, 'legit_count': (100 - fraud_ct)}})

        # Populate model_performance with a minimal document
        perf_coll.delete_many({})
        perf_coll.insert_one({
            'evaluation_date': datetime.now(),
            'metrics': {
                'accuracy': 0.9993,
                'precision': 0.9978,
                'recall': 1.0,
                'f1': 0.9989,
                'auc': 1.0,
                'specificity': 0.999,
            },
            'confusion_matrix': [[33897,36],[0,16067]],
            'roc_curve': {'fpr': [0,0,1], 'tpr': [0,1,1], 'thresholds': [1,0.5,0]}
        })

        # Clear caches
        try:
            cache.delete_pattern('dashboard_stats_*')
        except Exception:
            pass

        return JsonResponse({
            'status': 'success',
            'seeded': 100,
            'user': {'email': email, 'password': password, 'id': user_id}
        })
    except Exception as e:
        logger.error(f"Bootstrap demo error: {e}")
        return JsonResponse({'error': 'Bootstrap failed', 'details': str(e)}, status=500)
@login_required
@require_http_methods(["POST"]) 
def seed_dummy_data_api(request):
    """POST /api/seed-dummy?count=100
    Clears current user's predictions and uploads, then seeds N dummy predictions
    spanning recent days so charts have data. Also clears dashboard cache.
    """
    try:
        n = 100
        try:
            n = max(1, min(1000, int(request.GET.get('count', '100'))))
        except Exception:
            n = 100

        coll_pred = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        coll_uploads = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('file_uploads', 'file_uploads'))

        # Remove existing user data
        coll_pred.delete_many({'user_id': str(request.user.id)})
        coll_uploads.delete_many({'user_id': str(request.user.id)})

        # Seed one upload record
        up_id = coll_uploads.insert_one({
            'filename': 'dummy_seed.csv',
            'file_size': 1024,
            'file_type': 'csv',
            'upload_timestamp': datetime.now(),
            'total_records': n,
            'processed_records': n,
            'fraud_count': 0,
            'legit_count': 0,
            'processing_status': 'completed',
            'error_logs': [],
            'user_id': str(request.user.id),
        }).inserted_id

        channels = ['ONLINE','BRANCH','ATM','MOBILE','THIRD_PARTY','P2P']
        docs = []
        fraud_ct = 0
        from datetime import timedelta
        for i in range(n):
            score = random.random()
            # Make ~30% fraud
            if random.random() < 0.3:
                score = 0.6 + random.random()*0.4
            else:
                score = random.random()*0.5
            pred = 1 if score >= 0.5 else 0
            if pred == 1:
                fraud_ct += 1
            ts = datetime.now() - timedelta(days=random.randint(0, 13), hours=random.randint(0,23), minutes=random.randint(0,59))
            docs.append({
                'transaction_id': str(uuid.uuid4()),
                'timestamp': ts,
                'channel': random.choice(channels),
                'transaction_amount': round(random.random()*2000, 2),
                'model_prediction': pred,
                'model_fraud_probability': round(score, 4),
                'prediction': pred,
                'risk_score': score,
                'risk_level': _risk_level_from_score(score),
                'confidence_level': round(random.uniform(0.5, 0.99), 2),
                'rules_triggered': [],
                'reason': 'Seeded dummy data',
                'model_version': 'seed',
                'processing_time_ms': random.randint(20, 120),
                'user_id': str(request.user.id),
                'created_at': ts,
                'updated_at': ts,
                'batch_id': str(up_id),
                'source': 'batch',
                'decision_threshold': 0.5,
            })
        if docs:
            coll_pred.insert_many(docs)
        coll_uploads.update_one({'_id': up_id}, {'$set': {'fraud_count': fraud_ct, 'legit_count': (n - fraud_ct)}})

        cache.delete(f'dashboard_stats_{request.user.id}')
        return JsonResponse({'status': 'success', 'seeded': n})
    except Exception as e:
        logger.error(f"Seed dummy error: {e}")
        return JsonResponse({'error': 'Seeding failed', 'details': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def analytics_api(request):
    """GET /api/analytics - Aggregated dashboard analytics with optional date filters"""
    try:
        start_date = _parse_date(request.GET.get('start_date'))
        end_date = _parse_date(request.GET.get('end_date'))
        if end_date:
            # Include end of the day
            end_date = end_date + timedelta(days=1)

        coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        match = {'user_id': str(request.user.id)}
        if start_date:
            match['timestamp'] = match.get('timestamp', {})
            match['timestamp']['$gte'] = start_date
        if end_date:
            match['timestamp'] = match.get('timestamp', {})
            match['timestamp']['$lt'] = end_date

        # Fraud vs Legit and risk levels
        pipeline = [
            {'$match': match},
            {'$group': {
                '_id': None,
                'fraud': {'$sum': {'$cond': [{'$eq': ['$prediction', 1]}, 1, 0]}},
                'legitimate': {'$sum': {'$cond': [{'$eq': ['$prediction', 0]}, 1, 0]}},
            }}
        ]
        agg = list(coll.aggregate(pipeline))
        class_distribution = {'fraud': 0, 'legitimate': 0}
        if agg:
            class_distribution['fraud'] = int(agg[0].get('fraud', 0))
            class_distribution['legitimate'] = int(agg[0].get('legitimate', 0))

        # Risk levels counts
        risk_counts = {}
        pipeline_risk = [
            {'$match': match},
            {'$group': {'_id': '$risk_level', 'count': {'$sum': 1}}}
        ]
        for d in coll.aggregate(pipeline_risk):
            k = (d.get('_id') or 'UNKNOWN').upper()
            risk_counts[k] = int(d.get('count', 0))

        # Over time (last 14 days by default) - total count and fraud% per day
        from collections import defaultdict
        daily_total = defaultdict(int)
        daily_fraud = defaultdict(int)
        from_dt = datetime.now() - timedelta(days=13)
        match_time = dict(match)
        match_time['timestamp'] = {'$gte': from_dt}
        for d in coll.find(match_time, {'timestamp': 1, 'prediction': 1}):
            ts = d.get('timestamp') or datetime.now()
            if not isinstance(ts, datetime):
                try:
                    ts = datetime.fromisoformat(str(ts))
                except Exception:
                    ts = datetime.now()
            key = ts.strftime('%Y-%m-%d')
            daily_total[key] += 1
            if int(d.get('prediction') or 0) == 1:
                daily_fraud[key] += 1
        series = []
        fraud_rate_series = []
        for i in range(13, -1, -1):
            day = datetime.now() - timedelta(days=i)
            key = day.strftime('%Y-%m-%d')
            total = int(daily_total.get(key, 0))
            fraud_ct = int(daily_fraud.get(key, 0))
            pct = (fraud_ct / total * 100.0) if total > 0 else 0.0
            series.append({'date': key, 'count': total})
            fraud_rate_series.append({'date': key, 'fraud_pct': pct})

        # Channel-wise fraud distribution (only frauds)
        channel_fraud = {}
        for d in coll.aggregate([
            {'$match': {**match, 'prediction': 1}},
            {'$group': {'_id': '$channel', 'count': {'$sum': 1}}}
        ]):
            channel_fraud[str(d.get('_id') or 'UNKNOWN')] = int(d.get('count', 0))

        # Transaction Amount vs Fraud (sample last 500 with amount)
        amount_points = []
        try:
            cur = coll.find({**match, 'transaction_amount': {'$ne': None}}, {'transaction_amount': 1, 'prediction': 1, 'timestamp': 1}) \
                       .sort('timestamp', -1).limit(500)
            for d in cur:
                try:
                    x = float(d.get('transaction_amount'))
                    y = 1 if int(d.get('prediction') or 0) == 1 else 0
                    amount_points.append({'x': x, 'y': y})
                except Exception:
                    pass
        except Exception:
            amount_points = []

        insights = {
            'class_distribution': class_distribution,
            'risk_levels': risk_counts,
            'over_time': series,
            'fraud_rate_over_time': fraud_rate_series,
            'channel_fraud': channel_fraud,
            'amount_vs_fraud': amount_points,
        }
        if request.GET.get('format') == 'csv':
            # Export insights summary as CSV
            import csv as _csv
            from io import StringIO
            s = StringIO()
            w = _csv.writer(s)
            w.writerow(['metric', 'key', 'value'])
            for k, v in class_distribution.items():
                w.writerow(['class_distribution', k, v])
            for k, v in risk_counts.items():
                w.writerow(['risk_levels', k, v])
            for r in series:
                w.writerow(['over_time', r['date'], r['count']])
            for r in fraud_rate_series:
                w.writerow(['fraud_rate_over_time', r['date'], f"{r['fraud_pct']:.2f}%"]) 
            for k, v in channel_fraud.items():
                w.writerow(['channel_fraud', k, v])
            resp = HttpResponse(s.getvalue(), content_type='text/csv')
            resp['Content-Disposition'] = 'attachment; filename="analytics_report.csv"'
            return resp
        return JsonResponse({'status': 'success', 'insights': insights})
    except Exception as e:
        logger.error(f"Analytics API error: {e}")
        return JsonResponse({'error': 'Failed to compute analytics'}, status=500)


@login_required
@require_http_methods(["GET"])
def transactions_api(request):
    """GET /api/transactions - History with pagination, filters, sorting, export"""
    try:
        coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        q = {'user_id': str(request.user.id)}
        
        # Filters
        # Prediction filter (fraud/legit)
        prediction = request.GET.get('prediction')
        if prediction is not None:
            try:
                q['prediction'] = int(prediction)
            except:
                pass
        
        risk = request.GET.get('risk_level')
        if risk:
            q['risk_level'] = risk.upper()
        channel = request.GET.get('channel')
        if channel:
            q['channel'] = channel
        start_date = _parse_date(request.GET.get('start_date'))
        end_date = _parse_date(request.GET.get('end_date'))
        if start_date or end_date:
            q['timestamp'] = {}
            if start_date:
                q['timestamp']['$gte'] = start_date
            if end_date:
                q['timestamp']['$lt'] = end_date + timedelta(days=1)

        # Sorting
        sort_param = request.GET.get('sort', request.GET.get('sort_by', 'timestamp'))
        if sort_param == 'recent':
            sort_by = 'created_at'
            sort_dir = -1  # Most recent first
        else:
            sort_by = sort_param
            sort_dir = -1 if request.GET.get('order', 'desc').lower() == 'desc' else 1

        # Pagination
        page = max(1, int(request.GET.get('page', 1)))
        page_size = min(100, max(1, int(request.GET.get('page_size', 20))))
        skip = (page - 1) * page_size

        total = coll.count_documents(q)
        cursor = coll.find(q).sort(sort_by, sort_dir).skip(skip).limit(page_size)
        items = []
        for d in cursor:
            d['_id'] = str(d['_id'])
            if 'timestamp' in d and isinstance(d['timestamp'], datetime):
                d['timestamp'] = d['timestamp'].isoformat()
            items.append(d)

        if request.GET.get('format') == 'csv':
            # Export business-friendly CSV
            import csv as _csv
            from io import StringIO
            s = StringIO()
            w = _csv.writer(s)
            headers = [
                'Transaction ID', 'Timestamp', 'Customer ID', 'Channel', 'Amount',
                'Predicted Label', 'Risk Level', 'Risk Score (%)', 'Confidence (%)',
                'Rules Triggered', 'Reason', 'Model Version', 'Processing Time (ms)'
            ]
            w.writerow(headers)
            for i in items:
                ts = i.get('timestamp') or i.get('created_at')
                if isinstance(ts, datetime):
                    ts = ts.isoformat()
                rules = i.get('rules_triggered') or []
                if isinstance(rules, list):
                    rules = ', '.join([str(r) for r in rules])
                risk_score_pct = ''
                if i.get('risk_score') is not None:
                    try:
                        risk_score_pct = f"{float(i.get('risk_score')) * 100:.1f}"
                    except Exception:
                        risk_score_pct = ''
                confidence_pct = ''
                if i.get('confidence_level') is not None:
                    try:
                        confidence_pct = f"{float(i.get('confidence_level')) * 100:.1f}"
                    except Exception:
                        confidence_pct = ''
                label = 'Fraud' if i.get('prediction') == 1 else 'Legit'
                row = [
                    i.get('transaction_id') or i.get('_id'),
                    ts,
                    i.get('customer_id'),
                    i.get('channel'),
                    i.get('transaction_amount'),
                    label,
                    i.get('risk_level'),
                    risk_score_pct,
                    confidence_pct,
                    rules,
                    i.get('reason'),
                    i.get('model_version'),
                    i.get('processing_time_ms')
                ]
                w.writerow(row)
            resp = HttpResponse(s.getvalue(), content_type='text/csv')
            resp['Content-Disposition'] = 'attachment; filename="predictions_export.csv"'
            return resp

        return JsonResponse({'status': 'success', 'items': items, 'total': total, 'page': page, 'page_size': page_size})
    except Exception as e:
        logger.error(f"Transactions API error: {e}")
        return JsonResponse({'error': 'Failed to fetch transactions'}, status=500)


@login_required
@require_http_methods(["POST"]) 
def transactions_delete_api(request, doc_id: str):
    """POST /api/transactions/<id>/delete - Delete a single prediction owned by the user"""
    try:
        coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        try:
            _id = ObjectId(doc_id)
        except Exception:
            return JsonResponse({'error': 'Invalid id'}, status=400)

        doc = coll.find_one({'_id': _id})
        if not doc:
            return JsonResponse({'error': 'Not found'}, status=404)
        if str(doc.get('user_id')) != str(request.user.id):
            return JsonResponse({'error': 'Forbidden'}, status=403)

        coll.delete_one({'_id': _id})
        return JsonResponse({'status': 'success'})
    except Exception as e:
        logger.error(f"Transactions delete error: {e}")
        return JsonResponse({'error': 'Delete failed'}, status=500)

@login_required
@require_http_methods(["GET"])
def performance_api(request):
    """GET /api/performance - Model performance, feature importance, trends"""
    try:
        # Ensure model is loaded so fields are not undefined
        try:
            initialize_predictor()
        except Exception:
            pass
        model_info = get_predictor_info() or {}
        if model_info.get('error'):
            # Fallback sensible defaults to avoid undefined/NaN in UI
            model_info = {
                'model_type': 'Unknown',
                'feature_count': int(model_info.get('feature_count') or 0),
                'fraud_rate': float(model_info.get('fraud_rate') or 0.0),
                'encoders_loaded': int(model_info.get('encoders_loaded') or 0),
                'model_loaded': False,
                'last_updated': datetime.now().isoformat(),
            }
        # ALWAYS enrich model_info by inspecting model files directly
        try:
            candidates = [
                os.path.join('ml','models','fraud_models','gradient_boosting_model.pkl'),
                os.path.join('ml','models','fraud_models','fraud_model.pkl'),
                os.path.join('ml','models','model.pkl'),
            ]
            model_path = next((p for p in candidates if os.path.exists(p)), None)
            if model_path:
                _mdl = joblib.load(model_path)
                _names = getattr(_mdl, 'feature_names_in_', None)
                model_info = {
                    'model_type': type(_mdl).__name__,
                    'feature_count': int(len(_names)) if _names is not None else 0,
                    'fraud_rate': model_info.get('fraud_rate', 0.0),
                    'encoders_loaded': model_info.get('encoders_loaded', 0),
                    'model_loaded': True,
                    'last_updated': datetime.now().isoformat(),
                }
                # Also populate feature importance from model if not set yet
                try:
                    _imp = getattr(_mdl, 'feature_importances_', None)
                    if _imp is not None:
                        _names = _names or [f'f{i}' for i in range(len(_imp))]
                        tmp_pairs = sorted(zip(_names, _imp), key=lambda x: x[1], reverse=True)[:20]
                        feature_importance = [{'feature': str(n), 'importance': float(v)} for n, v in tmp_pairs]
                except Exception:
                    pass
        except Exception:
            pass
        coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        # Observed stats (strict per-user; no global fallback)
        q = {'user_id': str(request.user.id)}
        total = coll.count_documents(q)
        fraud_pred = coll.count_documents({**q, 'prediction': 1})
        avg_conf_cursor = coll.aggregate([
            {'$match': q},
            {'$group': {'_id': None, 'avg_conf': {'$avg': '$confidence_level'}}}
        ])
        avg_conf = 0.0
        for d in avg_conf_cursor:
            avg_conf = float(d.get('avg_conf') or 0.0)

        # User stats with source breakdown
        single_count = coll.count_documents({**q, 'source': 'single'})
        batch_count = coll.count_documents({**q, 'source': 'batch'})
        # Backward compatibility: approximate if zero and legacy docs exist
        if total > 0 and (single_count + batch_count == 0):
            # Approximation: treat docs with batch_id as batch
            batch_count = coll.count_documents({**q, 'batch_id': {'$exists': True}})
            single_count = max(0, total - batch_count)
        
        user_stats = {
            'total_predictions': total,
            'single_predictions': single_count,
            'batch_predictions': batch_count,
        }
        observed = {
            'total_predictions': total,
            'predicted_fraud_rate': (fraud_pred / total * 100.0) if total > 0 else 0.0,
            'avg_confidence': avg_conf,
        }

        # Feature importance placeholder (can be overridden by evaluation.py output)
        feature_importance = []
        try:
            mdl = predictor.model if getattr(predictor, 'is_loaded', False) else None
            names = getattr(mdl, 'feature_names_in_', None)
            importances = getattr(mdl, 'feature_importances_', None)
            if importances is not None:
                if names is None:
                    names = [f'f{i}' for i in range(len(importances))]
                pairs = sorted(zip(names, importances), key=lambda x: x[1], reverse=True)
                feature_importance = [{'feature': n, 'importance': float(v)} for n, v in pairs[:20]]
        except Exception:
            feature_importance = []

        # Stored metrics if any
        perf_coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('model_performance', 'model_performance'))
        latest_perf = perf_coll.find_one(sort=[('evaluation_date', -1)])
        metrics = None
        if latest_perf:
            latest_perf['_id'] = str(latest_perf['_id'])
            metrics = latest_perf

        # Helper: compute metrics using ml/evaluation.py if present
        def _compute_from_evaluation():
            from datetime import datetime
            try:
                from ml.evaluation import evaluate_model as _evaluate_model
                ev = _evaluate_model()
                cm = ev.get('confusion_matrix')
                # Map evaluation.py feature importance (DataFrame) if available
                nonlocal feature_importance
                try:
                    fi_df = ev.get('feature_importance')
                    if fi_df is not None:
                        # Ensure top 20 and correct format
                        records = fi_df.sort_values('importance', ascending=False).head(20).to_dict('records')
                        feature_importance = [
                            {'feature': str(r.get('feature')), 'importance': float(r.get('importance', 0.0) or 0.0)}
                            for r in records
                        ]
                except Exception:
                    pass
                # Serialize confusion matrix properly
                cm_serialized = None
                if cm is not None:
                    try:
                        if hasattr(cm, 'tolist'):
                            cm_serialized = cm.tolist()
                        elif isinstance(cm, list):
                            cm_serialized = cm
                    except Exception:
                        pass
                
                doc = {
                    'evaluation_date': datetime.now(),
                    'metrics': {
                        'accuracy': float(ev.get('accuracy') or 0.0),
                        'precision': float(ev.get('precision') or 0.0),
                        'recall': float(ev.get('recall') or 0.0),
                        'f1': float(ev.get('f1') or 0.0),
                        'auc': float(ev.get('auc') or 0.0) if ev.get('auc') is not None else 0.0,
                    },
                    'confusion_matrix': cm_serialized,
                    'roc_curve': ev.get('roc_curve'),
                }
                # Don't store in MongoDB to avoid ObjectId serialization issues
                # Just return the doc for immediate use
                return doc
            except Exception as _e:
                logger.warning(f"Eval-based metric load failed: {_e}")
                return None


        # If critical metrics missing, attempt: evaluation.py, then fallback local compute
        def _compute_and_store_metrics():
            from datetime import datetime
            try:
                data_path = os.path.join(os.getcwd(), 'ml', 'data', 'transactions_processed.csv')
                model_path = getattr(predictor, 'model_path', None)
                if not model_path or not os.path.exists(model_path) or not os.path.exists(data_path):
                    return None
                df = pd.read_csv(data_path)
                y = None
                for tgt in ['fraud_label', 'label', 'is_fraud']:
                    if tgt in df.columns:
                        y = df[tgt].astype(int)
                        break
                if y is None:
                    return None
                X = df.select_dtypes(include=['number']).copy()
                if 'fraud_label' in X.columns:
                    X = X.drop(columns=['fraud_label'])
                mdl = joblib.load(model_path)
                y_pred = mdl.predict(X)
                # Prefer proba if available
                try:
                    y_proba = mdl.predict_proba(X)[:, 1]
                except Exception:
                    # Fallback to decision_function scaled to [0,1]
                    try:
                        s = mdl.decision_function(X)
                        s = (s - np.min(s)) / (np.max(s) - np.min(s) + 1e-9)
                        y_proba = s
                    except Exception:
                        y_proba = y_pred.astype(float)

                acc = float(accuracy_score(y, y_pred))
                prec = float(precision_score(y, y_pred, zero_division=0))
                rec = float(recall_score(y, y_pred, zero_division=0))
                f1 = float(f1_score(y, y_pred, zero_division=0))
                auc = float(roc_auc_score(y, y_proba)) if y_proba is not None else None
                cm = confusion_matrix(y, y_pred)
                tn, fp, fn, tp = [int(v) for v in cm.ravel()]
                spec = float(tn / (tn + fp)) if (tn + fp) > 0 else 0.0
                fpr, tpr, thr = _roc_curve(y, y_proba)
                doc = {
                    'evaluation_date': datetime.now(),
                    'metrics': {
                        'accuracy': acc,
                        'precision': prec,
                        'recall': rec,
                        'f1': f1,
                        'specificity': spec,
                        'auc': auc,
                    },
                    'confusion_matrix': [[tn, fp], [fn, tp]],
                    'roc_curve': {'fpr': fpr.tolist(), 'tpr': tpr.tolist(), 'thresholds': thr.tolist()},
                }
                try:
                    perf_coll.insert_one(doc)
                except Exception:
                    pass
                return doc
            except Exception as _e:
                logger.warning(f"Metric compute failed: {_e}")
                return None

        force = request.GET.get('force') == '1'
        need_compute = True
        if metrics and metrics.get('metrics') and not force:
            m = metrics['metrics']
            if all(k in m for k in ['accuracy', 'precision', 'recall', 'f1']):
                need_compute = False
        
        # Always try to compute from evaluation.py first (your actual model)
        if need_compute or force:
            comp_eval = _compute_from_evaluation()
            if comp_eval:
                metrics = comp_eval
            else:
                comp = _compute_and_store_metrics()
                if comp:
                    metrics = comp

        # CSV export support
        if request.GET.get('format') == 'csv':
            import csv as _csv
            from io import StringIO
            s = StringIO()
            w = _csv.writer(s)
            w.writerow(['section', 'key', 'value'])
            w.writerow(['model_info', 'model_type', model_info.get('model_type')])
            w.writerow(['model_info', 'feature_count', model_info.get('feature_count')])
            w.writerow(['model_info', 'fraud_rate', model_info.get('fraud_rate')])
            w.writerow(['user_stats', 'total_predictions', user_stats['total_predictions']])
            w.writerow(['user_stats', 'single_predictions', user_stats['single_predictions']])
            w.writerow(['user_stats', 'batch_predictions', user_stats['batch_predictions']])
            w.writerow(['observed', 'predicted_fraud_rate', observed['predicted_fraud_rate']])
            w.writerow(['observed', 'avg_confidence', observed['avg_confidence']])
            if metrics and metrics.get('metrics'):
                for k, v in metrics['metrics'].items():
                    w.writerow(['training_metrics', k, v])
            if feature_importance:
                for fi in feature_importance:
                    w.writerow(['feature_importance', fi['feature'], fi['importance']])
            resp = HttpResponse(s.getvalue(), content_type='text/csv')
            resp['Content-Disposition'] = 'attachment; filename="performance_report.csv"'
            return resp

        # Include confusion matrix and ROC in response if available
        cm_resp = metrics.get('confusion_matrix') if metrics else None
        roc_resp = metrics.get('roc_curve') if metrics else None

        return JsonResponse({
            'status': 'success',
            'model_info': model_info,
            'user_stats': user_stats,
            'observed': observed,
            'feature_importance': feature_importance,
            'metrics': metrics,
            'confusion_matrix': cm_resp,
            'roc_curve': roc_resp,
        })
    except Exception as e:
        logger.error(f"Performance API error: {e}")
        # Return minimal success payload so UI can render gracefully
        return JsonResponse({
            'status': 'success',
            'model_info': {
                'model_type': 'Unknown',
                'feature_count': 0,
                'fraud_rate': 0.0,
                'encoders_loaded': 0,
                'model_loaded': False,
                'last_updated': datetime.now().isoformat(),
            },
            'user_stats': {
                'total_predictions': 0,
                'single_predictions': 0,
                'batch_predictions': 0,
            },
            'observed': {
                'total_predictions': 0,
                'predicted_fraud_rate': 0.0,
                'avg_confidence': 0.0,
            },
            'feature_importance': [],
            'metrics': { 'metrics': {} },
            'confusion_matrix': None,
            'roc_curve': None,
        })


@login_required
@require_http_methods(["GET"])
def prediction_report_api(request, transaction_id: str):
    """GET /api/prediction/<transaction_id>/report - Download prediction report as PDF (fallback HTML)."""
    try:
        coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        doc = coll.find_one({'user_id': str(request.user.id), 'transaction_id': transaction_id})
        if not doc:
            return HttpResponse('Not found', status=404)
        # Build report data
        pred = {
            'transaction_id': doc.get('transaction_id'),
            'prediction': doc.get('prediction'),
            'risk_level': doc.get('risk_level'),
            'risk_score': doc.get('risk_score'),
            'confidence': doc.get('confidence_level'),
            'timestamp': doc.get('timestamp') if isinstance(doc.get('timestamp'), str) else (doc.get('timestamp').isoformat() if doc.get('timestamp') else ''),
            'channel': doc.get('channel'),
            'amount': doc.get('transaction_amount'),
            'model_version': doc.get('model_version'),
            'rules_triggered': doc.get('rules_triggered', []),
        }
        explanation = (doc.get('explanation') or {})

        # Try ReportLab
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
            from reportlab.lib.units import cm
            from reportlab.lib import colors
            import io as _io

            buf = _io.BytesIO()
            c = canvas.Canvas(buf, pagesize=A4)
            width, height = A4
            y = height - 2*cm

            c.setFont("Helvetica-Bold", 16)
            c.drawString(2*cm, y, "Prediction Report")
            y -= 1.2*cm
            c.setFont("Helvetica", 11)
            lines = [
                f"Transaction ID: {pred['transaction_id']}",
                f"Timestamp: {pred['timestamp']}",
                f"Channel: {pred['channel']}",
                f"Amount: {pred['amount']}",
                f"Prediction: {'FRAUD' if pred['prediction']==1 else 'LEGIT'}",
                f"Risk Level: {pred['risk_level']}  (Score: {pred['risk_score']:.3f})",
                f"Confidence: {((pred['confidence'] or 0)*100):.1f}%",
                f"Model Version: {pred['model_version']}",
                f"Rules Triggered: {', '.join(pred['rules_triggered']) if pred['rules_triggered'] else 'None'}",
            ]
            for ln in lines:
                c.drawString(2*cm, y, ln)
                y -= 0.7*cm

            # Explanation bars
            c.setFont("Helvetica-Bold", 13)
            c.drawString(2*cm, y, "Top Contributors")
            y -= 0.8*cm
            top = (explanation.get('top_contributors') or [])[:5]
            if not top:
                c.setFont("Helvetica", 11)
                c.drawString(2*cm, y, "No explanation available")
            else:
                max_abs = max(abs(t.get('contribution', 0.0)) for t in top) or 1.0
                bar_w_max = width - 4*cm
                for t in top:
                    feat = str(t.get('feature'))
                    val = float(t.get('contribution', 0.0))
                    dirc = t.get('direction')
                    bar_w = bar_w_max * (abs(val) / max_abs)
                    color = colors.red if dirc == 'fraud' else colors.green
                    c.setFillColor(color)
                    c.rect(2*cm, y-0.3*cm, bar_w, 0.5*cm, fill=1, stroke=0)
                    c.setFillColor(colors.black)
                    c.setFont("Helvetica", 10)
                    c.drawString(2*cm, y+0.25*cm, feat)
                    c.drawRightString(2*cm + bar_w + 6, y+0.25*cm, f"{val:+.3f}")
                    y -= 0.8*cm

            c.showPage()
            c.save()
            pdf = buf.getvalue()
            buf.close()
            resp = HttpResponse(pdf, content_type='application/pdf')
            resp['Content-Disposition'] = f'attachment; filename="prediction_{transaction_id}.pdf"'
            return resp
        except Exception:
            # Fallback HTML report
            html = [
                "<html><head><meta charset='utf-8'><title>Prediction Report</title></head><body>",
                f"<h2>Prediction Report</h2>",
                f"<p><strong>Transaction ID:</strong> {pred['transaction_id']}</p>",
                f"<p><strong>Timestamp:</strong> {pred['timestamp']}</p>",
                f"<p><strong>Channel:</strong> {pred['channel']} &nbsp; <strong>Amount:</strong> {pred['amount']}</p>",
                f"<p><strong>Prediction:</strong> {'FRAUD' if pred['prediction']==1 else 'LEGIT'} &nbsp; <strong>Risk Level:</strong> {pred['risk_level']} ({pred['risk_score']:.3f}) &nbsp; <strong>Confidence:</strong> {((pred['confidence'] or 0)*100):.1f}%</p>",
                f"<p><strong>Model Version:</strong> {pred['model_version']}</p>",
                f"<p><strong>Rules Triggered:</strong> {', '.join(pred['rules_triggered']) if pred['rules_triggered'] else 'None'}</p>",
                "<h3>Top Contributors</h3>",
            ]
            top = (explanation.get('top_contributors') or [])[:5]
            if top:
                html.append("<ol>")
                for t in top:
                    html.append(f"<li>{t.get('feature')}: {t.get('contribution'):+.3f} ({t.get('direction')})</li>")
                html.append("</ol>")
            else:
                html.append("<p>No explanation available</p>")
            html.append("</body></html>")
            payload = "\n".join(html)
            resp = HttpResponse(payload, content_type='text/html')
            resp['Content-Disposition'] = f'attachment; filename="prediction_{transaction_id}.html"'
            return resp
    except Exception as e:
        logger.error(f"Prediction report error: {e}")
        return HttpResponse('Failed to generate report', status=500)


@login_required
@require_http_methods(["GET"])
def drift_api(request):
    """GET /api/drift - Compute PSI/JS divergence between recent window and baseline.
    Query params: window_days (default 7), baseline_days (default 30), feature (risk_score|amount)
    """
    try:
        def psi(p, q, eps=1e-6):
            import math
            s = 0.0
            for pi, qi in zip(p, q):
                pi = max(pi, eps); qi = max(qi, eps)
                s += (pi-qi) * math.log(pi/qi)
            return s

        from collections import Counter
        import numpy as _np

        coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        now = datetime.now()
        window_days = int(request.GET.get('window_days', 7))
        baseline_days = int(request.GET.get('baseline_days', 30))
        feature = (request.GET.get('feature') or 'risk_score').lower()

        # Recent window
        recent_start = now - timedelta(days=window_days)
        baseline_start = now - timedelta(days=baseline_days + window_days)
        baseline_end = now - timedelta(days=window_days)

        q_user = {'user_id': str(request.user.id)}
        recent = list(coll.find({**q_user, 'timestamp': {'$gte': recent_start}}).limit(5000))
        baseline = list(coll.find({**q_user, 'timestamp': {'$gte': baseline_start, '$lt': baseline_end}}).limit(5000))

        def series_from_docs(docs, key):
            vals = []
            for d in docs:
                v = d.get(key)
                if v is None and key == 'risk_score':
                    v = d.get('fraud_probability')
                try:
                    vals.append(float(v))
                except Exception:
                    pass
            return vals

        if feature == 'amount':
            r = series_from_docs(recent, 'transaction_amount')
            b = series_from_docs(baseline, 'transaction_amount')
            # Log-scale stabilize
            r = _np.log1p(_np.array(r)) if r else _np.array([])
            b = _np.log1p(_np.array(b)) if b else _np.array([])
        else:
            r = _np.array(series_from_docs(recent, 'risk_score'))
            b = _np.array(series_from_docs(baseline, 'risk_score'))

        # Binning
        bins = _np.linspace(r.min() if r.size else 0, r.max() if r.size else 1, 6) if feature=='amount' else _np.linspace(0,1,6)
        def hist_norm(x):
            if x.size == 0:
                return _np.zeros(len(bins)-1)
            h, _ = _np.histogram(x, bins=bins)
            h = h.astype(float)
            s = h.sum()
            return h/s if s>0 else _np.zeros_like(h)
        p = hist_norm(r)
        q = hist_norm(b)
        psi_score = float(psi(p, q))

        # Trendline (daily avg risk_score)
        def daily_avg(docs):
            from collections import defaultdict
            acc = defaultdict(list)
            for d in docs:
                ts = d.get('timestamp') or d.get('created_at') or now
                if not isinstance(ts, datetime):
                    try:
                        ts = datetime.fromisoformat(str(ts))
                    except Exception:
                        ts = now
                key = ts.strftime('%Y-%m-%d')
                v = d.get('risk_score') or d.get('fraud_probability') or 0.0
                try:
                    acc[key].append(float(v))
                except Exception:
                    pass
            out = []
            days = sorted(acc.keys())
            for k in days[-14:]:
                arr = acc[k]
                out.append({'date': k, 'avg': float(sum(arr)/max(1,len(arr)))})
            return out

        trend = daily_avg(recent)

        # Optional drift alert
        severity = None
        if psi_score >= 0.25:
            severity = 'CRITICAL'
        elif psi_score >= 0.1:
            severity = 'HIGH'
        if severity:
            try:
                a = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('system_alerts', 'system_alerts'))
                a.insert_one({
                    'alert_type': 'DRIFT',
                    'severity': severity,
                    'metric': 'PSI',
                    'value': psi_score,
                    'feature': feature,
                    'alert_timestamp': now,
                    'resolved_status': False,
                    'user_id': str(request.user.id),
                })
                try:
                    send_to_n8n('drift_alert', {'psi': psi_score, 'feature': feature}, request.user)
                except Exception:
                    pass
            except Exception:
                pass

        if request.GET.get('format') == 'csv':
            import csv as _csv
            from io import StringIO
            s = StringIO()
            w = _csv.writer(s)
            w.writerow(['section','key','value'])
            w.writerow(['drift','feature', feature])
            w.writerow(['drift','psi', psi_score])
            for row in trend:
                w.writerow(['trend', row['date'], row['avg']])
            resp = HttpResponse(s.getvalue(), content_type='text/csv')
            resp['Content-Disposition'] = 'attachment; filename="drift_report.csv"'
            return resp

        try:
            send_to_n8n('drift_snapshot', {'feature': feature, 'psi': psi_score, 'trend': trend}, request.user)
        except Exception:
            pass
        return JsonResponse({'status': 'success', 'feature': feature, 'psi': psi_score, 'trend': trend, 'bins': list(bins.astype(float))})
    except Exception as e:
        logger.error(f"Drift API error: {e}")
        return JsonResponse({'error': 'Failed to compute drift'}, status=500)


@login_required
@require_http_methods(["GET", "POST"])  # POST supports simple bulk actions via query/body
def alerts_api(request):
    """GET /api/alerts - list alerts; optional bulk actions: acknowledge/resolve via action param and ids."""
    try:
        coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('system_alerts', 'system_alerts'))
        if request.method == 'POST':
            try:
                body = json.loads(request.body or '{}')
            except json.JSONDecodeError:
                body = {}
            action = (body.get('action') or request.GET.get('action') or '').lower()
            ids = body.get('ids') or []
            # RBAC: only analyst/admin can modify alerts
            role = getattr(request.user, 'role', 'viewer')
            if action in ('acknowledge', 'ack', 'resolve', 'note') and role not in ('analyst', 'admin'):
                return JsonResponse({'error': 'Insufficient permissions'}, status=403)
            if action in ('acknowledge', 'ack') and ids:
                coll.update_many({'_id': {'$in': [ObjectId(i) for i in ids]}}, {'$set': {'notification_sent': True}})
                try:
                    send_to_n8n('alert_action', {'action': 'acknowledge', 'ids': ids}, request.user)
                except Exception:
                    pass
            elif action in ('resolve',) and ids:
                coll.update_many({'_id': {'$in': [ObjectId(i) for i in ids]}}, {'$set': {'resolved_status': True}})
                try:
                    send_to_n8n('alert_action', {'action': 'resolve', 'ids': ids}, request.user)
                except Exception:
                    pass
            elif action in ('note',) and ids:
                note_text = (body.get('note') or '').strip()
                if note_text:
                    entry = {'text': note_text, 'at': datetime.now(), 'by': str(request.user.id)}
                    coll.update_many({'_id': {'$in': [ObjectId(i) for i in ids]}}, {'$push': {'case_notes': entry}})
                    try:
                        send_to_n8n('alert_action', {'action': 'note', 'ids': ids, 'note': note_text}, request.user)
                    except Exception:
                        pass
            return JsonResponse({'status': 'success'})

        # GET list
        q = {'user_id': str(request.user.id)}
        if request.GET.get('active') == '1':
            q['resolved_status'] = False
        severity = request.GET.get('severity')
        if severity:
            q['severity'] = severity.upper()

        # CSV export
        if request.GET.get('format') == 'csv':
            import csv as _csv
            from io import StringIO
            s = StringIO()
            w = _csv.writer(s)
            w.writerow(['Alert ID','Type','Severity','Timestamp','Resolved','Transaction ID','Rules','PSI','Feature'])
            for d in coll.find(q).sort('alert_timestamp', -1).limit(200):
                rid = str(d.get('_id'))
                ts = d.get('alert_timestamp')
                if isinstance(ts, datetime):
                    ts = ts.isoformat()
                w.writerow([
                    rid,
                    d.get('alert_type'),
                    d.get('severity'),
                    ts,
                    d.get('resolved_status'),
                    d.get('transaction_id') or '',
                    ', '.join(d.get('triggered_rules', []) or []),
                    d.get('value') if d.get('metric') == 'PSI' else '',
                    d.get('feature') if d.get('metric') == 'PSI' else '',
                ])
            resp = HttpResponse(s.getvalue(), content_type='text/csv')
            resp['Content-Disposition'] = 'attachment; filename="alerts_export.csv"'
            return resp

        items = []
        for d in coll.find(q).sort('alert_timestamp', -1).limit(200):
            d['_id'] = str(d['_id'])
            if 'alert_timestamp' in d and isinstance(d['alert_timestamp'], datetime):
                d['alert_timestamp'] = d['alert_timestamp'].isoformat()
            items.append(d)
        return JsonResponse({'status': 'success', 'alerts': items})
    except Exception as e:
        logger.error(f"Alerts API error: {e}")
        return JsonResponse({'error': 'Failed to fetch alerts'}, status=500)



@csrf_exempt
@login_required  
@require_http_methods(["POST"])
def predict_batch_transactions_api(request):
    """API endpoint for batch transaction predictions"""
    try:
        # Initialize predictor if needed
        if not initialize_predictor():
            return JsonResponse({
                'error': 'Model not available',
                'message': 'Please ensure model.pkl is in ml/models/ directory'
            }, status=500)
        
        # Handle file upload
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'No file uploaded'}, status=400)
        
        file = request.FILES['file']
        
        # Validate file type
        if not file.name.endswith(('.csv', '.xlsx', '.json')):
            return JsonResponse({'error': 'Invalid file type. Please upload CSV, XLSX, or JSON'}, status=400)
        
        # Parse file data
        try:
            transactions = []
            
            if file.name.endswith('.csv'):
                content = file.read().decode('utf-8')
                reader = csv.DictReader(io.StringIO(content))
                transactions = list(reader)
                
            elif file.name.endswith('.xlsx'):
                df = pd.read_excel(file)
                transactions = df.to_dict('records')
                
            elif file.name.endswith('.json'):
                content = file.read().decode('utf-8')
                data = json.loads(content)
                if isinstance(data, list):
                    transactions = data
                else:
                    transactions = [data]
            
            # Limit batch size for performance
            if len(transactions) > 1000:
                return JsonResponse({
                    'error': 'Batch size too large',
                    'message': 'Maximum 1000 transactions per batch'
                }, status=400)
            
        except Exception as e:
            return JsonResponse({'error': f'File parsing error: {str(e)}'}, status=400)
        
        # Make batch predictions
        results = predict_transactions_batch(transactions)
        
        # Calculate summary statistics
        total_predictions = len(results)
        fraud_count = sum(1 for r in results if r.get('prediction') == 1)
        error_count = sum(1 for r in results if 'error' in r)
        
        summary = {
            'total_transactions': total_predictions,
            'fraud_detected': fraud_count,
            'legitimate_transactions': total_predictions - fraud_count - error_count,
            'errors': error_count,
            'fraud_rate': (fraud_count / (total_predictions - error_count)) * 100 if (total_predictions - error_count) > 0 else 0
        }
        
        # Store batch prediction in MongoDB
        try:
            predictions_collection = MongoConnection.get_collection('predictions')
            batch_record = {
                'user_id': str(request.user.id),
                'user_email': request.user.email,
                'file_name': file.name,
                'batch_results': results,
                'summary': summary,
                'created_at': datetime.now(),
                'prediction_type': 'batch'
            }
            predictions_collection.insert_one(batch_record)
            
            # Also store individual predictions in fraud_predictions collection for dashboard
            fraud_predictions_coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
            for idx, result in enumerate(results):
                if 'error' not in result:
                    fraud_predictions_coll.insert_one({
                        'transaction_id': result.get('transaction_id', f'batch_{idx}'),
                        'timestamp': datetime.now(),
                        'prediction': result.get('prediction', 0),
                        'fraud_probability': result.get('fraud_probability', 0.0),
                        'risk_score': result.get('fraud_probability', 0.0),
                        'confidence_level': result.get('confidence', 0.0),
                        'risk_level': result.get('risk_level', 'UNKNOWN'),
                        'user_id': str(request.user.id),
                        'created_at': datetime.now(),
                        'source': 'batch',
                        'batch_file': file.name
                    })
            
            # Clear dashboard cache so new predictions show immediately
            from django.core.cache import cache
            cache_key = f'dashboard_stats_{request.user.id}'
            cache.delete(cache_key)
            logger.info(f"Cleared dashboard cache after batch prediction for user {request.user.id}")
        except Exception as e:
            logger.warning(f"Failed to store batch prediction: {str(e)}")
        
        return JsonResponse({
            'status': 'success',
            'summary': summary,
            'results': results[:100],  # Return first 100 results
            'total_results': total_predictions,
            'message': f'Processed {total_predictions} transactions'
        })
        
    except Exception as e:
        logger.error(f"Batch prediction API error: {str(e)}")
        return JsonResponse({'error': 'Batch prediction failed', 'details': str(e)}, status=500)

@login_required
@require_http_methods(["GET"])
def prediction_history_api(request):
    """API endpoint to get user's prediction history"""
    try:
        predictions_collection = MongoConnection.get_collection('predictions')
        
        # Get user's predictions (limit to last 50)
        predictions = list(
            predictions_collection.find(
                {'user_id': str(request.user.id)}
            ).sort('created_at', -1).limit(50)
        )
        
        # Convert MongoDB objects to JSON serializable
        for pred in predictions:
            pred['_id'] = str(pred['_id'])
            if 'created_at' in pred:
                pred['created_at'] = pred['created_at'].isoformat()
        
        return JsonResponse({
            'status': 'success',
            'predictions': predictions,
            'count': len(predictions)
        })
        
    except Exception as e:
        logger.error(f"Prediction history API error: {str(e)}")
        return JsonResponse({'error': 'Failed to fetch prediction history'}, status=500)

@login_required
@require_http_methods(["GET"])
def model_stats_api(request):
    """API endpoint to get model statistics and information"""
    try:
        # Get model info
        model_info = get_predictor_info()
        
        if 'error' in model_info:
            return JsonResponse(model_info, status=500)
        
        # Get user's prediction statistics
        predictions_collection = MongoConnection.get_collection('predictions')
        
        user_stats = {
            'total_predictions': predictions_collection.count_documents({'user_id': str(request.user.id)}),
            'single_predictions': predictions_collection.count_documents({
                'user_id': str(request.user.id),
                'prediction_type': 'single'
            }),
            'batch_predictions': predictions_collection.count_documents({
                'user_id': str(request.user.id),
                'prediction_type': 'batch'
            })
        }
        
        return JsonResponse({
            'status': 'success',
            'model_info': model_info,
            'user_stats': user_stats
        })
        
    except Exception as e:
        logger.error(f"Model stats API error: {str(e)}")
        return JsonResponse({'error': 'Failed to fetch model statistics'}, status=500)


@login_required
@require_http_methods(["GET"])
def profile_stats_api(request):
    """GET /api/profile-stats - Dedicated counts for Profile page.
    Returns transactions, reports, alerts, uploads.
    """
    try:
        user_id = str(request.user.id)
        pred_coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        alerts_coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('system_alerts', 'system_alerts'))
        uploads_coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('file_uploads', 'file_uploads'))

        transactions = pred_coll.count_documents({'user_id': user_id})
        alerts_active = alerts_coll.count_documents({'user_id': user_id, 'resolved_status': False})
        uploads = uploads_coll.count_documents({'user_id': user_id})
        # Reports are available per-transaction via on-demand generation
        reports_available = transactions

        return JsonResponse({
            'status': 'success',
            'transactions': int(transactions),
            'reports': int(reports_available),
            'alerts_active': int(alerts_active),
            'uploads': int(uploads),
        })
    except Exception as e:
        logger.error(f"Profile stats API error: {e}")
        return JsonResponse({'error': 'Failed to fetch profile stats'}, status=500)

@csrf_exempt
@login_required
@require_http_methods(["POST"])
def analyze_transaction_patterns_api(request):
    """API endpoint to analyze transaction patterns"""
    try:
        # Parse input data
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON data'}, status=400)
        
        transactions = data.get('transactions', [])
        if not transactions:
            return JsonResponse({'error': 'No transactions provided'}, status=400)
        
        # Analyze patterns
        analysis = {
            'total_transactions': len(transactions),
            'amount_analysis': {},
            'time_analysis': {},
            'risk_analysis': {}
        }
        
        # Amount analysis
        amounts = [float(t.get('transaction_amount', 0)) for t in transactions if t.get('transaction_amount')]
        if amounts:
            analysis['amount_analysis'] = {
                'avg_amount': sum(amounts) / len(amounts),
                'max_amount': max(amounts),
                'min_amount': min(amounts),
                'high_value_count': len([a for a in amounts if a > 1000])
            }
        
        # Time analysis (if timestamp available)
        timestamps = [t.get('timestamp') for t in transactions if t.get('timestamp')]
        if timestamps:
            try:
                import pandas as pd
                df = pd.DataFrame({'timestamp': pd.to_datetime(timestamps)})
                df['hour'] = df['timestamp'].dt.hour
                df['day_of_week'] = df['timestamp'].dt.dayofweek
                
                analysis['time_analysis'] = {
                    'night_transactions': len(df[(df['hour'] >= 22) | (df['hour'] <= 5)]),
                    'business_hours': len(df[(df['hour'] >= 9) & (df['hour'] <= 17)]),
                    'weekend_transactions': len(df[df['day_of_week'] >= 5])
                }
            except:
                analysis['time_analysis'] = {'error': 'Could not parse timestamps'}
        
        return JsonResponse({
            'status': 'success',
            'analysis': analysis
        })
        
    except Exception as e:
        logger.error(f"Pattern analysis API error: {str(e)}")
        return JsonResponse({'error': 'Pattern analysis failed', 'details': str(e)}, status=500)


# ========== Legacy Analytics APIs (kept for compatibility; will be superseded) ==========
@login_required
@require_http_methods(["GET"])
def prediction_insights_api(request):
    """Aggregate user predictions for charts: class distribution, risk levels, over time."""
    try:
        coll = MongoConnection.get_collection('predictions')
        cursor = coll.find({'user_id': str(request.user.id)}).sort('created_at', -1)

        fraud = legit = 0
        risk_counts = {}
        avg_prob_sum = 0.0
        avg_prob_n = 0

        # Over time (last 14 days)
        from collections import defaultdict
        daily_counts = defaultdict(int)

        for doc in cursor:
            created_at = doc.get('created_at') or datetime.now()
            day_key = created_at.strftime('%Y-%m-%d')

            if doc.get('prediction_type') == 'single':
                res = (doc.get('prediction_result') or {})
                pred = int(res.get('prediction', 0))
                prob = float(res.get('fraud_probability', 0.0) or 0.0)
                risk = (res.get('risk_level') or 'UNKNOWN').upper()

                if pred == 1:
                    fraud += 1
                else:
                    legit += 1
                risk_counts[risk] = risk_counts.get(risk, 0) + 1
                avg_prob_sum += prob
                avg_prob_n += 1
                daily_counts[day_key] += 1

            elif doc.get('prediction_type') == 'batch':
                results = doc.get('batch_results') or []
                daily_counts[day_key] += len(results)
                for r in results:
                    pred = int(r.get('prediction', 0)) if r.get('prediction') is not None else 0
                    prob = float(r.get('fraud_probability', 0.0) or 0.0)
                    risk = (r.get('risk_level') or 'UNKNOWN').upper()
                    if pred == 1:
                        fraud += 1
                    else:
                        legit += 1
                    risk_counts[risk] = risk_counts.get(risk, 0) + 1
                    if 'fraud_probability' in r:
                        avg_prob_sum += prob
                        avg_prob_n += 1

        # Build ordered last 14 days series
        from datetime import timedelta
        series = []
        for i in range(13, -1, -1):
            day = datetime.now() - timedelta(days=i)
            key = day.strftime('%Y-%m-%d')
            series.append({'date': key, 'count': int(daily_counts.get(key, 0))})

        insights = {
            'class_distribution': {
                'fraud': fraud,
                'legitimate': legit
            },
            'risk_levels': risk_counts,
            'over_time': series,
            'avg_fraud_probability': (avg_prob_sum / avg_prob_n) if avg_prob_n > 0 else 0.0
        }

        return JsonResponse({'status': 'success', 'insights': insights})
    except Exception as e:
        logger.error(f"Prediction insights API error: {str(e)}")
        return JsonResponse({'error': 'Failed to compute insights'}, status=500)


@login_required
@require_http_methods(["GET"])
def model_performance_api(request):
    """Return model information and observed user-side performance signals."""
    try:
        # User-side observed metrics (from fraud_predictions collection)
        coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        cursor = coll.find({'user_id': str(request.user.id)})
        total = 0
        fraud_pred = 0
        confidence_sum = 0.0
        conf_n = 0
        single_count = 0
        batch_count = 0
        for doc in cursor:
            total += 1
            if int(doc.get('prediction') or doc.get('model_prediction') or 0) == 1:
                fraud_pred += 1
            conf = doc.get('confidence_level') or doc.get('model_fraud_probability')
            if conf is not None:
                try:
                    confidence_sum += float(conf)
                    conf_n += 1
                except Exception:
                    pass
            src = doc.get('source', 'single')
            if src == 'batch':
                batch_count += 1
            else:
                single_count += 1
        avg_conf = (confidence_sum / conf_n) if conf_n > 0 else 0.0
        
        user_stats = {
            'total_predictions': total,
            'single_predictions': single_count,
            'batch_predictions': batch_count,
        }
        observed = {
            'total_predictions': total,
            'predicted_fraud_rate': (fraud_pred / total * 100.0) if total > 0 else 0.0,
            'avg_confidence': avg_conf,
        }

        model_info = get_predictor_info()

        return JsonResponse({'status': 'success', 'model_info': model_info, 'observed': observed})
    except Exception as e:
        logger.error(f"Model performance API error: {str(e)}")
        return JsonResponse({'error': 'Failed to compute model performance'}, status=500)


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def simulate_predictions_api(request):
    return JsonResponse({'error': 'Disabled in production'}, status=404)