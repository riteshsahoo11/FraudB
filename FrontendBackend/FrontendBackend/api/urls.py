from django.urls import path
from . import views

urlpatterns = [
    # Authentication APIs
    path("signup/", views.signup_api, name="signup_api"),
    path("signin/", views.signin_api, name="signin_api"),
    path("forgot-password/", views.forgot_password_api, name="forgot_password_api"),
    path("reset-password/", views.reset_password_api, name="reset_password_api"),

    # Production REST API
    path("predict", views.predict_api, name="predict_api"),
    path("upload", views.upload_api, name="upload_api"),
    path("analytics", views.analytics_api, name="analytics_api"),
    path("transactions", views.transactions_api, name="transactions_api"),
    path("transactions/<str:doc_id>/delete", views.transactions_delete_api, name="transactions_delete_api"),
    path("transactions/bulk-delete", views.transactions_bulk_delete_api, name="transactions_bulk_delete_api"),
    path("uploads/<str:upload_id>/delete", views.upload_delete_api, name="upload_delete_api"),
    path("bootstrap-demo", views.bootstrap_demo_api, name="bootstrap_demo_api"),
    path("account/delete", views.account_delete_api, name="account_delete_api"),
    path("performance", views.performance_api, name=" performance_api"),
    path("predict-batch", views.predict_batch_transactions_api, name="predict_batch_transactions_api"),
    path("alerts", views.alerts_api, name="alerts_api"),
    path("drift", views.drift_api, name="drift_api"),
    path("prediction/<str:transaction_id>/report", views.prediction_report_api, name="prediction_report_api"),
    path("profile-stats", views.profile_stats_api, name="profile_stats_api"),
    path("seed-dummy", views.seed_dummy_data_api, name="seed_dummy_data_api"),
]