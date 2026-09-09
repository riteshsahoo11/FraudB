from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY
from django.contrib.auth.signals import user_logged_in
from django.contrib.auth.models import update_last_login
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, Http404
import json
from .mongo_models import MongoUser, MongoFileStorage, MongoConnection
from bson import ObjectId
from .forms import SignUpForm, SignInForm, ForgotPasswordForm, ResetPasswordForm, VerifyEmailForm, ProfileForm, ChangePasswordForm
from .utils import send_verification_email, send_password_reset_email, log_user_activity

def signup_view(request):
    """User registration view"""
    if request.method == 'POST':
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                form = SignUpForm(data)
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'message': 'Invalid JSON data'})
        else:
            form = SignUpForm(request.POST)
        
        if form.is_valid():
            try:
                # Check if user already exists
                email = form.cleaned_data['email']
                username = form.cleaned_data['username']
                
                if MongoUser.find_by_email(email):
                    message = 'User with this email already exists'
                    if request.content_type == 'application/json':
                        return JsonResponse({'success': False, 'message': message})
                    messages.error(request, message)
                    return render(request, 'accounts/signup.html', {'form': form})
                
                if MongoUser.find_by_username(username):
                    message = 'User with this username already exists'
                    if request.content_type == 'application/json':
                        return JsonResponse({'success': False, 'message': message})
                    messages.error(request, message)
                    return render(request, 'accounts/signup.html', {'form': form})
                
                # Create user (simplified fields)
                user = MongoUser.create_user(
                    username=username,
                    email=email,
                    password=form.cleaned_data['password'],
                )
                
                # Generate email verification OTP
                user.set_email_otp()
                user.save()
                
                # Send verification email
                if send_verification_email(user):
                    success_message = 'Account created successfully. Please check your email for verification code.'
                    if request.content_type == 'application/json':
                        return JsonResponse({'success': True, 'message': success_message, 'redirect_url': f'/accounts/verify-email/?email={email}'})
                    
                    messages.success(request, success_message)
                    return redirect(f'/accounts/verify-email/?email={email}')
                else:
                    message = 'Account created but failed to send verification email. Please try resending.'
                    if request.content_type == 'application/json':
                        return JsonResponse({'success': False, 'message': message})
                    messages.warning(request, message)
                
            except Exception as e:
                print(f"Signup error: {e}")
                message = f'Error creating account: {str(e)}'
                if request.content_type == 'application/json':
                    return JsonResponse({'success': False, 'message': message})
                messages.error(request, message)
        else:
            if request.content_type == 'application/json':
                return JsonResponse({'success': False, 'message': 'Please correct the errors below.', 'errors': form.errors})
            messages.error(request, 'Please correct the errors below.')
    
    else:
        form = SignUpForm()
    
    return render(request, 'accounts/signup.html', {'form': form})

