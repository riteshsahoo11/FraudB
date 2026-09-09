from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)

class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        # Initialize MongoDB indexes on startup
        try:
            from django.conf import settings
            from accounts.mongo_models import MongoConnection
            db = MongoConnection.get_database()

            cols = settings.MONGO_COLLECTIONS

            # FraudPrediction indexes
            fp = db[cols.get('fraud_predictions', 'fraud_predictions')]
            fp.create_index('transaction_id', unique=True, name='transaction_id_unique')
            fp.create_index('customer_id', name='customer_id_idx')
            fp.create_index('timestamp', name='timestamp_idx')
            fp.create_index([('risk_score', -1)], name='risk_score_desc_idx')
            fp.create_index([('created_at', -1)], name='created_at_desc_idx')
            fp.create_index([('channel', 1)], name='channel_idx')

            # FileUpload indexes (metadata only)
            fu = db[cols.get('file_uploads', 'file_uploads')]
            fu.create_index([('upload_timestamp', -1)], name='upload_ts_desc_idx')
            fu.create_index('user_id', name='user_id_idx')
            fu.create_index('processing_status', name='processing_status_idx')

            # ModelPerformance indexes
            mp = db[cols.get('model_performance', 'model_performance')]
            mp.create_index('model_version', name='model_version_idx')
            mp.create_index([('evaluation_date', -1)], name='evaluation_date_desc_idx')

            # SystemAlerts indexes
            sa = db[cols.get('system_alerts', 'system_alerts')]
            sa.create_index('alert_type', name='alert_type_idx')
            sa.create_index('severity', name='severity_idx')
            sa.create_index([('alert_timestamp', -1)], name='alert_ts_desc_idx')
            sa.create_index('resolved_status', name='resolved_status_idx')
            sa.create_index('transaction_id', name='alert_txn_id_idx')

            logger.info('MongoDB indexes ensured for API collections')
        except Exception as e:
            logger.warning(f'Failed to initialize MongoDB indexes: {e}')
