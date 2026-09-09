from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from bson import ObjectId

class MinimalUserManager(BaseUserManager):
    """Minimal user manager for Django compatibility"""
    
    def create_user(self, username, email, password=None, **extra_fields):
        # This won't be used since we handle users through MongoDB
        pass
    
    def create_superuser(self, username, email, password=None, **extra_fields):
        # This won't be used since we handle users through MongoDB  
        pass

class MinimalUser(AbstractBaseUser):
    """
    Minimal Django user model for compatibility.
    Actual user data is stored in MongoDB via MongoUser class.
    """
    id = models.CharField(max_length=24, primary_key=True)  # MongoDB ObjectId as string
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)
    
    objects = MinimalUserManager()
    
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email']
    
    class Meta:
        db_table = 'minimal_user'
    
    def __str__(self):
        return self.username
    
    def has_perm(self, perm, obj=None):
        return self.is_superuser
    
    def has_module_perms(self, app_label):
        return self.is_superuser
    
    @property
    def is_authenticated(self):
        return True
    
    @property
    def is_anonymous(self):
        return False