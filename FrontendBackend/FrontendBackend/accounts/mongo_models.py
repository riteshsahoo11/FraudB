"""
Pure MongoDB models for authentication and file storage
"""
import pymongo
from pymongo import MongoClient
from bson import ObjectId
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from datetime import datetime, timedelta
import hashlib
import random
import string
import gridfs
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager


class MongoConnection:
    """MongoDB connection manager"""
    _client = None
    _db = None
    
    @classmethod
    def get_client(cls):
        if cls._client is None:
            cls._client = MongoClient(settings.MONGO_URI)
        return cls._client
    
    @classmethod
    def get_database(cls):
        if cls._db is None:
            cls._db = cls.get_client()[settings.MONGO_DB_NAME]
        return cls._db
    
    @classmethod
    def get_collection(cls, collection_name):
        return cls.get_database()[collection_name]
    
    @classmethod
    def get_gridfs(cls):
        """Get GridFS for file storage"""
        return gridfs.GridFS(cls.get_database())


class MongoUser:
    """MongoDB User model"""
    
    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.username = kwargs.get('username', '')
        self.email = kwargs.get('email', '')
        self.password = kwargs.get('password', '')
        self.first_name = kwargs.get('first_name', '')
        self.last_name = kwargs.get('last_name', '')
        self.organization = kwargs.get('organization', '')
        self.department = kwargs.get('department', '')
        self.phone_number = kwargs.get('phone_number', '')
        self.avatar_file_id = kwargs.get('avatar_file_id', '')
        self.role = kwargs.get('role', 'viewer')
        self.is_active = kwargs.get('is_active', True)
        self.is_email_verified = kwargs.get('is_email_verified', False)
        self.email_otp = kwargs.get('email_otp', '')
        self.email_otp_expires = kwargs.get('email_otp_expires')
        self.reset_otp = kwargs.get('reset_otp', '')
        self.reset_otp_expires = kwargs.get('reset_otp_expires')
        self.date_joined = kwargs.get('date_joined', datetime.now())
        self.last_login = kwargs.get('last_login')
    
    @property
    def pk(self):
        """Primary key property for Django compatibility"""
        return str(self._id) if self._id else None
    
    @property
    def id(self):
        """ID property for Django compatibility"""
        return str(self._id) if self._id else None
    
    @property
    def is_authenticated(self):
        """Always return True for authenticated users"""
        return True
    
    @property
    def is_anonymous(self):
        """Always return False for authenticated users"""
        return False
    
    def save(self):
        """Save user to MongoDB"""
        collection = MongoConnection.get_collection(getattr(settings, 'MONGO_COLLECTIONS', {}).get('users', 'users'))
        
        user_data = {
            'username': self.username,
            'email': self.email,
            'password': self.password,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'organization': self.organization,
            'department': self.department,
            'phone_number': self.phone_number,
            'avatar_file_id': self.avatar_file_id,
            'role': self.role,
            'is_active': self.is_active,
            'is_email_verified': self.is_email_verified,
            'email_otp': self.email_otp,
            'email_otp_expires': self.email_otp_expires,
            'reset_otp': self.reset_otp,
            'reset_otp_expires': self.reset_otp_expires,
            'date_joined': self.date_joined,
            'last_login': self.last_login,
        }
        
        if self._id:
            collection.update_one({'_id': self._id}, {'$set': user_data})
        else:
            result = collection.insert_one(user_data)
            self._id = result.inserted_id
        
        return self
    
    def check_password(self, raw_password):
        """Check if the provided password matches the stored password"""
        return check_password(raw_password, self.password)
    
    def set_password(self, raw_password):
        """Set password with hashing"""
        self.password = make_password(raw_password)
    
    def set_email_otp(self, expiry_minutes=10):
        """Generate and set email verification OTP"""
        self.email_otp = ''.join(random.choices(string.digits, k=6))
        self.email_otp_expires = datetime.now() + timedelta(minutes=expiry_minutes)
    
    def set_reset_otp(self, expiry_minutes=10):
        """Generate and set password reset OTP"""
        self.reset_otp = ''.join(random.choices(string.digits, k=6))
        self.reset_otp_expires = datetime.now() + timedelta(minutes=expiry_minutes)
    
    def verify_email_otp(self, otp):
        """Verify email OTP"""
        if (self.email_otp == otp and 
            self.email_otp_expires and 
            datetime.now() < self.email_otp_expires):
            self.is_email_verified = True
            self.email_otp = ''
            self.email_otp_expires = None
            return True
        return False
    
    def verify_reset_otp(self, otp):
        """Verify password reset OTP"""
        if (self.reset_otp == otp and 
            self.reset_otp_expires and 
            datetime.now() < self.reset_otp_expires):
            return True
        return False
    
    def update_last_login(self):
        """Update last login timestamp"""
        self.last_login = datetime.now()
    
    @classmethod
    def create_user(cls, username, email, password, **extra_fields):
        """Create a new user"""
        user = cls(
            username=username,
            email=email.lower(),
            **extra_fields
        )
        user.set_password(password)
        return user.save()
    
    @classmethod
    def find_by_email(cls, email):
        """Find user by email"""
        collection = MongoConnection.get_collection(getattr(settings, 'MONGO_COLLECTIONS', {}).get('users', 'users'))
        user_data = collection.find_one({'email': email.lower()})
        return cls(**user_data) if user_data else None
    
    @classmethod
    def find_by_username(cls, username):
        """Find user by username"""
        collection = MongoConnection.get_collection(getattr(settings, 'MONGO_COLLECTIONS', {}).get('users', 'users'))
        user_data = collection.find_one({'username': username})
        return cls(**user_data) if user_data else None
    
    @classmethod
    def find_by_id(cls, user_id):
        """Find user by ID"""
        collection = MongoConnection.get_collection(getattr(settings, 'MONGO_COLLECTIONS', {}).get('users', 'users'))
        try:
            if isinstance(user_id, str):
                if len(user_id) == 24 and user_id.isalnum():
                    user_id = ObjectId(user_id)
                else:
                    return None
            user_data = collection.find_one({'_id': user_id})
            return cls(**user_data) if user_data else None
        except Exception:
            return None
    
    def __str__(self):
        return self.username


