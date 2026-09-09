"""
MongoDB-based session backend for Django
"""
import json
import base64
from datetime import datetime, timedelta
from django.contrib.sessions.backends.base import SessionBase
from django.conf import settings
from django.core import signing
from .mongo_models import MongoConnection


class SessionStore(SessionBase):
    """MongoDB session store"""
    
    def __init__(self, session_key=None):
        super().__init__(session_key)
        self.collection = MongoConnection.get_collection('django_sessions')
    
    def load(self):
        """Load session data from MongoDB"""
        try:
            if self.session_key is None:
                return {}
                
            session_data = self.collection.find_one({
                'session_key': self.session_key,
                'expire_date': {'$gt': datetime.now()}
            })
            
            if session_data:
                return self.decode(session_data['session_data'])
            else:
                self._session_key = None
                return {}
        except Exception:
            self._session_key = None
            return {}
    
    def exists(self, session_key):
        """Check if session exists in MongoDB"""
        return bool(self.collection.find_one({
            'session_key': session_key,
            'expire_date': {'$gt': datetime.now()}
        }))
    
    def save(self, must_create=False):
        """Save session data to MongoDB"""
        if self.session_key is None:
            self._session_key = self._get_new_session_key()
        
        session_data = {
            'session_key': self.session_key,
            'session_data': self.encode(self._get_session(no_load=must_create)),
            'expire_date': self.get_expiry_date()
        }
        
        try:
            if must_create:
                self.collection.insert_one(session_data)
            else:
                self.collection.update_one(
                    {'session_key': self.session_key},
                    {'$set': session_data},
                    upsert=True
                )
        except Exception as e:
            print(f"Session save error: {e}")
            pass
    
    def delete(self, session_key=None):
        """Delete session from MongoDB"""
        if session_key is None:
            if self.session_key is None:
                return
            session_key = self.session_key
        
        self.collection.delete_one({'session_key': session_key})
    
    @classmethod
    def clear_expired(cls):
        """Clear expired sessions from MongoDB"""
        collection = MongoConnection.get_collection('django_sessions')
        collection.delete_many({'expire_date': {'$lt': datetime.now()}})
