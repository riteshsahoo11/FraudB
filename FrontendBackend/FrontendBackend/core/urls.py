"""
URL patterns for core app
"""

from django.urls import path
from . import views
from django.views.generic import TemplateView

urlpatterns = [
    path("", views.home_view, name="home"),
    path("about/", views.about_view, name="about"),
    path("privacy/", views.privacy_view, name="privacy"),
    path("terms/", views.terms_view, name="terms"),
    path("contact/", views.contact_view, name="contact"),
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("predictions/", views.predictions_view, name="predictions"),
    path("upload/", views.upload_view, name="upload"),
    path("analytics/", views.analytics_view, name="analytics"),
    path("ml-ops/", views.ml_ops_view, name="ml_ops"),
    path("analyze/<str:file_doc_id>/", views.analyze_view, name="analyze"),
    path("prediction/<str:doc_id>/", views.prediction_detail_view, name="prediction_detail"),
    
    # Test pages
    path("test-data/", TemplateView.as_view(template_name="core/test_data.html"), name="test_data"),
    path("model-data/", views.show_model_data_view, name="show_model_data"),
    
    # API endpoints (in addition to the api/ app endpoints)
    path("api/dashboard-stats/", views.dashboard_stats_api, name="dashboard_stats_api"),
    path("api/notifications/", views.notifications_api, name="notifications_api"),
]