class MongoOTP:
    """MongoDB OTP model"""
    
    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.user_email = kwargs.get('user_email')
        self.otp_code = kwargs.get('otp_code')
        self.otp_type = kwargs.get('otp_type')
        self.created_at = kwargs.get('created_at', datetime.now())
        self.expires_at = kwargs.get('expires_at')
        self.is_used = kwargs.get('is_used', False)
    
    def save(self):
        """Save OTP to MongoDB"""
        collection = MongoConnection.get_collection(settings.MONGO_COLLECTIONS['otps'])
        
        otp_data = {
            'user_email': self.user_email,
            'otp_code': self.otp_code,
            'otp_type': self.otp_type,
            'created_at': self.created_at,
            'expires_at': self.expires_at,
            'is_used': self.is_used,
        }
        
        if self._id:
            collection.update_one({'_id': self._id}, {'$set': otp_data})
        else:
            result = collection.insert_one(otp_data)
            self._id = result.inserted_id
        
        return self
    
    def is_valid(self):
        """Check if OTP is still valid"""
        return not self.is_used and datetime.now() < self.expires_at
    
    @classmethod
    def generate_otp(cls, user_email, otp_type, expiry_minutes=10):
        """Generate a new OTP"""
        collection = MongoConnection.get_collection(settings.MONGO_COLLECTIONS['otps'])
        
        # Invalidate previous OTPs
        collection.update_many(
            {'user_email': user_email, 'otp_type': otp_type, 'is_used': False},
            {'$set': {'is_used': True}}
        )
        
        # Generate new OTP
        otp_code = ''.join(random.choices(string.digits, k=6))
        
        otp = cls(
            user_email=user_email,
            otp_code=otp_code,
            otp_type=otp_type,
            expires_at=datetime.now() + timedelta(minutes=expiry_minutes)
        )
        return otp.save()


class MongoUserActivity:
    """MongoDB User Activity model"""
    
    def __init__(self, **kwargs):
        self._id = kwargs.get('_id')
        self.user_email = kwargs.get('user_email')
        self.activity_type = kwargs.get('activity_type')
        self.description = kwargs.get('description')
        self.ip_address = kwargs.get('ip_address')
        self.user_agent = kwargs.get('user_agent', '')
        self.created_at = kwargs.get('created_at', datetime.now())
    
    def save(self):
        """Save activity to MongoDB"""
        collection = MongoConnection.get_collection(settings.MONGO_COLLECTIONS['user_activities'])
        
        activity_data = {
            'user_email': self.user_email,
            'activity_type': self.activity_type,
            'description': self.description,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'created_at': self.created_at,
        }
        
        result = collection.insert_one(activity_data)
        self._id = result.inserted_id
        return self
    
    @classmethod
    def create(cls, **kwargs):
        """Create and save activity"""
        activity = cls(**kwargs)
        return activity.save()


class MongoFileStorage:
    """MongoDB GridFS file storage"""
    
    @classmethod
    def save_file(cls, file_data, filename, user_id, metadata=None):
        """Save file to GridFS"""
        fs = MongoConnection.get_gridfs()
        
        file_metadata = {
            'filename': filename,
            'uploaded_by': user_id,
            'uploaded_at': datetime.now(),
            'content_type': getattr(file_data, 'content_type', 'application/octet-stream'),
            'size': len(file_data.read()) if hasattr(file_data, 'read') else len(file_data),
        }
        
        if metadata:
            file_metadata.update(metadata)
        
        # Reset file pointer if it's a file object
        if hasattr(file_data, 'seek'):
            file_data.seek(0)
        
        file_id = fs.put(file_data, **file_metadata)
        return str(file_id)
    
    @classmethod
    def get_file(cls, file_id):
        """Get file from GridFS"""
        fs = MongoConnection.get_gridfs()
        try:
            return fs.get(ObjectId(file_id))
        except gridfs.NoFile:
            return None
    
    @classmethod
    def delete_file(cls, file_id):
        """Delete file from GridFS"""
        fs = MongoConnection.get_gridfs()
        try:
            fs.delete(ObjectId(file_id))
            return True
        except gridfs.NoFile:
            return False
    
    @classmethod
    def list_user_files(cls, user_id, limit=None):
        """List files uploaded by user"""
        fs = MongoConnection.get_gridfs()
        query = {'uploaded_by': user_id}
        
        files = []
        for grid_file in fs.find(query).sort('uploadDate', -1):
            if limit and len(files) >= limit:
                break
            
            files.append({
                'id': str(grid_file._id),
                'filename': grid_file.filename,
                'size': grid_file.length,
                'upload_date': grid_file.upload_date,
                'content_type': grid_file.content_type,
                'metadata': grid_file.metadata
            })
        
        return files