@ensure_csrf_cookie
def signin_view(request):
    """User login view"""
    if request.user and hasattr(request.user, 'is_authenticated') and request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                form = SignInForm(data)
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'message': 'Invalid JSON data'})
        else:
            form = SignInForm(request.POST)
        
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            
            # Authenticate user
            user = authenticate(request, username=username, password=password)
            
            if user:
                if not user.is_active:
                    message = 'Your account has been deactivated.'
                elif not user.is_email_verified:
                    message = f'Please verify your email address before logging in. <a href="/accounts/resend-verification/?email={user.email}">Resend verification email</a>'
                    if request.content_type == 'application/json':
                        return JsonResponse({
                            'success': False, 
                            'message': 'Please verify your email address before logging in.',
                            'redirect_url': f'/accounts/verify-email/?email={user.email}'
                        })
                    messages.error(request, message)
                    return render(request, 'accounts/signin.html', {'form': form})
                else:
                    # Login successful - suppress user_logged_in signal receivers during login
                    original_send = user_logged_in.send
                    try:
                        user_logged_in.send = lambda *args, **kwargs: []
                        # Force Django to store our backend path in session
                        login(request, user, backend='accounts.backends.MongoAuthBackend')
                    finally:
                        user_logged_in.send = original_send

                    log_user_activity(user, 'login', 'User logged in successfully', request)
                    
                    # Force session to store Mongo string user id for our backend
                    try:
                        request.session[SESSION_KEY] = user.id
                        request.session[BACKEND_SESSION_KEY] = 'accounts.backends.MongoAuthBackend'
                        if hasattr(user, 'get_session_auth_hash'):
                            request.session[HASH_SESSION_KEY] = user.get_session_auth_hash()
                        request.session.modified = True
                    except Exception as e:
                        print(f"Warning: could not set session keys explicitly: {e}")

                    success_message = 'Login successful!'
                    if request.content_type == 'application/json':
                        return JsonResponse({
                            'success': True, 
                            'message': success_message,
                            'redirect_url': '/dashboard/'
                        })
                    messages.success(request, success_message)
                    # Respect ?next= param if present
                    next_url = request.GET.get('next') or request.POST.get('next')
                    if next_url:
                        return redirect(next_url)
                    return redirect('dashboard')
            else:
                message = 'Invalid username/email or password.'
                if request.content_type == 'application/json':
                    return JsonResponse({'success': False, 'message': message})
                messages.error(request, message)
        else:
            if request.content_type == 'application/json':
                return JsonResponse({'success': False, 'message': 'Please correct the errors below.', 'errors': form.errors})
            messages.error(request, 'Please correct the errors below.')
    
    else:
        form = SignInForm()
    
    return render(request, 'accounts/signin.html', {'form': form})


def verify_email_view(request):
    """Email verification view"""
    email = request.GET.get('email', '')
    
    if request.method == 'POST':
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                form = VerifyEmailForm(data)
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'message': 'Invalid JSON data'})
        else:
            form = VerifyEmailForm(request.POST)
        
        if form.is_valid():
            email = form.cleaned_data['email']
            otp = form.cleaned_data['otp']
            
            try:
                user = MongoUser.find_by_email(email)
                if not user:
                    message = 'User not found.'
                    if request.content_type == 'application/json':
                        return JsonResponse({'success': False, 'message': message})
                    messages.error(request, message)
                    return render(request, 'accounts/verify_email.html', {'form': form, 'email': email})
                
                if user.verify_email_otp(otp):
                    user.save()
                    log_user_activity(user, 'email_verified', 'Email verified successfully', request)
                    
                    success_message = 'Email verified successfully! You can now log in.'
                    if request.content_type == 'application/json':
                        return JsonResponse({
                            'success': True, 
                            'message': success_message,
                            'redirect_url': '/accounts/login/'
                        })
                    messages.success(request, success_message)
                    return redirect('login')
                else:
                    message = 'Invalid or expired OTP. Please try again.'
                    if request.content_type == 'application/json':
                        return JsonResponse({'success': False, 'message': message})
                    messages.error(request, message)
                    
            except Exception as e:
                print(f"Email verification error: {e}")
                message = f'Error verifying email: {str(e)}'
                if request.content_type == 'application/json':
                    return JsonResponse({'success': False, 'message': message})
                messages.error(request, message)
        else:
            if request.content_type == 'application/json':
                return JsonResponse({'success': False, 'message': 'Please correct the errors below.', 'errors': form.errors})
            messages.error(request, 'Please correct the errors below.')
    
    else:
        form = VerifyEmailForm(initial={'email': email})
    
    return render(request, 'accounts/verify_email.html', {'form': form, 'email': email})


