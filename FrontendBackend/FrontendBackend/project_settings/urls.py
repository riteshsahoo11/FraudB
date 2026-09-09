"""
URL Configuration for Predictive Transaction Intelligence for BFSI
"""
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect

# Convenience redirect functions
def login_redirect(request):
    return redirect('/accounts/login/')

def signup_redirect(request):
    return redirect('/accounts/signup/')

def logout_redirect(request):
    return redirect('/accounts/logout/')

def forgot_password_redirect(request):
    return redirect('/accounts/forgot-password/')

# Removed incorrect dashboard redirect; '/dashboard/' is provided by core.urls

# Compatibility redirect for legacy links
def legacy_core_dashboard_redirect(request):
    return redirect('/dashboard/')

urlpatterns = [
    # Convenience auth URLs (redirect to accounts app)
    path('login/', login_redirect),
    path('signin/', login_redirect),
    path('signup/', signup_redirect),
    path('register/', signup_redirect),
    path('logout/', logout_redirect),
    path('forgot-password/', forgot_password_redirect),
    path('reset-password/', forgot_password_redirect),
    # '/dashboard/' is defined in core.urls
    path('core/dashboard/', legacy_core_dashboard_redirect),
    
    # Main app URLs
    path('', include('core.urls')),
    path('accounts/', include('accounts.urls')),
    path('api/', include('api.urls')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Custom error handlers
handler404 = 'core.views.custom_404'
handler500 = 'core.views.custom_500'