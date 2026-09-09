from django.urls import path
from . import views

urlpatterns = [
    # Authentication views
    path('signup/', views.signup_view, name='signup'),
    path('signin/', views.signin_view, name='signin'),
    path('login/', views.signin_view, name='login'),  # Alias for signin
    path('logout/', views.logout_view, name='logout'),
    
    # Email verification
    path('verify-email/', views.verify_email_view, name='verify_email'),
    path('resend-verification/', views.resend_verification_view, name='resend_verification'),
    
    # Password reset
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    path('reset-password/', views.reset_password_view, name='reset_password'),
    path('resend-reset-otp/', views.resend_reset_otp_view, name='resend_reset_otp'),
    path('change-password/', views.change_password_view, name='change_password'),
    
    # Profile
    path('profile/', views.profile_view, name='profile'),
    path('avatar/upload/', views.avatar_upload_view, name='avatar_upload'),
    path('avatar/<str:file_id>/', views.avatar_image_view, name='avatar_image'),
    path('preferences/', views.preferences_api, name='preferences_api'),
    path('export/', views.export_profile_view, name='export_profile'),
]
