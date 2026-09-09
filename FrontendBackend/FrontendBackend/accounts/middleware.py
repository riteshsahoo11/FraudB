"""
MongoDB session middleware to handle ObjectId compatibility issues
"""
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import SESSION_KEY, BACKEND_SESSION_KEY
from .backends import MongoAuthBackend
from django.utils.deprecation import MiddlewareMixin
from django.core.exceptions import ValidationError
import logging

logger = logging.getLogger(__name__)

class MongoSessionMiddleware(MiddlewareMixin):
    """
    Middleware to handle MongoDB ObjectId session validation errors
    """
    
    def process_request(self, request):
        """
        Process request and handle session validation errors
        """
        # Only check if user attribute exists (set by AuthenticationMiddleware)
        if hasattr(request, 'user'):
            # Avoid repeated recovery attempts within a single request
            if getattr(request, '_mongo_auth_recovered', False):
                return
            # Proactive fast-path: if session id looks like ObjectId string, resolve via MongoAuthBackend
            try:
                sid = request.session.get(SESSION_KEY)
                sb = request.session.get(BACKEND_SESSION_KEY)
                if isinstance(sid, str) and len(sid) == 24 and sid.isalnum():
                    try:
                        backend = MongoAuthBackend()
                        user = backend.get_user(sid)
                        if user:
                            request.session[BACKEND_SESSION_KEY] = 'accounts.backends.MongoAuthBackend'
                            request.session[SESSION_KEY] = str(user.id)
                            request.user = user
                            setattr(request, '_cached_user', user)
                            setattr(request, '_mongo_auth_recovered', True)
                            return
                    except Exception:
                        # fall through to legacy recovery
                        pass
                # Fallback to legacy path that may raise, we handle below
                _ = request.user.is_authenticated
            except (ValueError, TypeError, ValidationError) as e:
                msg = str(e)
                # Log current session auth keys
                sid = request.session.get(SESSION_KEY)
                sb = request.session.get(BACKEND_SESSION_KEY)
                logger.warning(f"Auth recovery path: error='{msg}', _auth_user_id='{sid}', _auth_user_backend='{sb}'")

                if "None" in msg:
                    logger.warning(f"Session validation error (None); flushing session")
                    request.session.flush()
                    request.user = AnonymousUser()
                    return

                # Try to recover user via our backend if backend mismatch or int-casting errors
                if "must be an integer" in msg or (sb and sb != 'accounts.backends.MongoAuthBackend'):
                    try:
                        user_id = sid
                        logger.warning(f"Attempting recovery via MongoAuthBackend for id={user_id}")
                        backend = MongoAuthBackend()
                        user = backend.get_user(user_id)
                        if user:
                            # Ensure future resolution uses our backend and cache user
                            request.session[BACKEND_SESSION_KEY] = 'accounts.backends.MongoAuthBackend'
                            request.session[SESSION_KEY] = str(user.id)
                            request.user = user
                            # Cache to prevent repeated lazy resolution in this request
                            setattr(request, '_cached_user', user)
                            setattr(request, '_mongo_auth_recovered', True)
                            return
                        else:
                            logger.warning("MongoAuthBackend could not recover user; setting AnonymousUser")
                            request.user = AnonymousUser()
                            return
                    except Exception as ex:
                        logger.error(f"Recovery failed: {ex}; flushing session")
                        request.session.flush()
                        request.user = AnonymousUser()
                        return

                # Fallback
                request.session.flush()
                request.user = AnonymousUser()
                return
    
    def process_exception(self, request, exception):
        """
        Handle exceptions during request processing
        """
        if isinstance(exception, (ValueError, TypeError)):
            if "None" in str(exception) or "must be an integer" in str(exception):
                logger.warning(f"Session exception handled: {exception}")
                request.session.flush()
                request.user = AnonymousUser()
                return None  # Continue processing
        return None