def resend_verification_view(request):
    """Resend email verification OTP"""
    email = request.GET.get('email', '')
    
    if request.method == 'POST':
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                email = data.get('email', '')
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'message': 'Invalid JSON data'})
        else:
            email = request.POST.get('email', '')
        
        if not email:
            message = 'Email address is required.'
            if request.content_type == 'application/json':
                return JsonResponse({'success': False, 'message': message})
            messages.error(request, message)
            return render(request, 'accounts/resend_verification.html', {'email': email})
        
        try:
            user = MongoUser.find_by_email(email)
            if not user:
                message = 'User not found.'
                if request.content_type == 'application/json':
                    return JsonResponse({'success': False, 'message': message})
                messages.error(request, message)
                return render(request, 'accounts/resend_verification.html', {'email': email})
            
            if user.is_email_verified:
                message = 'Email is already verified.'
                if request.content_type == 'application/json':
                    return JsonResponse({'success': False, 'message': message})
                messages.info(request, message)
                return render(request, 'accounts/resend_verification.html', {'email': email})
            
            # Generate new OTP
            user.set_email_otp()
            user.save()
            
            # Send verification email
            if send_verification_email(user):
                success_message = 'Verification email sent successfully. Please check your email.'
                if request.content_type == 'application/json':
                    return JsonResponse({
                        'success': True, 
                        'message': success_message,
                        'redirect_url': f'/accounts/verify-email/?email={email}'
                    })
                messages.success(request, success_message)
                return redirect(f'/accounts/verify-email/?email={email}')
            else:
                message = 'Failed to send verification email. Please try again.'
                if request.content_type == 'application/json':
                    return JsonResponse({'success': False, 'message': message})
                messages.error(request, message)
                
        except Exception as e:
            print(f"Resend verification error: {e}")
            message = f'Error sending verification email: {str(e)}'
            if request.content_type == 'application/json':
                return JsonResponse({'success': False, 'message': message})
            messages.error(request, message)
    
    return render(request, 'accounts/resend_verification.html', {'email': email})


def forgot_password_view(request):
    """Forgot password view"""
    if request.method == 'POST':
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                form = ForgotPasswordForm(data)
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'message': 'Invalid JSON data'})
        else:
            form = ForgotPasswordForm(request.POST)
        
        if form.is_valid():
            email = form.cleaned_data['email']
            
            try:
                user = MongoUser.find_by_email(email)
                if not user:
                    # Don't reveal if user exists or not for security
                    message = 'If an account with this email exists, you will receive a password reset email.'
                    if request.content_type == 'application/json':
                        return JsonResponse({'success': True, 'message': message})
                    messages.success(request, message)
                    return render(request, 'accounts/forgot_password.html', {'form': ForgotPasswordForm()})
                
                if not user.is_active:
                    message = 'If an account with this email exists, you will receive a password reset email.'
                    if request.content_type == 'application/json':
                        return JsonResponse({'success': True, 'message': message})
                    messages.success(request, message)
                    return render(request, 'accounts/forgot_password.html', {'form': ForgotPasswordForm()})
                
                # Generate reset OTP
                user.set_reset_otp()
                user.save()
                
                # Debug: Print OTP to console
                print(f"DEBUG: Generated OTP for {user.email}: {user.reset_otp}")
                
                # Send reset email
                if send_password_reset_email(user):
                    log_user_activity(user, 'password_reset_requested', 'Password reset requested', request)
                    success_message = 'Password reset email sent successfully. Please check your email.'
                    if request.content_type == 'application/json':
                        return JsonResponse({
                            'success': True, 
                            'message': success_message,
                            'redirect_url': f'/accounts/reset-password/?email={email}'
                        })
                    messages.success(request, success_message)
                    return redirect(f'/accounts/reset-password/?email={email}')
                else:
                    message = 'Failed to send password reset email. Please try again.'
                    if request.content_type == 'application/json':
                        return JsonResponse({'success': False, 'message': message})
                    messages.error(request, message)
                    
            except Exception as e:
                print(f"Forgot password error: {e}")
                message = f'Error processing request: {str(e)}'
                if request.content_type == 'application/json':
                    return JsonResponse({'success': False, 'message': message})
                messages.error(request, message)
        else:
            if request.content_type == 'application/json':
                return JsonResponse({'success': False, 'message': 'Please correct the errors below.', 'errors': form.errors})
            messages.error(request, 'Please correct the errors below.')
    
    else:
        form = ForgotPasswordForm()
    
    return render(request, 'accounts/forgot_password.html', {'form': form})


