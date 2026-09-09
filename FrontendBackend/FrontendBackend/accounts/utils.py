from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from datetime import datetime, timedelta
from accounts.mongo_models import MongoUserActivity
import secrets
import string

def generate_otp(length=6):
    """Generate a random numeric OTP"""
    return ''.join(secrets.choice(string.digits) for _ in range(length))

def send_verification_email(user):
    """Send email verification OTP"""
    try:
        subject = f'Email Verification - Your OTP: {user.email_otp}'
        
        # Create email context
        context = {
            'user': user,
            'otp_code': user.email_otp,
            'expiry_minutes': 10,
            'site_name': 'BFSI Platform'
        }
        
        # Try to render HTML template, fallback to plain text
        try:
            html_message = render_to_string('accounts/emails/otp_verification.html', context)
            plain_message = strip_tags(html_message)
        except:
            # Fallback plain text message
            plain_message = f"""
            Hello {user.username},

            Your email verification OTP is: {user.email_otp}

            This OTP will expire in 10 minutes.

            Best regards,
            BFSI Platform Team
            """
            html_message = None
        
        # Send email
        send_mail(
            subject=subject,
            message=plain_message,
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        # Debug confirmation to server logs
        try:
            print(f"DEBUG: Verification email sent to {user.email} with OTP {user.email_otp}")
        except Exception:
            pass
        return True
        
    except Exception as e:
        print(f"Error sending verification email: {e}")
        return False

def send_password_reset_email(user):
    """Send password reset OTP"""
    try:
        subject = f'Password Reset OTP: {user.reset_otp}'
        
        # Create email context
        context = {
            'user': user,
            'otp_code': user.reset_otp,
            'expiry_minutes': 10,
            'site_name': 'BFSI Platform'
        }
        
        # Try to render HTML template, fallback to plain text
        try:
            html_message = render_to_string('accounts/emails/password_reset_otp.html', context)
            plain_message = strip_tags(html_message)
        except:
            # Fallback plain text message
            plain_message = f"""
            Hello {user.username},

            Your password reset OTP is: {user.reset_otp}

            This OTP will expire in 10 minutes.

            If you did not request this, please ignore this email.

            Best regards,
            BFSI Platform Team
            """
            html_message = None
        
        # Send email
        send_mail(
            subject=subject,
            message=plain_message,
            html_message=html_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        return True
        
    except Exception as e:
        print(f"Error sending reset email: {e}")
        return False

def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip
def get_user_agent(request):
    """Get user agent from request"""
    return request.META.get('HTTP_USER_AGENT', '')

def log_user_activity(user, activity_type, description, request=None):
    """Log user activity to MongoDB and print to server logs"""
    try:
        payload = {
            'user_email': getattr(user, 'email', ''),
            'activity_type': activity_type,
            'description': description,
            'ip_address': get_client_ip(request) if request else None,
            'user_agent': get_user_agent(request) if request else '',
            'created_at': datetime.utcnow(),
        }
        try:
            MongoUserActivity.create(**payload)
        except Exception:
            # Fallback to print if DB write fails
            pass
        try:
            print(f"Activity logged: {payload}")
        except Exception:
            pass
        return True
    except Exception as e:
        try:
            print(f"Error logging activity: {e}")
        except Exception:
            pass
        return False