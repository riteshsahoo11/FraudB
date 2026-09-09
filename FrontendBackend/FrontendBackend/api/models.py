"""
MongoDB models for API app - file uploads and predictions
"""

from datetime import datetime
from bson import ObjectId
from accounts.mongo_models import MongoConnection
import gridfs


class MongoFileUpload:
    """MongoDB model for file uploads"""
    
    def __init__(self, user_email=None, file_name=None, file_path=None, 
                 file_size=0, status="uploaded", record_count=0, 
                 processed_count=0, uploaded_at=None, _id=None, **kwargs):
        self._id = _id or ObjectId()
        self.user_email = user_email
        self.file_name = file_name
        self.file_path = file_path
        self.file_size = file_size
        self.uploaded_at = uploaded_at or datetime.now()
        self.status = status
        self.record_count = record_count
        self.processed_count = processed_count
    
    def save(self):
        """Save file upload to MongoDB"""
        collection = MongoConnection.get_collection('file_uploads')
        data = self.to_dict()
        
        if collection.find_one({'_id': self._id}):
            collection.update_one({'_id': self._id}, {'$set': data})
        else:
            collection.insert_one(data)
        return self
    
    def to_dict(self):
        return {
            '_id': self._id,
            'user_email': self.user_email,
            'file_name': self.file_name,
            'file_path': self.file_path,
            'file_size': self.file_size,
            'uploaded_at': self.uploaded_at,
            'status': self.status,
            'record_count': self.record_count,
            'processed_count': self.processed_count,
        }


class MongoPrediction:
    """MongoDB model for predictions"""
    
    def __init__(self, user_email=None, file_upload_id=None, transaction_id=None,
                 prediction_data=None, predicted_label=0, confidence=0.0,
                 created_at=None, _id=None, **kwargs):
        self._id = _id or ObjectId()
        self.user_email = user_email
        self.file_upload_id = file_upload_id
        self.transaction_id = transaction_id
        self.prediction_data = prediction_data or {}
        self.predicted_label = predicted_label
        self.confidence = confidence
        self.created_at = created_at or datetime.now()
    
    def save(self):
        """Save prediction to MongoDB"""
        collection = MongoConnection.get_collection('predictions')
        data = self.to_dict()
        
        if collection.find_one({'_id': self._id}):
            collection.update_one({'_id': self._id}, {'$set': data})
        else:
            collection.insert_one(data)
        return self
    
    def to_dict(self):
        return {
            '_id': self._id,
            'user_email': self.user_email,
            'file_upload_id': self.file_upload_id,
            'transaction_id': self.transaction_id,
            'prediction_data': self.prediction_data,
            'predicted_label': self.predicted_label,
            'confidence': self.confidence,
            'created_at': self.created_at,
        }