def reset_password_view(request):
    """Reset password view"""
    email = request.GET.get('email', '')
    otp_verified = False
    
    if request.method == 'POST':
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                form = ResetPasswordForm(data)
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'message': 'Invalid JSON data'})
        else:
            form = ResetPasswordForm(request.POST)
        
        if form.is_valid():
            email = form.cleaned_data['email']
            otp = form.cleaned_data['otp']
            new_password = form.cleaned_data.get('new_password')
            
            try:
                user = MongoUser.find_by_email(email)
                if not user:
                    message = 'User not found.'
                    if request.content_type == 'application/json':
                        return JsonResponse({'success': False, 'message': message})
                    messages.error(request, message)
                    return render(request, 'accounts/reset_password.html', {'form': form, 'email': email, 'otp_verified': otp_verified})
                
                # First verify OTP
                if user.verify_reset_otp(otp):
                    otp_verified = True
                    
                    # If new password is provided, reset it
                    if new_password:
                        user.set_password(new_password)
                        user.reset_otp = ''
                        user.reset_otp_expires = None
                        user.save()
                        
                        log_user_activity(user, 'password_reset', 'Password reset successfully', request)
                        
                        success_message = 'Password reset successfully! You can now log in with your new password.'
                        if request.content_type == 'application/json':
                            return JsonResponse({
                                'success': True, 
                                'message': success_message,
                                'redirect_url': '/accounts/login/'
                            })
                        messages.success(request, success_message)
                        return redirect('/accounts/login/')
                    else:
                        # OTP verified, show password reset form
                        form = ResetPasswordForm(initial={'email': email, 'otp': otp})
                        return render(request, 'accounts/reset_password.html', {'form': form, 'email': email, 'otp_verified': otp_verified})
                else:
                    message = 'Invalid or expired OTP. Please try again.'
                    if request.content_type == 'application/json':
                        return JsonResponse({'success': False, 'message': message})
                    messages.error(request, message)
                    
            except Exception as e:
                print(f"Reset password error: {e}")
                message = f'Error resetting password: {str(e)}'
                if request.content_type == 'application/json':
                    return JsonResponse({'success': False, 'message': message})
                messages.error(request, message)
        else:
            if request.content_type == 'application/json':
                return JsonResponse({'success': False, 'message': 'Please correct the errors below.', 'errors': form.errors})
            messages.error(request, 'Please correct the errors below.')
    
    else:
        form = ResetPasswordForm(initial={'email': email})
    
    return render(request, 'accounts/reset_password.html', {'form': form, 'email': email, 'otp_verified': otp_verified})


@csrf_exempt
def resend_reset_otp_view(request):
    """Resend password reset OTP"""
    if request.method == 'POST':
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                email = data.get('email', '')
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'message': 'Invalid JSON data'})
        else:
            email = request.POST.get('email', '')
        
        if not email:
            return JsonResponse({'success': False, 'message': 'Email address is required.'})
        
        try:
            user = MongoUser.find_by_email(email)
            if not user:
                # Don't reveal if user exists or not for security
                return JsonResponse({'success': True, 'message': 'If an account with this email exists, a new reset code has been sent.'})
            
            if not user.is_active:
                return JsonResponse({'success': True, 'message': 'If an account with this email exists, a new reset code has been sent.'})
            
            # Generate new reset OTP
            user.set_reset_otp()
            user.save()
            
            # Send reset email
            if send_password_reset_email(user):
                log_user_activity(user, 'password_reset_otp_resent', 'Password reset OTP resent', request)
                return JsonResponse({'success': True, 'message': 'A new reset code has been sent to your email.'})
            else:
                return JsonResponse({'success': False, 'message': 'Failed to send reset code. Please try again.'})
                
        except Exception as e:
            print(f"Resend reset OTP error: {e}")
            return JsonResponse({'success': False, 'message': 'Error sending reset code. Please try again.'})
    
    return JsonResponse({'success': False, 'message': 'Invalid request method.'})


@login_required
def logout_view(request):
    """User logout view"""
    if request.user.is_authenticated:
        log_user_activity(request.user, 'logout', 'User logged out', request)
    
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('login')


