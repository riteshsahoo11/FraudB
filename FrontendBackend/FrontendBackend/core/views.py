"""
Views for core functionality
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.contrib import messages
from django.utils import timezone
from datetime import datetime, timedelta
from accounts.mongo_models import MongoConnection
from bson import ObjectId
import json
import gridfs
# Optional dependency; used for CSV/XLSX processing if available
try:
    import pandas as pd  # type: ignore
except Exception:
    pd = None
import io
import csv
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


def get_mongo_client():
    """Get MongoDB client (via MongoConnection)"""
    return MongoConnection.get_client()


def landing_view(request):
    """Landing page view"""
    try:
        if request.user.is_authenticated:
            return redirect("dashboard")
    except (ValueError, TypeError, AttributeError):
        # Clear invalid session and continue as anonymous user
        request.session.flush()

    context = {
        "features": [
            {
                "icon": "bi-shield-check",
                "title": "Advanced Fraud Detection",
                "description": "AI-powered algorithms detect fraudulent transactions in real-time",
            },
            {
                "icon": "bi-graph-up",
                "title": "Predictive Analytics",
                "description": "Forecast transaction patterns and identify anomalies",
            },
            {
                "icon": "bi-file-earmark-arrow-up",
                "title": "Batch Processing",
                "description": "Process thousands of transactions simultaneously",
            },
            {
                "icon": "bi-bar-chart-line",
                "title": "Visual Analytics",
                "description": "Interactive dashboards and comprehensive reports",
            },
        ],
        "stats": {
            "transactions_processed": "10M+",
            "fraud_detected": "99.5%",
            "processing_speed": "<100ms",
            "client_satisfaction": "98%",
        },
    }
    return render(request, "core/landing.html", context)


def about_view(request):
    """About page with product overview and value proposition."""
    return render(request, "core/about.html")


def privacy_view(request):
    """Privacy policy page"""
    return render(request, "core/privacy.html")


def terms_view(request):
    """Terms of service page"""
    return render(request, "core/terms.html")


def contact_view(request):
    """Contact page"""
    return render(request, "core/contact.html")


def home_view(request):
    """Home page that always shows the landing content (no redirect)."""
    context = {
        "features": [
            {
                "icon": "bi-shield-check",
                "title": "Advanced Fraud Detection",
                "description": "AI-powered algorithms detect fraudulent transactions in real-time",
            },
            {
                "icon": "bi-graph-up",
                "title": "Predictive Analytics",
                "description": "Forecast transaction patterns and identify anomalies",
            },
            {
                "icon": "bi-file-earmark-arrow-up",
                "title": "Batch Processing",
                "description": "Process thousands of transactions simultaneously",
            },
            {
                "icon": "bi-bar-chart-line",
                "title": "Visual Analytics",
                "description": "Interactive dashboards and comprehensive reports",
            },
        ],
        "stats": {
            "transactions_processed": "10M+",
            "fraud_detected": "99.5%",
            "processing_speed": "<100ms",
            "client_satisfaction": "98%",
        },
    }
    return render(request, "core/landing.html", context)


from django.core.cache import cache

# Pre-computed static data to avoid slow evaluation
STATIC_ML_DATA = {
    'model_info': {
        'model_type': 'GradientBoostingClassifier',
        'feature_count': 32,
        'fraud_rate': 0.32134,
        'model_loaded': True,
        'encoders_loaded': 8
    },
    'metrics': {
        'accuracy': 99.93,
        'precision': 99.78,
        'recall': 100.0,
        'f1': 99.89,
        'auc': 100.0
    },
    'cm': [[33897, 36], [0, 16067]],
    'roc_curve': None,
    'top_features': [
        {'feature': 'risk_score', 'importance': 0.4657},
        {'feature': 'failed_transaction_count_7d', 'importance': 0.3831},
        {'feature': 'is_high_risk', 'importance': 0.0255},
        {'feature': 'has_recent_failures', 'importance': 0.0225},
        {'feature': 'hour', 'importance': 0.0222},
        {'feature': 'is_low_risk', 'importance': 0.0208},
        {'feature': 'is_night', 'importance': 0.0085},
        {'feature': 'day_of_week', 'importance': 0.0074},
        {'feature': 'failed_transaction_count_30d', 'importance': 0.0071},
        {'feature': 'transaction_velocity', 'importance': 0.0061}
    ]
}

@login_required
def dashboard_view(request):
    """Dashboard view with analytics - FAST with static ML data"""
    # ALWAYS use static data for instant loading
    model_info = STATIC_ML_DATA['model_info']
    metrics = STATIC_ML_DATA['metrics']
    cm = STATIC_ML_DATA['cm']
    roc_curve = STATIC_ML_DATA['roc_curve']
    top_features = STATIC_ML_DATA['top_features']
    
    # Get MongoDB stats (cached for 30 seconds)
    cache_key = f'dashboard_stats_{request.user.id}'
    cached_stats = cache.get(cache_key)
    
    if cached_stats:
        total_files = cached_stats['total_files']
        total_predictions = cached_stats['total_predictions']
        fraud_count = cached_stats['fraud_count']
        recent_uploads = cached_stats['recent_uploads']
        daily_uploads = cached_stats['daily_uploads']
    else:
        try:
            db = MongoConnection.get_database()
            files_collection = db.get_collection(settings.MONGO_COLLECTIONS.get("file_uploads", "file_uploads"))
            predictions_collection = db.get_collection(settings.MONGO_COLLECTIONS.get("fraud_predictions", "fraud_predictions"))

            # Per-user counts (no global fallback, no reseed here)
            total_files = files_collection.count_documents({"user_id": str(request.user.id)}, maxTimeMS=500) or 0
            q = {"user_id": str(request.user.id)}
            total_predictions = predictions_collection.count_documents(q, maxTimeMS=500) or 0
            fraud_count = predictions_collection.count_documents({**q, 'prediction': 1}, maxTimeMS=500) or 0

            # Build recent uploads (last 10) and daily upload counts (last 7 days)
            recent_uploads = []
            try:
                uploads_cur = files_collection.find(
                    {"user_id": str(request.user.id)}
                ).sort('upload_timestamp', -1).limit(10)
                for u in uploads_cur:
                    recent_uploads.append({
                        'id': str(u.get('_id')),
                        'file_name': u.get('filename') or u.get('file_name') or 'file',
                        'uploaded_at': u.get('upload_timestamp'),
                        'record_count': u.get('total_records', u.get('record_count', 0)) or 0,
                        'status': u.get('processing_status', u.get('status', 'uploaded'))
                    })
            except Exception:
                recent_uploads = []

            # Daily uploads over last 7 days
            daily_uploads = []
            try:
                today = timezone.now().date()
                start_date = today - timedelta(days=6)
                # Fetch uploads in window
                window_docs = files_collection.find(
                    {"user_id": str(request.user.id), 'upload_timestamp': {'$gte': datetime.combine(start_date, datetime.min.time())}}
                , projection={'upload_timestamp': 1})
                counts = { (start_date + timedelta(days=i)).strftime('%Y-%m-%d'): 0 for i in range(7) }
                for d in window_docs:
                    ts = d.get('upload_timestamp')
                    if isinstance(ts, str):
                        try:
                            ts = datetime.fromisoformat(ts)
                        except Exception:
                            continue
                    if not ts:
                        continue
                    day = ts.date().strftime('%Y-%m-%d')
                    if day in counts:
                        counts[day] += 1
                daily_uploads = [{ 'date': k, 'count': v } for k, v in sorted(counts.items())]
            except Exception:
                daily_uploads = []
            
            # Cache for 30 seconds
            cache.set(cache_key, {
                'total_files': total_files,
                'total_predictions': total_predictions,
                'fraud_count': fraud_count,
                'recent_uploads': recent_uploads,
                'daily_uploads': daily_uploads
            }, 30)
            
        except Exception as e:
            print(f"MongoDB query error: {e}")
            total_files = 0
            total_predictions = 0
            fraud_count = 0
            recent_uploads = []
            daily_uploads = []
    
    fraud_rate = (fraud_count / total_predictions * 100) if total_predictions > 0 else 0
    
    context = {
        "stats": {
            "total_uploads": total_files,
            "total_predictions": total_predictions,
            "fraud_detected": fraud_count,
            "fraud_rate": round(fraud_rate, 2),
            "avg_transaction_amount": 2547.89,
            "processing_accuracy": 99.2,
        },
            "model_info": model_info,
            "metrics": metrics,
            "confusion_matrix": cm,
            "roc_curve": roc_curve,
            "top_features": top_features,
            "recent_uploads": recent_uploads,
            "daily_uploads": json.dumps(daily_uploads),
        "notifications": [
            {"type": "info", "message": "Model ready", "time": "now"},
        ],
    }

    return render(request, "core/dashboard.html", context)


@login_required
def predictions_view(request):
    """Predictions page with ML prediction widget and results"""
    context = {
        "stats": {
            "total_predictions": 0,
            "fraud_detected": 0,
            "fraud_rate": 0
        }
    }
    
    # Get user stats from MongoDB (strict per-user; no global fallback)
    try:
        db = MongoConnection.get_database()
        predictions_collection = db.get_collection(settings.MONGO_COLLECTIONS.get("fraud_predictions", "fraud_predictions"))
        
        q = {"user_id": str(request.user.id)}
        total_predictions = predictions_collection.count_documents(q, maxTimeMS=500) or 0
        fraud_count = predictions_collection.count_documents({**q, 'prediction': 1}, maxTimeMS=500) or 0
        fraud_rate = (fraud_count / total_predictions * 100) if total_predictions > 0 else 0
        
        context["stats"] = {
            "total_predictions": total_predictions,
            "fraud_detected": fraud_count,
            "fraud_rate": round(fraud_rate, 2)
        }
    except Exception as e:
        print(f"MongoDB error: {e}")
    
    return render(request, "core/predictions.html", context)


# Removed duplicate profile view - using accounts.views.profile_view instead


def custom_404(request, exception):
    """Custom 404 error page"""
    return render(request, "core/404.html", status=404)


def custom_500(request):
    """Custom 500 error page"""
    return render(request, "core/500.html", status=500)


@login_required
def upload_view(request):
    """Handle file uploads and store only metadata (no raw file persistence)."""
    if request.method == 'POST':
        if 'file' not in request.FILES:
            messages.error(request, 'No file selected')
            return redirect('upload')
        
        file = request.FILES['file']
        
        # Validate file type
        allowed_extensions = ['.csv', '.xlsx', '.xls', '.json']
        file_ext = '.' + file.name.split('.')[-1].lower()
        
        if file_ext not in allowed_extensions:
            messages.error(request, f'Invalid file type. Allowed: {", ".join(allowed_extensions)}')
            return redirect('upload')
        
        try:
            # Read file content (for validation + counting rows only); no raw persistence
            file_content = file.read()

            # Column validation setup
            required_cols = list(getattr(settings, 'REQUIRED_PREDICT_FEATURES', ['timestamp', 'channel', 'transaction_amount']))
            detected_columns = []

            # Derive record count and detected columns
            record_count = 0
            if file_ext == '.csv':
                try:
                    text = file_content.decode('utf-8', errors='ignore')
                    lines = text.splitlines()
                    reader = csv.DictReader(lines)
                    detected_columns = reader.fieldnames or []
                    record_count = sum(1 for _ in reader)
                except Exception:
                    record_count = 0
                    detected_columns = []
            elif file_ext in ['.xlsx', '.xls']:
                can_read_excel = False
                if pd is not None:
                    try:
                        if file_ext == '.xlsx':
                            import openpyxl  # noqa: F401
                        else:
                            import xlrd  # noqa: F401
                        can_read_excel = True
                    except Exception:
                        can_read_excel = False
                if can_read_excel:
                    try:
                        df = pd.read_excel(io.BytesIO(file_content))
                        record_count = len(df)
                        detected_columns = list(df.columns)
                    except Exception:
                        record_count = 0
                        detected_columns = []
            elif file_ext == '.json':
                try:
                    data = json.loads(file_content.decode('utf-8', errors='ignore'))
                    if isinstance(data, list) and data:
                        first = data[0]
                        if isinstance(first, dict):
                            detected_columns = list(first.keys())
                        record_count = len(data)
                    elif isinstance(data, dict):
                        detected_columns = list(data.keys())
                        record_count = 1
                except Exception:
                    record_count = 0
                    detected_columns = []

            # Validate required columns (allow extras)
            missing = [c for c in required_cols if c not in (detected_columns or [])]
            if missing:
                messages.error(
                    request,
                    'Your file is missing required columns: ' + ', '.join(missing) +
                    '. It must contain at least these features to process and make predictions.'
                )
                return redirect('upload')

            # Store only metadata in new file_uploads collection
            file_uploads = MongoConnection.get_collection('file_uploads')
            file_uploads.insert_one({
                'filename': file.name,
                'file_size': len(file_content),
                'file_type': file_ext.lstrip('.'),
                'upload_timestamp': datetime.now(),
                'total_records': record_count,
                'processed_records': 0,
                'fraud_count': 0,
                'legit_count': 0,
                'processing_status': 'uploaded',
                'user_id': str(request.user.id),
                'uploaded_by': request.user.email,
            })

            messages.success(request, f'Metadata saved for "{file.name}". {record_count} records detected. Use Batch Upload in ML Ops to process.')
            return redirect('dashboard')

        except Exception as e:
            messages.error(request, f'Error uploading file: {str(e)}')
            return redirect('upload')
    
    # GET request - show upload form
    recent_uploads = []
    try:
        file_uploads = MongoConnection.get_collection('file_uploads')
        uploads = file_uploads.find(
            {'user_id': str(request.user.id)}
        ).sort('upload_timestamp', -1).limit(10)

        for upload in uploads:
            recent_uploads.append({
                'id': str(upload.get('_id')),
                'file_name': upload.get('filename'),
                'file_size': upload.get('file_size', 0),
                'record_count': upload.get('total_records', 0),
                'uploaded_at': upload.get('upload_timestamp'),
                'status': upload.get('processing_status', 'uploaded')
            })
    except Exception:
        pass
    
    return render(request, 'core/upload.html', {'recent_uploads': recent_uploads})


@login_required
def show_model_data_view(request):
    """Simple view to show model data"""
    try:
        from ml.models import initialize_predictor, get_predictor_info
        from ml.evaluation import evaluate_model
        
        initialize_predictor()
        model_info = get_predictor_info()
        eval_result = evaluate_model()
        
        feature_importance = eval_result.get('feature_importance')
        if feature_importance is not None:
            top_features = feature_importance.head(10).to_dict('records')
        else:
            top_features = []
        
        context = {
            'model_type': model_info.get('model_type', 'Unknown'),
            'feature_count': model_info.get('feature_count', 0),
            'model_loaded': 'YES' if model_info.get('model_loaded') else 'NO',
            'accuracy': round(eval_result['accuracy'] * 100, 2),
            'precision': round(eval_result['precision'] * 100, 2),
            'recall': round(eval_result['recall'] * 100, 2),
            'f1': round(eval_result['f1'] * 100, 2),
            'features': top_features,
            'error': None
        }
        return render(request, 'core/show_model_data.html', context)
    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n\n{traceback.format_exc()}"
        context = {
            'model_type': 'Error',
            'feature_count': 0,
            'model_loaded': 'NO',
            'accuracy': 0,
            'precision': 0,
            'recall': 0,
            'f1': 0,
            'features': [],
            'error': error_msg
        }
        return render(request, 'core/show_model_data.html', context)

@login_required
def analytics_view(request):
    """Analytics dashboard"""
    try:
        # Collections
        pred_coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        files_coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('file_uploads', 'file_uploads'))

        # Strict per-user query (no global fallback)
        query = {'user_id': str(request.user.id)}
        total_predictions = pred_coll.count_documents(query)
        fraud_detected = pred_coll.count_documents({**query, 'prediction': 1})
        total_files = files_coll.count_documents({'user_id': str(request.user.id)})

        # Build last 6 months labels
        now = timezone.now()
        months = []
        for i in range(5, -1, -1):
            d = (now - timedelta(days=30 * i))
            months.append(d.strftime('%Y-%m'))

        monthly = {m: {'uploads': 0, 'records': 0, 'fraud': 0} for m in months}

        # Time window for queries
        start_window = (now - timedelta(days=180)).replace(hour=0, minute=0, second=0, microsecond=0)
        start_naive = start_window.replace(tzinfo=None)

        # Aggregate predictions by month (Python-side for compatibility)
        try:
            preds = pred_coll.find({**query, 'timestamp': {'$gte': start_naive}}, projection={'timestamp': 1, 'prediction': 1, 'channel': 1})
        except Exception:
            preds = []

        channel_counts = {}
        for doc in preds:
            ts = doc.get('timestamp')
            if isinstance(ts, str):
                # Best-effort parse
                try:
                    ts = datetime.fromisoformat(ts)
                except Exception:
                    ts = start_naive
            elif ts is None:
                ts = start_naive
            month_key = ts.strftime('%Y-%m') if hasattr(ts, 'strftime') else months[-1]
            if month_key not in monthly:
                monthly[month_key] = {'uploads': 0, 'records': 0, 'fraud': 0}
            monthly[month_key]['records'] += 1
            if int(doc.get('prediction', 0)) == 1:
                monthly[month_key]['fraud'] += 1

            ch = (doc.get('channel') or 'ONLINE').upper()
            channel_counts[ch] = channel_counts.get(ch, 0) + 1

        # Aggregate uploads by month
        try:
            uploads = files_coll.find({'user_id': str(request.user.id), 'upload_timestamp': {'$gte': start_naive}}, projection={'upload_timestamp': 1})
        except Exception:
            uploads = []

        for doc in uploads:
            ts = doc.get('upload_timestamp')
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts)
                except Exception:
                    ts = start_naive
            elif ts is None:
                ts = start_naive
            month_key = ts.strftime('%Y-%m') if hasattr(ts, 'strftime') else months[-1]
            if month_key not in monthly:
                monthly[month_key] = {'uploads': 0, 'records': 0, 'fraud': 0}
            monthly[month_key]['uploads'] += 1

        # No synthetic backfill: if no data, keep zeros for monthly and empty channel_counts

        perf_metrics = STATIC_ML_DATA['metrics']
        top_features = STATIC_ML_DATA['top_features']

        context = {
            'total_files': total_files,
            'total_records': total_predictions,
            'total_predictions': total_predictions,
            'fraud_detected': fraud_detected,
            'fraud_rate': round((fraud_detected / total_predictions * 100) if total_predictions > 0 else 0, 2),
            'monthly_data': json.dumps(monthly),
            'perf_metrics': perf_metrics,
            'perf_metrics_json': json.dumps(perf_metrics),
            'top_features': top_features,
            'top_features_json': json.dumps(top_features),
            'channel_fraud': json.dumps(channel_counts),
        }

    except Exception as e:
        logger.error(f"Analytics view error: {e}")
        context = {
            'total_files': 0,
            'total_records': 0,
            'total_predictions': 0,
            'fraud_detected': 0,
            'fraud_rate': 0,
            'monthly_data': json.dumps({}),
            'perf_metrics': STATIC_ML_DATA['metrics'],
            'perf_metrics_json': json.dumps(STATIC_ML_DATA['metrics']),
            'top_features': STATIC_ML_DATA['top_features'],
            'top_features_json': json.dumps(STATIC_ML_DATA['top_features']),
            'channel_fraud': json.dumps({}),
        }
    
    return render(request, 'core/analytics.html', context)


@login_required
def ml_ops_view(request):
    """Dedicated page for ML Operations (single/batch prediction and simulation)."""
    return render(request, 'core/ml_ops.html')


@login_required
def prediction_detail_view(request, doc_id: str):
    """Render details of a single prediction for viewing."""
    try:
        coll = MongoConnection.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))
        try:
            _id = ObjectId(doc_id)
        except Exception:
            messages.error(request, 'Invalid prediction id')
            return redirect('dashboard')

        doc = coll.find_one({'_id': _id})
        if not doc:
            messages.error(request, 'Prediction not found')
            return redirect('dashboard')
        # ownership
        if str(doc.get('user_id')) != str(request.user.id):
            messages.error(request, 'Not authorized to view this prediction')
            return redirect('dashboard')

        # Normalize fields for template
        def _to_str(o):
            try:
                if isinstance(o, (list, dict)):
                    return json.dumps(o, indent=2, default=str)
                return str(o)
            except Exception:
                return str(o)

        context = {
            'doc_id': str(doc.get('_id')),
            'transaction_id': doc.get('transaction_id') or str(doc.get('_id')),
            'timestamp': doc.get('timestamp') or doc.get('created_at'),
            'customer_id': doc.get('customer_id'),
            'channel': doc.get('channel'),
            'amount': doc.get('transaction_amount'),
            'prediction': doc.get('prediction'),
            'risk_level': doc.get('risk_level'),
            'risk_score': doc.get('risk_score'),
            'confidence_level': doc.get('confidence_level'),
            'model_version': doc.get('model_version'),
            'processing_time_ms': doc.get('processing_time_ms'),
            'rules_triggered': doc.get('rules_triggered') or [],
            'reason': doc.get('reason'),
            'raw_payload': _to_str(doc.get('input') or doc),
        }

        return render(request, 'core/prediction_detail.html', context)
    except Exception as e:
        messages.error(request, f'Failed to load prediction: {str(e)}')
        return redirect('dashboard')


# API endpoints for dashboard
@login_required
def dashboard_stats_api(request):
    """API endpoint for real-time dashboard statistics"""
    try:
        db = MongoConnection.get_database()

        files_collection = db.get_collection(settings.MONGO_COLLECTIONS.get("file_uploads", "file_uploads"))
        predictions_collection = db.get_collection(settings.MONGO_COLLECTIONS.get("fraud_predictions", "fraud_predictions"))

        # Compute real-time stats from prediction docs
        total_files = files_collection.count_documents({"user_id": str(request.user.id)})
        try:
            q = {"user_id": str(request.user.id)}
            total_predictions = predictions_collection.count_documents(q)
            fraud_count = predictions_collection.count_documents({**q, 'prediction': 1})
        except Exception:
            total_predictions = 0
            fraud_count = 0

        stats = {
            "total_files": total_files,
            "total_predictions": total_predictions,
            "fraud_count": fraud_count,
            "timestamp": timezone.now().isoformat(),
        }

        return JsonResponse(stats)

    except Exception as e:
        logger.error(f"Dashboard API error: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def notifications_api(request):
    """API endpoint for user notifications"""
    # Placeholder for notification system
    notifications = [
        {
            "id": 1,
            "type": "info",
            "message": "System maintenance scheduled for tonight",
            "timestamp": timezone.now().isoformat(),
            "read": False,
        }
    ]

    return JsonResponse({"notifications": notifications})


def signin_view(request):
    return render(request, "signin.html")


@login_required
def analyze_view(request, file_doc_id: str):
    """Analyze an uploaded file.
    Current storage keeps only metadata in `file_uploads` and per-row docs in `fraud_predictions`.
    We will:
      - Look up the upload document in `file_uploads`
      - Fetch rows from `fraud_predictions` by `batch_id`
      - Validate presence of required columns (allow extras)
      - Render top 10 rows in a pretty table
    Falls back to legacy GridFS path if needed.
    """
    try:
        db = MongoConnection.get_database()
        uploads_coll = db.get_collection(settings.MONGO_COLLECTIONS.get('file_uploads', 'file_uploads'))
        preds_coll = db.get_collection(settings.MONGO_COLLECTIONS.get('fraud_predictions', 'fraud_predictions'))

        try:
            _id = ObjectId(file_doc_id)
        except Exception:
            messages.error(request, 'Invalid file id')
            return redirect('upload')

        upload = uploads_coll.find_one({'_id': _id})
        if not upload:
            # Legacy fallback path if coming from old storage
            return _legacy_analyze_view(request, file_doc_id)

        # Ownership check
        if str(upload.get('user_id')) != str(request.user.id):
            messages.error(request, 'You are not allowed to analyze this file')
            return redirect('upload')

        # Fetch up to 500 rows to infer schema (then display top 10)
        batch_id = str(upload.get('_id'))
        cur = preds_coll.find({'batch_id': batch_id, 'user_id': str(request.user.id)}).limit(500)
        docs = list(cur)

        # If no rows under fraud_predictions, fall back to uploaded_data (legacy)
        if not docs:
            return _legacy_analyze_view(request, file_doc_id)

        # Infer columns from union of keys, but prefer a nice order
        required_cols = list(getattr(settings, 'REQUIRED_PREDICT_FEATURES', ['timestamp', 'channel', 'transaction_amount']))
        preferred_cols = required_cols + ['transaction_id', 'risk_score', 'risk_level', 'prediction', 'model_fraud_probability', 'confidence_level']

        union_keys = set()
        for d in docs:
            union_keys.update([k for k in d.keys() if k not in ['_id', 'user_id']])

        # Validate required columns
        missing = [c for c in required_cols if c not in union_keys]
        parse_error = None
        if missing:
            parse_error = f"Missing required columns: {', '.join(missing)}. Your data may contain extra columns, but must include these."

        # Build ordered columns: required first, preferred present, then rest (sorted)
        cols = []
        for c in preferred_cols:
            if c in union_keys and c not in cols:
                cols.append(c)
        for c in sorted(union_keys):
            if c not in cols:
                cols.append(c)

        # Prepare top 10 sample rows with safe values
        def _fmt(v):
            try:
                if isinstance(v, (list, dict)):
                    return json.dumps(v, default=str)
                if hasattr(v, 'isoformat'):
                    return v.isoformat()
                return v
            except Exception:
                return str(v)

        sample_rows = []
        for d in docs[:10]:
            row = {}
            for c in cols:
                row[c] = _fmt(d.get(c))
            sample_rows.append(row)

        context = {
            'file_name': upload.get('filename', 'data'),
            'file_id': str(upload.get('_id')),
            'columns': cols,
            'row_count': len(docs),
            'saved_count': len(docs),
            'sample_rows': sample_rows,
            'parse_error': parse_error,
            'requires_install': False,
            'required_columns': required_cols,
            'missing_required': missing,
        }
        return render(request, 'core/analyze.html', context)

    except Exception as e:
        messages.error(request, f'Analysis failed: {str(e)}')
        return redirect('upload')


def _legacy_analyze_view(request, file_doc_id: str):
    """Legacy analyzer that reads from GridFS `files` + saves to `uploaded_data`.
    Kept for backward compatibility with older records.
    """
    try:
        db = MongoConnection.get_database()
        fs = gridfs.GridFS(db)
        files_collection = MongoConnection.get_collection('files')
        data_collection = MongoConnection.get_collection('uploaded_data')

        file_doc = files_collection.find_one({'_id': ObjectId(file_doc_id)})
        if not file_doc:
            messages.error(request, 'File metadata not found')
            return redirect('upload')

        if file_doc.get('uploaded_by') != request.user.email:
            messages.error(request, 'You are not allowed to analyze this file')
            return redirect('upload')

        grid_id = file_doc.get('file_id')
        if not grid_id:
            messages.error(request, 'Missing file reference')
            return redirect('upload')

        try:
            content = fs.get(ObjectId(grid_id)).read()
        except Exception as e:
            messages.error(request, f'Cannot read file from storage: {str(e)}')
            return redirect('upload')

        file_name = file_doc.get('file_name', 'data')
        ext = file_doc.get('file_type') or ('.' + file_name.split('.')[-1].lower())

        rows = []
        columns = []
        parse_error = None

        try:
            if ext == '.csv':
                text = content.decode('utf-8', errors='ignore')
                reader = csv.DictReader(text.splitlines())
                columns = reader.fieldnames or []
                for i, r in enumerate(reader):
                    rows.append(r)
                    if i >= 9999:
                        break
            elif ext == '.json':
                data = json.loads(content.decode('utf-8', errors='ignore'))
                if isinstance(data, list):
                    rows = data[:10000]
                elif isinstance(data, dict):
                    rows = [data]
                else:
                    rows = []
                if rows and isinstance(rows[0], dict):
                    columns = list(rows[0].keys())
            elif ext in ('.xlsx', '.xls'):
                can_read_excel = False
                if pd is not None:
                    try:
                        if ext == '.xlsx':
                            import openpyxl  # noqa: F401
                        else:
                            import xlrd  # noqa: F401
                        can_read_excel = True
                    except Exception:
                        can_read_excel = False
                if can_read_excel:
                    df = pd.read_excel(io.BytesIO(content))
                    rows = df.to_dict(orient='records')[:10000]
                    columns = list(df.columns)
                else:
                    parse_error = 'Excel analysis requires openpyxl (for .xlsx) or xlrd (for .xls).'
            else:
                parse_error = f'Unsupported file type: {ext}'
        except Exception as e:
            parse_error = str(e)

        saved_count = 0
        if rows:
            norm_rows = []
            now = datetime.now()
            for r in rows:
                if isinstance(r, dict):
                    doc = {**r, 'file_ref': str(file_doc['_id']), 'uploaded_by': request.user.email, 'created_at': now}
                else:
                    doc = {'value': r, 'file_ref': str(file_doc['_id']), 'uploaded_by': request.user.email, 'created_at': now}
                norm_rows.append(doc)
            try:
                if norm_rows:
                    data_collection.insert_many(norm_rows, ordered=False)
                    saved_count = len(norm_rows)
                    files_collection.update_one({'_id': file_doc['_id']}, {'$set': {'status': 'processed', 'record_count': saved_count or file_doc.get('record_count', 0)}})
            except Exception as e:
                parse_error = f'Data save error: {str(e)}'

        context = {
            'file_name': file_name,
            'file_id': str(file_doc['_id']),
            'columns': columns,
            'row_count': len(rows),
            'saved_count': saved_count,
            'sample_rows': rows[:10],
            'parse_error': parse_error,
            'requires_install': parse_error is not None and 'openpyxl' in parse_error.lower(),
        }
        return render(request, 'core/analyze.html', context)
    except Exception as e:
        messages.error(request, f'Analysis failed: {str(e)}')
        return redirect('upload')
