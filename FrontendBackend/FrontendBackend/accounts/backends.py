from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.hashers import check_password
from django.contrib.auth import get_user_model
from .mongo_models import MongoUser, MongoConnection
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)

class MongoAuthBackend(BaseBackend):
    """
    MongoDB authentication backend - Direct MongoDB integration
    """
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate user with email/username and password using direct MongoDB queries
        """
        if not username or not password:
            return None
        
        try:
            logger.debug(f"Attempting authentication for: {username}")
            
            # Get MongoDB collection directly
            collection = MongoConnection.get_collection('users')
            
            # Find user by email or username
            user_data = None
            if '@' in username:
                user_data = collection.find_one({'email': username.lower()})
            else:
                user_data = collection.find_one({'username': username})
                if not user_data:
                    user_data = collection.find_one({'email': username.lower()})
            
            if not user_data:
                logger.warning(f"User not found: {username}")
                return None
            
            # Check password directly
            if not check_password(password, user_data.get('password', '')):
                logger.warning(f"Invalid password for user: {username}")
                return None
            
            # Check if user is active and email verified
            if not user_data.get('is_active', True):
                logger.warning(f"Inactive user: {username}")
                return None
            
            if not user_data.get('is_email_verified', False):
                logger.warning(f"Email not verified for user: {username}")
                # Still return user but views will handle email verification
            
            # Create user object manually from MongoDB data
            user = self._create_user_from_data(user_data)
            
            # Update last login
            from datetime import datetime
            collection.update_one(
                {'_id': user_data['_id']}, 
                {'$set': {'last_login': datetime.now()}}
            )
            
            # Ensure user has proper session attributes
            user._state.db = None  # Prevent Django from trying to save to DB
            
            logger.debug(f"Authentication successful for: {username}")
            return user
            
        except Exception as e:
            logger.error(f"Authentication error for {username}: {e}")
            return None
    
    def get_user(self, user_id):
        """
        Get user by ID using ONLY MongoDB
        """
        try:
            logger.debug(f"MongoAuthBackend.get_user called with user_id={user_id}")
            
            # Convert string ID to ObjectId if needed
            if isinstance(user_id, str):
                if user_id in ['None', 'null', 'undefined', '']:
                    return None
                if len(user_id) == 24:
                    try:
                        user_id = ObjectId(user_id)
                    except Exception:
                        logger.warning(f"Invalid ObjectId format: {user_id}")
                        return None
                else:
                    logger.warning(f"Invalid user_id format: {user_id}")
                    return None
            
            # Get MongoDB collection directly
            collection = MongoConnection.get_collection('users')
            user_data = collection.find_one({'_id': user_id})
            
            if not user_data:
                logger.warning(f"User not found in MongoDB: {user_id}")
                return None
            
            # Create user object from MongoDB data
            user = self._create_user_from_data(user_data)
            user._state.db = None  # Prevent Django from trying to save to DB
            logger.debug(f"Found MongoDB user: {user.username}")
            return user
            
        except Exception as e:
            logger.error(f"Get user error for ID {user_id}: {e}")
            return None
    
    def _create_user_from_data(self, user_data):
        """
        Create a user object from MongoDB data with Django compatibility
        """
        # Get Django user model for compatibility
        User = get_user_model()
        
        # Create user instance
        user = User()
        
        # Set attributes from MongoDB data
        user.pk = str(user_data['_id'])
        user.id = str(user_data['_id'])
        user.username = user_data.get('username', '')
        user.email = user_data.get('email', '')
        user.is_active = user_data.get('is_active', True)
        user.is_staff = user_data.get('is_staff', False)
        user.is_superuser = user_data.get('is_superuser', False)
        user.date_joined = user_data.get('date_joined')
        user.last_login = user_data.get('last_login')
        
        # Add MongoDB-specific attributes
        user.is_email_verified = user_data.get('is_email_verified', False)
        user.last_name = user_data.get('last_name', '')
        user.organization = user_data.get('organization', '')
        user.department = user_data.get('department', '')
        user.phone_number = user_data.get('phone_number', '')
        user.avatar_file_id = user_data.get('avatar_file_id', '')
        # RBAC role
        try:
            user.role = user_data.get('role', 'viewer')
        except Exception:
            pass
        
        return user