@login_required
def profile_view(request):
    """User profile view"""
    if request.method == 'POST':
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
                form = ProfileForm(data)
            except json.JSONDecodeError:
                return JsonResponse({'success': False, 'message': 'Invalid JSON data'})
        else:
            form = ProfileForm(request.POST)
        
        if form.is_valid():
            try:
                user = MongoUser.find_by_id(request.user.pk)
                if user:
                    # Update user profile
                    # Username (with uniqueness check)
                    new_username = (form.cleaned_data.get('username') or '').strip()
                    if new_username and new_username != user.username:
                        existing = MongoUser.find_by_username(new_username)
                        if existing and existing.pk != user.pk:
                            message = 'Username is already taken. Please choose another.'
                            if request.content_type == 'application/json':
                                return JsonResponse({'success': False, 'message': message}, status=400)
                            messages.error(request, message)
                            return render(request, 'accounts/profile.html', {'form': form})
                        user.username = new_username
                    user.first_name = form.cleaned_data.get('first_name', '')
                    user.last_name = form.cleaned_data.get('last_name', '')
                    user.organization = form.cleaned_data.get('organization', '')
                    user.department = form.cleaned_data.get('department', '')
                    user.phone_number = form.cleaned_data.get('phone_number', '')
                    user.save()
                    
                    # Refresh in-memory request user for current response cycle
                    try:
                        request.user.username = user.username
                        request.user.first_name = user.first_name
                        request.user.last_name = user.last_name
                    except Exception:
                        pass

                    log_user_activity(user, 'profile_updated', 'Profile updated successfully', request)
                    
                    success_message = 'Profile updated successfully!'
                    if request.content_type == 'application/json':
                        return JsonResponse({'success': True, 'message': success_message})
                    messages.success(request, success_message)
                    return redirect('profile')
                else:
                    message = 'User not found.'
                    if request.content_type == 'application/json':
                        return JsonResponse({'success': False, 'message': message})
                    messages.error(request, message)
                    
            except Exception as e:
                print(f"Profile update error: {e}")
                message = f'Error updating profile: {str(e)}'
                if request.content_type == 'application/json':
                    return JsonResponse({'success': False, 'message': message})
                messages.error(request, message)
        else:
            if request.content_type == 'application/json':
                return JsonResponse({'success': False, 'message': 'Please correct the errors below.', 'errors': form.errors})
            messages.error(request, 'Please correct the errors below.')
    
    else:
        # Pre-populate form with current user data
        user = MongoUser.find_by_id(request.user.pk)
        if user:
            initial_data = {
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'organization': user.organization,
                'department': user.department,
                'phone_number': user.phone_number,
            }
            form = ProfileForm(initial=initial_data)
        else:
            form = ProfileForm()
    
    return render(request, 'accounts/profile.html', {'form': form})


@login_required
def change_password_view(request):
    """Allow authenticated users to change their password"""
    if request.method == 'POST':
        form = ChangePasswordForm(request.POST)
        if form.is_valid():
            current_password = form.cleaned_data['current_password']
            new_password = form.cleaned_data['new_password']

            user = MongoUser.find_by_id(request.user.pk)
            if not user:
                messages.error(request, 'User not found.')
                return redirect('profile')

            # Verify current password
            if not user.check_password(current_password):
                messages.error(request, 'Current password is incorrect.')
                return render(request, 'accounts/change_password.html', {'form': form})

            # Prevent reusing same password
            if user.check_password(new_password):
                messages.error(request, 'New password must be different from the current password.')
                return render(request, 'accounts/change_password.html', {'form': form})

            # Update password
            user.set_password(new_password)
            user.save()

            try:
                log_user_activity(user, 'password_changed', 'Password changed successfully', request)
            except Exception:
                pass

            messages.success(request, 'Your password has been changed successfully.')
            return redirect('profile')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ChangePasswordForm()

    return render(request, 'accounts/change_password.html', {'form': form})

@login_required
def preferences_api(request):
    """Persist user preferences from Profile page (twoFactorAuth, loginAlerts, sessionTimeout)."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Only POST method allowed'}, status=405)

    try:
        try:
            data = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            data = {}

        two_factor = bool(data.get('two_factor_auth', False))
        login_alerts = bool(data.get('login_alerts', False))
        try:
            session_timeout = int(data.get('session_timeout', 30))
        except Exception:
            session_timeout = 30

        # Update nested preferences on user document
        users = MongoConnection.get_collection('users')
        uid = request.user.pk
        try:
            oid = ObjectId(uid) if isinstance(uid, str) else uid
        except Exception:
            return JsonResponse({'success': False, 'message': 'Invalid user id'}, status=400)

        users.update_one({'_id': oid}, {
            '$set': {
                'preferences': {
                    'two_factor_auth': two_factor,
                    'login_alerts': login_alerts,
                    'session_timeout': session_timeout
                }
            }
        })

        return JsonResponse({'success': True, 'message': 'Preferences updated'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'Failed to update preferences: {str(e)}'}, status=500)

@login_required
def export_profile_view(request):
    """Download current user's profile as a JSON file (excluding password/OTPs)."""
    try:
        users = MongoConnection.get_collection('users')
        uid = request.user.pk
        try:
            oid = ObjectId(uid) if isinstance(uid, str) else uid
        except Exception:
            return HttpResponse('Invalid user id', status=400)

        doc = users.find_one({'_id': oid})
        if not doc:
            return HttpResponse('User not found', status=404)

        # Remove sensitive fields
        for k in ['password', 'email_otp', 'email_otp_expires', 'reset_otp', 'reset_otp_expires']:
            if k in doc:
                doc.pop(k, None)
        doc['_id'] = str(doc.get('_id'))

        import json as _json
        payload = _json.dumps(doc, default=str, indent=2)
        resp = HttpResponse(payload, content_type='application/json')
        resp['Content-Disposition'] = 'attachment; filename="my_profile.json"'
        return resp
    except Exception as e:
        return HttpResponse(f'Export failed: {str(e)}', status=500)

@login_required
def avatar_upload_view(request):
    """Handle avatar upload and store it in GridFS"""
    if request.method != 'POST':
        return redirect('profile')

    file = request.FILES.get('avatar')
    if not file:
        messages.error(request, 'No file uploaded.')
        return redirect('profile')

    # Basic validation: allow common image types
    allowed_types = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
    content_type = getattr(file, 'content_type', '')
    if content_type not in allowed_types:
        messages.error(request, 'Invalid file type. Please upload a JPG, PNG, GIF, or WEBP image.')
        return redirect('profile')

    user = MongoUser.find_by_id(request.user.pk)
    if not user:
        messages.error(request, 'User not found.')
        return redirect('profile')

    try:
        # Delete old avatar if exists
        if getattr(user, 'avatar_file_id', ''):
            try:
                MongoFileStorage.delete_file(user.avatar_file_id)
            except Exception:
                pass

        # Save new avatar
        file_id = MongoFileStorage.save_file(
            file,
            filename=getattr(file, 'name', 'avatar'),
            user_id=user.id,
            metadata={'type': 'avatar'}
        )
        user.avatar_file_id = file_id
        user.save()

        messages.success(request, 'Profile photo updated successfully.')
    except Exception as e:
        print(f"Avatar upload error: {e}")
        messages.error(request, 'Failed to upload avatar. Please try again.')

    return redirect('profile')


@login_required
def avatar_image_view(request, file_id):
    """Serve avatar image from GridFS by file ID"""
    try:
        grid_file = MongoFileStorage.get_file(file_id)
        if not grid_file:
            raise Http404('File not found')

        content = grid_file.read()
        content_type = getattr(grid_file, 'content_type', 'application/octet-stream') or 'application/octet-stream'
        response = HttpResponse(content, content_type=content_type)
        # Cache for 1 hour
        response['Cache-Control'] = 'private, max-age=3600'
        return response
    except Exception as e:
        print(f"Avatar serve error: {e}")
        raise Http404('File not found')


# API Views
@csrf_exempt
def api_signup(request):
    """API endpoint for user registration"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Only POST method allowed'})
    
    return signup_view(request)


@csrf_exempt
def api_signin(request):
    """API endpoint for user login"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Only POST method allowed'})
    
    return signin_view(request)


@csrf_exempt
def api_verify_email(request):
    """API endpoint for email verification"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Only POST method allowed'})
    
    return verify_email_view(request)


@csrf_exempt
def api_forgot_password(request):
    """API endpoint for forgot password"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Only POST method allowed'})
    
    return forgot_password_view(request)


@csrf_exempt
def api_reset_password(request):
    """API endpoint for reset password"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Only POST method allowed'})
    
    return reset_password_view(request)