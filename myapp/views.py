# myapp/views.py - FINAL WORKING VERSION WITH COMPLETE M-PESA ERROR HANDLING
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.utils import timezone
from django.db.models import Sum, Count, Q
from datetime import datetime, timedelta
import json
import random
import os
import hmac
import hashlib
import requests
import uuid
import re
import threading
import time
from django.conf import settings
from .models import MonthlyVideo, Payment
from django.core.files.storage import default_storage
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET, require_http_methods

# ====================
# PAYSTACK CONFIGURATION
# ====================
PAYSTACK_SECRET_KEY = 'sk_live_fc4f550a27a942bc0f6ce014c57b1834c4b6195d'
PAYSTACK_PUBLIC_KEY = 'pk_live_197cf61799bc7493f737268952280f5da78cc7a4'
PAYSTACK_BASE_URL = 'https://api.paystack.co'

# ====================
# HELPER FUNCTIONS - FIXED FOR PAYSTACK
# ====================
def validate_and_format_phone_for_paystack(phone):
    """
    Validate and format Kenyan phone number for Paystack M-PESA.
    
    Paystack M-PESA requirements:
    - Format: "2547XXXXXXXX" (12 digits total for 07 numbers)
    - Format: "2541XXXXXXXXX" (13 digits total for 01 numbers)
    - Must be a valid Safaricom M-PESA number
    
    Returns: (is_valid, paystack_phone, display_phone, phone_digits)
    """
    if not phone:
        return False, "", "", ""
    
    # Remove all non-digit characters
    cleaned = re.sub(r'\D', '', phone)
    
    print(f"🔍 Phone validation - Input: '{phone}' -> Cleaned: '{cleaned}'")
    
    # Check minimum length
    if len(cleaned) < 9:
        print(f"❌ Too short: {len(cleaned)} digits")
        return False, "", cleaned, cleaned
    
    # Extract the phone digits (remove country code if present)
    if cleaned.startswith('254') and len(cleaned) >= 12:
        # Already has 254 prefix
        if len(cleaned) == 12:  # 2547XXXXXXXX
            phone_digits = cleaned[3:]  # Remove 254
        elif len(cleaned) == 13:  # 2541XXXXXXXXX
            phone_digits = cleaned[3:]  # Remove 254
        else:
            # Take last 9-10 digits
            phone_digits = cleaned[-9:] if cleaned[-10:][0] != '1' else cleaned[-10:]
    elif cleaned.startswith('+254'):
        # Remove +254
        phone_digits = cleaned[4:] if len(cleaned) > 4 else cleaned
    elif cleaned.startswith('0') and len(cleaned) >= 10:
        # Remove leading 0
        phone_digits = cleaned[1:]
    else:
        # Take last 9 digits
        phone_digits = cleaned[-9:]
    
    # Ensure we have the right number of digits
    if phone_digits[0] == '1' and len(phone_digits) < 10:
        # For 01 numbers, we need 10 digits
        phone_digits = phone_digits.zfill(10)
    elif phone_digits[0] == '7' and len(phone_digits) < 9:
        # For 07 numbers, we need 9 digits
        phone_digits = phone_digits.zfill(9)
    
    print(f"📱 Extracted digits: {phone_digits}")
    
    # Validate Kenyan mobile prefix
    if not phone_digits[0] in ['7', '1']:
        print(f"❌ Invalid Kenyan mobile prefix: {phone_digits[0]}")
        return False, "", "", phone_digits
    
    # Format for Paystack
    paystack_phone = f"254{phone_digits}"
    
    # Format for display
    if phone_digits[0] == '7':
        display_phone = f"0{phone_digits}"
    else:
        display_phone = phone_digits
    
    print(f"✅ Validated: {phone_digits} -> Display: {display_phone}, Paystack: {paystack_phone}")
    
    return True, paystack_phone, display_phone, phone_digits

def format_kenyan_phone(phone):
    """Format Kenyan phone number for display"""
    if not phone:
        return ""
    
    # Clean the number
    cleaned = re.sub(r'\D', '', phone)
    
    if len(cleaned) == 10:
        return f"{cleaned[:4]} {cleaned[4:7]} {cleaned[7:]}"
    elif len(cleaned) == 11:
        return f"{cleaned[:4]} {cleaned[4:8]} {cleaned[8:]}"
    elif len(cleaned) == 12 and cleaned.startswith('254'):
        # Convert 254 to 0 for display
        return f"0{cleaned[3:4]} {cleaned[4:7]} {cleaned[7:]}"
    else:
        return phone

# ====================
# DASHBOARD LOGIN
# ====================
def dashboard_login(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip().lower()
        password = request.POST.get('password', '').strip()
        
        # Debug logging
        print(f"LOGIN ATTEMPT: username='{username}', password='{password}'")
        
        # Check credentials
        if username == 'mesh' and password == 'Lumendeo@2026':
            request.session['admin_logged_in'] = True
            request.session['admin_name'] = 'Mesh'
            messages.success(request, 'Login successful! Welcome Mesh!')
            return redirect('dashboard_home')
        
        elif username == 'amos' and password == 'Lumendeo@2026':
            request.session['admin_logged_in'] = True
            request.session['admin_name'] = 'Amos'
            messages.success(request, 'Login successful! Welcome Amos!')
            return redirect('dashboard_home')
        
        elif username == 'admin' and password == 'admin123':
            request.session['admin_logged_in'] = True
            request.session['admin_name'] = 'Admin'
            messages.success(request, 'Login successful! Welcome Admin!')
            return redirect('dashboard_home')
        
        else:
            messages.error(request, 'Invalid credentials')
    
    return render(request, 'admin_login.html', {'current_year': datetime.now().year})

# ====================
# LOGOUT
# ====================
def admin_logout(request):
    request.session.flush()
    messages.success(request, 'Logged out successfully')
    return redirect('dashboard_login')

def is_admin_logged_in(request):
    return request.session.get('admin_logged_in', False)

# ====================
# MAIN DASHBOARD
# ====================
def all_in_one_dashboard(request):
    # Check login
    if not is_admin_logged_in(request):
        messages.error(request, 'Please login first')
        return redirect('dashboard_login')
    
    admin_name = request.session.get('admin_name', 'Admin')
    
    # Check URL parameter for section
    section = request.GET.get('section', 'dashboard')
    
    try:
        # GET ALL DATA AT ONCE for all sections
        # 1. REAL USER COUNT (from payments)
        total_users = Payment.objects.values('phone').distinct().count()
        
        # 2. REAL VIDEO COUNT
        total_videos = MonthlyVideo.objects.count()
        
        # 3. REAL REVENUE
        total_revenue_result = Payment.objects.filter(status=True).aggregate(total=Sum('amount'))
        total_revenue = total_revenue_result['total'] or 0
        
        # 4. TODAY'S REAL REVENUE
        today = timezone.now().date()
        today_revenue_result = Payment.objects.filter(
            timestamp__date=today,
            status=True
        ).aggregate(total=Sum('amount'))
        today_revenue = today_revenue_result['total'] or 0
        
        # 5. REAL ACTIVE VIDEOS
        active_videos = MonthlyVideo.objects.filter(
            expire_date__gte=timezone.now()
        ).count()
        
        # 6. REAL RECENT PAYMENTS (last 10)
        recent_activity = Payment.objects.select_related('movie').order_by('-timestamp')[:10]
        
        # 7. REAL LATEST VIDEOS (last 10)
        latest_videos = MonthlyVideo.objects.order_by('-date_uploaded')[:10]
        
        # 8. ALL VIDEOS for content section
        all_videos = MonthlyVideo.objects.all().order_by('-date_uploaded')
        
        # 9. REAL USERS FROM PAYMENTS
        all_payments = Payment.objects.select_related('movie').order_by('-timestamp')
        
        # Process to get unique users
        user_dict = {}
        for payment in all_payments:
            if payment.phone not in user_dict:
                user_dict[payment.phone] = {
                    'name': payment.name,
                    'phone': payment.phone,
                    'total_payments': 0,
                    'amount_spent': 0,
                    'first_payment': payment.timestamp,
                    'last_payment': payment.timestamp,
                }
            
            user_dict[payment.phone]['total_payments'] += 1
            if payment.status:
                user_dict[payment.phone]['amount_spent'] += float(payment.amount)
            
            if payment.timestamp > user_dict[payment.phone]['last_payment']:
                user_dict[payment.phone]['last_payment'] = payment.timestamp
        
        # Convert to list for template
        all_users = []
        for phone, data in user_dict.items():
            all_users.append({
                'name': data['name'],
                'phone': format_kenyan_phone(data['phone']),
                'total_payments': data['total_payments'],
                'amount_spent': data['amount_spent'],
                'join_date': data['first_payment'],
                'last_active': data['last_payment'],
                'status': 'paid' if data['amount_spent'] > 0 else 'free'
            })
        
        # Sort by last activity
        all_users.sort(key=lambda x: x['last_active'], reverse=True)
        
    except Exception as e:
        print(f"Error getting REAL data: {e}")
        # Fallback to sample data
        total_users = 0
        total_videos = 0
        total_revenue = 0
        today_revenue = 0
        active_videos = 0
        recent_activity = []
        latest_videos = []
        all_videos = []
        all_users = []
        all_payments = []
    
    # Prepare context with ALL data
    context = {
        'admin_name': admin_name,
        'today_date': timezone.now().strftime('%B %d, %Y'),
        'current_time': timezone.now(),
        'section': section,  # This tells the template which section to show initially
        'default_expire': (timezone.now() + timedelta(days=30)).strftime('%Y-%m-%d'),
        'current_year': timezone.now().year,
        
        # All data for all sections
        'stats': {
            'total_users': total_users,
            'total_videos': total_videos,
            'total_revenue': total_revenue,
            'today_revenue': today_revenue,
            'active_videos': active_videos,
            'active_sessions': random.randint(15, 40)
        },
        'recent_activity': recent_activity,
        'latest_videos': latest_videos,
        'all_videos': all_videos,
        'all_users': all_users,
        'all_payments': all_payments,
        'admin_email': 'admin@lumendeo.tv',
    }
    
    # Render the SAME template for all sections
    return render(request, 'dashboard/dashboard.html', context)

# ====================
# AJAX HANDLERS - VIDEO UPLOAD
# ====================
@csrf_exempt
def ajax_upload_video(request):
    """Handle LOCAL FILE upload via AJAX"""
    if request.method == 'POST':
        try:
            if not is_admin_logged_in(request):
                return JsonResponse({'success': False, 'error': 'Not authenticated'})
            
            print("Processing LOCAL FILE upload...")
            print(f"Files received: {list(request.FILES.keys())}")
            
            # Get form data
            title = request.POST.get('title', '').strip()
            year_published = request.POST.get('year_published', str(datetime.now().year))
            length = request.POST.get('length', '2.0')
            movie_type = request.POST.get('movie_type', 'drama')
            introduction = request.POST.get('introduction', '').strip()
            cast = request.POST.get('cast', '').strip()
            theme = request.POST.get('theme', '').strip()
            expire_date_str = request.POST.get('expire_date')
            
            # Validate required fields
            if not title:
                return JsonResponse({'success': False, 'error': 'Video title is required'})
            
            if not introduction:
                return JsonResponse({'success': False, 'error': 'Introduction text is required'})
            
            # Check for uploaded FILES
            if 'video' not in request.FILES:
                return JsonResponse({'success': False, 'error': 'Video file is required.'})
            
            if 'trailer' not in request.FILES:
                return JsonResponse({'success': False, 'error': 'Trailer file is required.'})
            
            if 'thumbnail' not in request.FILES:
                return JsonResponse({'success': False, 'error': 'Thumbnail image is required.'})
            
            # Get the uploaded files
            video_file = request.FILES['video']
            trailer_file = request.FILES['trailer']
            thumbnail_file = request.FILES['thumbnail']
            
            # Validate file types
            valid_video_types = ['video/mp4', 'video/x-m4v', 'video/quicktime', 'video/x-msvideo', 'video/webm']
            valid_image_types = ['image/jpeg', 'image/png', 'image/jpg', 'image/gif']
            
            if video_file.content_type not in valid_video_types:
                return JsonResponse({
                    'success': False,
                    'error': f'Invalid video file type. Allowed: MP4, MOV, AVI, WEBM'
                })
            
            if trailer_file.content_type not in valid_video_types:
                return JsonResponse({
                    'success': False,
                    'error': f'Invalid trailer file type. Allowed: MP4, MOV, AVI, WEBM'
                })
            
            if thumbnail_file.content_type not in valid_image_types:
                return JsonResponse({
                    'success': False,
                    'error': f'Invalid thumbnail image type. Allowed: JPG, PNG, GIF'
                })
            
            # Validate file sizes
            MAX_VIDEO_SIZE = 5 * 1024 * 1024 * 1024  # 5GB
            MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
            
            if video_file.size > MAX_VIDEO_SIZE:
                return JsonResponse({
                    'success': False,
                    'error': f'Video file is too large. Maximum size is 5GB.'
                })
            
            if trailer_file.size > MAX_VIDEO_SIZE:
                return JsonResponse({
                    'success': False,
                    'error': f'Trailer file is too large. Maximum size is 5GB.'
                })
            
            if thumbnail_file.size > MAX_IMAGE_SIZE:
                return JsonResponse({
                    'success': False,
                    'error': f'Thumbnail image is too large. Maximum size is 5MB.'
                })
            
            # Create video object
            video = MonthlyVideo(
                title=title,
                year_published=year_published,
                length=length,
                movie_type=movie_type,
                introduction=introduction,
                cast=cast,
                theme=theme,
                date_uploaded=timezone.now(),
            )
            
            # Handle expiration date
            if expire_date_str:
                try:
                    expire_date = datetime.strptime(expire_date_str, '%Y-%m-%d')
                    video.expire_date = timezone.make_aware(expire_date)
                except ValueError:
                    video.expire_date = timezone.now() + timedelta(days=30)
            else:
                video.expire_date = timezone.now() + timedelta(days=30)
            
            # Save the FILES to the model
            video.video = video_file
            video.trailer = trailer_file
            video.thumbnail = thumbnail_file
            
            # Save the video object
            video.save()
            
            print(f"✅ Video '{title}' saved successfully! ID: {video.id}")
            
            return JsonResponse({
                'success': True,
                'message': f'Video "{title}" uploaded successfully!',
                'video_id': video.id,
                'thumbnail_url': video.thumbnail.url
            })
            
        except Exception as e:
            import traceback
            print(f"❌ Error uploading video: {str(e)}")
            traceback.print_exc()
            return JsonResponse({
                'success': False,
                'error': f'Server error: {str(e)}'
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

# ====================
# AJAX HANDLERS - SETTINGS SAVE
# ====================
@csrf_exempt
def ajax_save_settings(request):
    """Handle settings save via AJAX"""
    if request.method == 'POST':
        try:
            if not is_admin_logged_in(request):
                return JsonResponse({'success': False, 'error': 'Not authenticated'})
            
            # Get form data
            admin_email = request.POST.get('admin_email', '')
            payment_amount = request.POST.get('payment_amount', '10')
            trailer_duration = request.POST.get('trailer_duration', '162')
            video_duration = request.POST.get('video_duration', '30')
            
            print(f"Settings saved - Email: {admin_email}, Payment: KES {payment_amount}")
            
            return JsonResponse({
                'success': True, 
                'message': 'Settings saved successfully!'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    return JsonResponse({'success': False, 'error': 'Invalid request'})

# ====================
# AJAX HANDLERS - VIDEO DELETE
# ====================
@csrf_exempt
def ajax_delete_video(request, video_id):
    """Handle video deletion via AJAX - FIXED VERSION"""
    if request.method == 'DELETE' or request.method == 'POST':
        try:
            if not is_admin_logged_in(request):
                return JsonResponse({'success': False, 'error': 'Not authenticated', 'code': 401})
            
            try:
                video = MonthlyVideo.objects.get(id=video_id)
            except MonthlyVideo.DoesNotExist:
                return JsonResponse({
                    'success': False, 
                    'error': f'Video with ID {video_id} does not exist',
                    'code': 404
                })
            
            title = video.title
            
            # Check for related payments
            related_payments = Payment.objects.filter(movie=video).count()
            if related_payments > 0:
                # Set movie to None for related payments instead of blocking deletion
                Payment.objects.filter(movie=video).update(movie=None)
                print(f"⚠️ Found {related_payments} payments for video '{title}', setting movie to None")
            
            # Delete the files from storage
            try:
                if video.video and video.video.name:
                    if default_storage.exists(video.video.name):
                        video.video.delete(save=False)
                if video.trailer and video.trailer.name:
                    if default_storage.exists(video.trailer.name):
                        video.trailer.delete(save=False)
                if video.thumbnail and video.thumbnail.name:
                    if default_storage.exists(video.thumbnail.name):
                        video.thumbnail.delete(save=False)
            except Exception as file_error:
                print(f"⚠️ Error deleting files: {file_error}")
                # Continue anyway
            
            # Delete the database record
            video.delete()
            
            print(f"🗑️ Video '{title}' deleted successfully!")
            
            return JsonResponse({
                'success': True, 
                'message': f'Video "{title}" deleted successfully!',
                'code': 200
            })
            
        except Exception as e:
            print(f"❌ Error deleting video: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'success': False, 
                'error': f'Server error: {str(e)}',
                'code': 500
            })
    
    return JsonResponse({
        'success': False, 
        'error': 'Invalid request method',
        'code': 405
    })

# ====================
# AJAX HANDLERS - VIDEO UPDATE
# ====================
@csrf_exempt
def ajax_update_video(request, video_id):
    """Handle video update via AJAX"""
    if request.method == 'POST':
        try:
            if not is_admin_logged_in(request):
                return JsonResponse({'success': False, 'error': 'Not authenticated'})
            
            video = MonthlyVideo.objects.get(id=video_id)
            
            # Update fields
            video.title = request.POST.get('title', video.title)
            video.year_published = request.POST.get('year_published', video.year_published)
            video.length = request.POST.get('length', video.length)
            video.movie_type = request.POST.get('movie_type', video.movie_type)
            video.introduction = request.POST.get('introduction', video.introduction)
            video.cast = request.POST.get('cast', video.cast)
            video.theme = request.POST.get('theme', video.theme)
            
            # Handle expiration date
            expire_date_str = request.POST.get('expire_date')
            if expire_date_str:
                try:
                    expire_date = datetime.strptime(expire_date_str, '%Y-%m-%d')
                    video.expire_date = timezone.make_aware(expire_date)
                except ValueError:
                    pass
            
            # Handle video file update
            if 'video' in request.FILES:
                if video.video:
                    video.video.delete(save=False)
                video.video = request.FILES['video']
            
            # Handle trailer file update
            if 'trailer' in request.FILES:
                if video.trailer:
                    video.trailer.delete(save=False)
                video.trailer = request.FILES['trailer']
            
            # Handle thumbnail update
            if 'thumbnail' in request.FILES:
                if video.thumbnail:
                    video.thumbnail.delete(save=False)
                video.thumbnail = request.FILES['thumbnail']
            
            video.save()
            
            return JsonResponse({
                'success': True, 
                'message': 'Video updated successfully!'
            })
            
        except MonthlyVideo.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Video not found'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})

# ====================
# API ENDPOINTS
# ====================
def api_user_details(request, user_id):
    """Get REAL user details by ID"""
    try:
        # Clean user_id (phone number)
        is_valid, paystack_phone, display_phone, phone_digits = validate_and_format_phone_for_paystack(user_id)
        
        if not is_valid:
            return JsonResponse({'success': False, 'error': 'Invalid phone number'})
        
        payments = Payment.objects.filter(phone=display_phone)
        
        if not payments.exists():
            return JsonResponse({'success': False, 'error': 'User not found'})
        
        first_payment = payments.order_by('timestamp').first()
        last_payment = payments.order_by('-timestamp').first()
        
        data = {
            'success': True,
            'name': first_payment.name,
            'phone': format_kenyan_phone(first_payment.phone),
            'join_date': first_payment.timestamp.strftime('%B %d, %Y'),
            'status': 'paid' if payments.filter(status=True).exists() else 'free',
            'total_payments': payments.count(),
            'amount_spent': float(payments.filter(status=True).aggregate(total=Sum('amount'))['total'] or 0),
            'last_active': last_payment.timestamp.strftime('%B %d, %Y %H:%M'),
        }
        
        return JsonResponse(data)
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def api_payment_details(request, payment_id):
    """Get REAL payment details by ID"""
    try:
        payment = Payment.objects.select_related('movie').get(id=payment_id)
        
        data = {
            'success': True,
            'transaction_id': f"TXN{payment.id:06d}",
            'name': payment.name,
            'phone': format_kenyan_phone(payment.phone),
            'movie_title': payment.movie.title if payment.movie else 'Unknown',
            'amount': float(payment.amount),
            'timestamp': payment.timestamp.strftime('%B %d, %Y %H:%M'),
            'status': 'paid' if payment.status else 'pending',
            'payment_method': payment.payment_method or 'MPESA',
        }
        
        return JsonResponse(data)
        
    except Payment.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Payment not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def api_video_details(request, video_id):
    """Get REAL video details by ID"""
    try:
        video = MonthlyVideo.objects.get(id=video_id)
        
        # Calculate views and revenue from payments
        views = Payment.objects.filter(movie=video).count()
        revenue = Payment.objects.filter(movie=video, status=True).aggregate(total=Sum('amount'))['total'] or 0
        
        data = {
            'success': True,
            'title': video.title,
            'year_published': video.year_published,
            'length': video.length,
            'movie_type': video.movie_type,
            'introduction': video.introduction,
            'cast': video.cast,
            'theme': video.theme,
            'date_uploaded': video.date_uploaded.strftime('%B %d, %Y'),
            'expire_date': video.expire_date.strftime('%B %d, %Y') if video.expire_date else 'Never',
            'views': views,
            'revenue': float(revenue),
            'is_expired': video.is_expired(),
            'video_url': video.video.url if video.video else '',
            'trailer_url': video.trailer.url if video.trailer else '',
            'thumbnail_url': video.thumbnail.url if video.thumbnail else '',
        }
        
        return JsonResponse(data)
        
    except MonthlyVideo.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Video not found'})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

def dashboard_live_data(request):
    """REAL live data for dashboard updates"""
    try:
        # Get real-time data
        total_users = Payment.objects.values('phone').distinct().count()
        total_videos = MonthlyVideo.objects.count()
        
        total_revenue_result = Payment.objects.filter(status=True).aggregate(total=Sum('amount'))
        total_revenue = total_revenue_result['total'] or 0
        
        data = {
            'success': True,
            'data': {
                'users_count': total_users,
                'videos_count': total_videos,
                'revenue': float(total_revenue),
                'active_sessions': random.randint(10, 50),
            }
        }
        
        return JsonResponse(data)
        
    except Exception as e:
        print(f"Error in live data: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

# ====================
# PAYMENT STATUS CHECK
# ====================
@csrf_exempt
def check_payment_status(request):
    """Check payment status via AJAX - COMPLETE ERROR HANDLING"""
    try:
        payment_id = request.GET.get('payment_id')
        reference = request.GET.get('reference')
        
        if not payment_id and not reference:
            return JsonResponse({
                'success': False,
                'error': 'Payment ID or reference required'
            })
        
        # Try to find payment by ID first, then reference
        if payment_id:
            try:
                payment = Payment.objects.get(id=payment_id)
            except Payment.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Payment not found'})
        else:
            try:
                payment = Payment.objects.get(payment_reference=reference)
            except Payment.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Payment not found'})
        
        # Check if already paid
        if payment.status:
            return JsonResponse({
                'success': True,
                'status': 'success',
                'message': 'Payment already confirmed',
                'already_paid': True,
                'video_id': payment.movie.id if payment.movie else None
            })
        
        # If it's been more than 3 minutes and still pending, treat as expired
        time_since_creation = timezone.now() - payment.timestamp
        if time_since_creation.total_seconds() > 180:  # 3 minutes
            payment.status = False
            payment.error_message = 'Payment request expired (took too long)'
            payment.save()
            return JsonResponse({
                'success': True,
                'status': 'expired',
                'message': 'Payment request expired. Please try again.',
                'expired': True
            })
        
        # Check with Paystack API for current status
        try:
            headers = {
                'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
            }
            
            # Try to verify transaction
            if payment.transaction_id:
                response = requests.get(
                    f'{PAYSTACK_BASE_URL}/transaction/{payment.transaction_id}',
                    headers=headers,
                    timeout=10
                )
            elif payment.payment_reference:
                response = requests.get(
                    f'{PAYSTACK_BASE_URL}/transaction/verify/{payment.payment_reference}',
                    headers=headers,
                    timeout=10
                )
            else:
                # No transaction ID yet, just return pending
                return JsonResponse({
                    'success': True,
                    'status': 'pending',
                    'message': 'Waiting for payment confirmation'
                })
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('status'):
                    transaction_data = data.get('data', {})
                    
                    # Check transaction status
                    status = transaction_data.get('status')
                    
                    if status == 'success':
                        # Update payment status
                        payment.status = True
                        payment.paystack_response = json.dumps(data)
                        payment.save()
                        
                        return JsonResponse({
                            'success': True,
                            'status': 'success',
                            'message': 'Payment confirmed!',
                            'video_id': payment.movie.id if payment.movie else None
                        })
                    
                    elif status == 'failed':
                        payment.status = False
                        error_msg = transaction_data.get('gateway_response', 'Payment failed')
                        payment.error_message = error_msg
                        payment.save()
                        
                        return JsonResponse({
                            'success': True,
                            'status': 'failed',
                            'message': f'Payment failed: {error_msg}',
                            'failed': True,
                            'retry': True
                        })
                    
                    elif status == 'pending':
                        # Still waiting
                        return JsonResponse({
                            'success': True,
                            'status': 'pending',
                            'message': 'Waiting for payment confirmation'
                        })
                    
                    elif status == 'reversed' or status == 'reversed':
                        # User cancelled
                        payment.status = False
                        payment.error_message = 'Payment cancelled by user'
                        payment.save()
                        
                        return JsonResponse({
                            'success': True,
                            'status': 'cancelled',
                            'message': 'Payment cancelled',
                            'cancelled': True,
                            'retry': True
                        })
                    else:
                        # Unknown status
                        return JsonResponse({
                            'success': True,
                            'status': 'pending',
                            'message': 'Processing payment...'
                        })
                else:
                    # API returned error
                    error_msg = data.get('message', 'Payment verification failed')
                    return JsonResponse({
                        'success': True,
                        'status': 'pending',
                        'message': 'Verifying payment...'
                    })
            else:
                # HTTP error
                return JsonResponse({
                    'success': True,
                    'status': 'pending',
                    'message': 'Checking payment status...'
                })
                
        except requests.exceptions.Timeout:
            # Timeout from Paystack
            return JsonResponse({
                'success': True,
                'status': 'pending',
                'message': 'Checking payment status...'
            })
        except requests.exceptions.ConnectionError:
            # Network error
            return JsonResponse({
                'success': True,
                'status': 'pending',
                'message': 'Network issue, checking...'
            })
        except Exception as api_error:
            # Other API errors
            print(f"Paystack API error: {api_error}")
            return JsonResponse({
                'success': True,
                'status': 'pending',
                'message': 'Processing...'
            })
        
    except Exception as e:
        print(f"Error checking payment status: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

# ====================
# PUBLIC VIEWS
# ====================
def home(request):
    """Homepage view"""
    try:
        # Get active videos (not expired)
        videos = MonthlyVideo.objects.filter(expire_date__gte=timezone.now()).order_by('-date_uploaded')
        
        # Debug: Print video count
        print(f"🏠 Homepage: Found {videos.count()} active videos")
        
        # Process introduction into chunks for first video only
        if videos:
            videos[0].intro_chunks = videos[0].get_intro_chunks()
        
        context = {
            'videos': videos,
            'current_year': timezone.now().year,
            'paystack_public_key': PAYSTACK_PUBLIC_KEY,
        }
        
        return render(request, 'index.html', context)
        
    except Exception as e:
        print(f"❌ Error in home view: {e}")
        # Return empty videos list on error
        return render(request, 'index.html', {
            'videos': [], 
            'current_year': timezone.now().year,
            'paystack_public_key': PAYSTACK_PUBLIC_KEY,
            'error': str(e)
        })

def movie_view(request):
    """Movie view page"""
    try:
        video_id = request.GET.get('id')
        if video_id:
            video = MonthlyVideo.objects.get(id=video_id)
            
            # Check if user has paid for this video
            paid = False
            phone = request.session.get('phone')
            if phone:
                payment = Payment.objects.filter(
                    phone=phone,
                    movie=video,
                    status=True
                ).first()
                if payment:
                    paid = True
            
            # Check if video is expired
            if video.is_expired():
                messages.error(request, 'This video has expired')
                return redirect('home')
            
            return render(request, 'movie.html', {
                'video': video,
                'paid': paid,
                'current_year': timezone.now().year,
            })
    except MonthlyVideo.DoesNotExist:
        messages.error(request, 'Video not found')
    return redirect('home')

@csrf_exempt
def mpesa_checkout(request):
    """Paystack M-PESA checkout - WITH COMPLETE ERROR HANDLING"""
    print("💰 PAYSTACK M-PESA CHECKOUT WITH ERROR HANDLING")
    
    if request.method == 'POST':
        try:
            # Get form data
            phone = request.POST.get('phone', '').strip()
            name = request.POST.get('name', '').strip()
            video_id = request.POST.get('video_id')
            
            print(f"📱 Payment Request: {name}, {phone}, Video: {video_id}")
            
            # Basic validation
            if not phone or not name or not video_id:
                return JsonResponse({
                    'success': False, 
                    'error': 'Name, phone and video are required'
                })
            
            # Get video
            try:
                video = MonthlyVideo.objects.get(id=video_id)
            except MonthlyVideo.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Video not found'})
            
            # Check if video is expired
            if video.is_expired():
                return JsonResponse({
                    'success': False, 
                    'error': 'This video has expired'
                })
            
            # ============================================
            # PHONE FORMATTING
            # ============================================
            # 1. Clean the phone
            cleaned_phone = phone.strip().replace(" ", "").replace("-", "")
            
            # 2. Convert to 254 format if starts with 0
            if cleaned_phone.startswith("0"):
                paystack_phone = "254" + cleaned_phone[1:]
                display_phone = cleaned_phone  # Keep 0 format for display
            elif cleaned_phone.startswith("254"):
                paystack_phone = cleaned_phone
                display_phone = "0" + cleaned_phone[3:]  # Convert to 0 format
            else:
                # Assume it's already in 254 format or add it
                paystack_phone = f"254{cleaned_phone}" if len(cleaned_phone) == 9 else cleaned_phone
                display_phone = f"0{cleaned_phone[3:]}" if cleaned_phone.startswith("254") else cleaned_phone
            
            print(f"✅ Phone: {display_phone} → Paystack: {paystack_phone}")
            
            # Check if already paid
            existing = Payment.objects.filter(
                phone=display_phone,
                movie=video,
                status=True
            ).first()
            
            if existing:
                return JsonResponse({
                    'success': True,
                    'message': 'Already paid!',
                    'already_paid': True,
                    'video_id': video.id
                })
            
            # Check if there's a pending payment within last 5 minutes
            recent_pending = Payment.objects.filter(
                phone=display_phone,
                movie=video,
                status=False,
                timestamp__gte=timezone.now() - timedelta(minutes=5)
            ).first()
            
            if recent_pending:
                # Use existing pending payment
                payment = recent_pending
                reference = payment.payment_reference
                print(f"↻ Using existing pending payment: {payment.id}, Ref: {reference}")
            else:
                # Create new payment record
                reference = f"LUMEN_{uuid.uuid4().hex[:10].upper()}"
                payment = Payment.objects.create(
                    phone=display_phone,
                    name=name,
                    amount=10.00,
                    movie=video,
                    status=False,
                    payment_reference=reference,
                    payment_method='PAYSTACK_MPESA'
                )
                print(f"📝 New payment record: {payment.id}, Ref: {reference}")
            
            # ============================================
            # PAYSTACK API CALL WITH ERROR HANDLING
            # ============================================
            headers = {
                'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                "email": f"{paystack_phone}@lumendeo.tv",
                "amount": 1000,  # 10 KES in kobo
                "reference": reference,
                "currency": "KES",
                "mobile_money": {
                    "phone": f"+{paystack_phone}",  # ← MUST HAVE + SIGN
                    "provider": "mpesa"
                }
            }
            
            print("🔄 Calling Paystack API...")
            print(f"   Phone: {payload['mobile_money']['phone']}")
            print(f"   Reference: {reference}")
            
            try:
                # Make the API call
                response = requests.post(
                    f'{PAYSTACK_BASE_URL}/charge',
                    json=payload,
                    headers=headers,
                    timeout=30
                )
                
                print(f"📡 Response Status: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if data.get('status'):
                        payment_data = data.get('data', {})
                        
                        # Save Paystack response
                        payment.transaction_id = payment_data.get('id', '')
                        payment.paystack_response = json.dumps(data)
                        payment.save()
                        
                        # Get message from Paystack
                        message = payment_data.get('display_text', 
                                    payment_data.get('message', 'Check your phone for M-PESA prompt'))
                        
                        print(f"✅ STK Push sent! Message: {message}")
                        
                        # Return SUCCESS - frontend will show loading
                        return JsonResponse({
                            'success': True,
                            'message': message,
                            'payment_id': payment.id,
                            'reference': reference,
                            'transaction_id': payment.transaction_id,
                            'status': 'pending',
                            'loading_message': 'Check your phone and enter M-PESA PIN'
                        })
                    else:
                        # Paystack API returned error
                        error_msg = data.get('message', 'Payment failed')
                        
                        # Check for specific errors
                        error_lower = error_msg.lower()
                        if 'insufficient' in error_lower:
                            error_msg = 'Insufficient M-PESA balance. Please top up and try again.'
                        elif 'timeout' in error_lower:
                            error_msg = 'Payment request timeout. Please try again.'
                        elif 'cancelled' in error_lower:
                            error_msg = 'Payment cancelled by user. Please try again.'
                        elif 'invalid' in error_lower:
                            error_msg = 'Invalid phone number. Please check and try again.'
                        elif 'not registered' in error_lower:
                            error_msg = 'Phone number not registered for M-PESA.'
                        
                        print(f"❌ Paystack error: {error_msg}")
                        
                        # Save error
                        payment.error_message = error_msg
                        payment.save()
                        
                        return JsonResponse({
                            'success': False,
                            'error': error_msg,
                            'retry': True
                        })
                else:
                    # HTTP error from Paystack
                    error_msg = f'Paystack Error {response.status_code}'
                    try:
                        error_data = response.json()
                        detailed_error = error_data.get('message', response.text[:200])
                        if detailed_error:
                            error_msg = f'{error_msg}: {detailed_error}'
                    except:
                        detailed_error = response.text[:200]
                        if detailed_error:
                            error_msg = f'{error_msg}: {detailed_error[:100]}'
                    
                    print(f"❌ HTTP Error: {error_msg}")
                    
                    # Save error
                    payment.error_message = error_msg
                    payment.save()
                    
                    return JsonResponse({
                        'success': False,
                        'error': 'Payment service temporarily unavailable. Please try again.',
                        'retry': True
                    })
                    
            except requests.exceptions.Timeout:
                error_msg = 'Payment request timeout. Please try again.'
                print(f"⏰ Timeout: {error_msg}")
                
                payment.error_message = error_msg
                payment.save()
                
                return JsonResponse({
                    'success': False,
                    'error': error_msg,
                    'retry': True
                })
                
            except requests.exceptions.ConnectionError:
                error_msg = 'Network error. Please check your internet connection and try again.'
                print(f"🌐 Connection Error: {error_msg}")
                
                payment.error_message = error_msg
                payment.save()
                
                return JsonResponse({
                    'success': False,
                    'error': error_msg,
                    'retry': True
                })
                
            except requests.exceptions.RequestException as req_err:
                error_msg = f'Payment service error: {str(req_err)}'
                print(f"🔧 Request Exception: {error_msg}")
                
                payment.error_message = error_msg
                payment.save()
                
                return JsonResponse({
                    'success': False,
                    'error': 'Payment service error. Please try again.',
                    'retry': True
                })
                
        except Exception as e:
            print(f"❌ System Error: {e}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'success': False,
                'error': 'System error. Please try again.',
                'retry': True
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})

# ====================
# PAYMENT RETRY ENDPOINT
# ====================
@csrf_exempt
def retry_payment(request):
    """Retry a failed payment"""
    if request.method == 'POST':
        try:
            payment_id = request.POST.get('payment_id')
            reference = request.POST.get('reference')
            
            if not payment_id and not reference:
                return JsonResponse({'success': False, 'error': 'Payment ID or reference required'})
            
            # Find payment
            if payment_id:
                payment = Payment.objects.get(id=payment_id)
            else:
                payment = Payment.objects.get(payment_reference=reference)
            
            # Check if payment is already successful
            if payment.status:
                return JsonResponse({
                    'success': True,
                    'message': 'Payment already successful',
                    'already_paid': True,
                    'video_id': payment.movie.id if payment.movie else None
                })
            
            # Update payment timestamp for new attempt
            payment.timestamp = timezone.now()
            payment.save()
            
            # Format phone for Paystack
            cleaned_phone = payment.phone.replace(" ", "").replace("-", "")
            if cleaned_phone.startswith("0"):
                paystack_phone = "254" + cleaned_phone[1:]
            elif cleaned_phone.startswith("254"):
                paystack_phone = cleaned_phone
            else:
                paystack_phone = f"254{cleaned_phone}"
            
            # Call Paystack API
            headers = {
                'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
                'Content-Type': 'application/json'
            }
            
            reference = payment.payment_reference or f"RETRY_{uuid.uuid4().hex[:10].upper()}"
            
            payload = {
                "email": f"{paystack_phone}@lumendeo.tv",
                "amount": 1000,
                "reference": reference,
                "currency": "KES",
                "mobile_money": {
                    "phone": f"+{paystack_phone}",
                    "provider": "mpesa"
                }
            }
            
            print(f"🔄 Retrying payment {payment.id} with reference {reference}")
            
            response = requests.post(
                f'{PAYSTACK_BASE_URL}/charge',
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('status'):
                    payment_data = data.get('data', {})
                    payment.transaction_id = payment_data.get('id', '')
                    payment.paystack_response = json.dumps(data)
                    payment.save()
                    
                    message = payment_data.get('display_text', 
                                payment_data.get('message', 'Check your phone for M-PESA prompt'))
                    
                    return JsonResponse({
                        'success': True,
                        'message': message,
                        'payment_id': payment.id,
                        'reference': reference,
                        'transaction_id': payment.transaction_id,
                        'status': 'pending'
                    })
                else:
                    error_msg = data.get('message', 'Payment failed')
                    return JsonResponse({
                        'success': False,
                        'error': error_msg,
                        'retry': True
                    })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Payment service error',
                    'retry': True
                })
                
        except Payment.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Payment not found'})
        except Exception as e:
            print(f"Retry error: {e}")
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid request'})

# ====================
# COMPATIBILITY VIEWS
# ====================
def dashboard_simple(request):
    if not is_admin_logged_in(request):
        return redirect('dashboard_login')
    return all_in_one_dashboard(request)

def content_create_simple(request):
    if not is_admin_logged_in(request):
        return redirect('dashboard_login')
    return all_in_one_dashboard(request)

def users_list_simple(request):
    if not is_admin_logged_in(request):
        return redirect('dashboard_login')
    return all_in_one_dashboard(request)

def settings_view_simple(request):
    if not is_admin_logged_in(request):
        return redirect('dashboard_login')
    return all_in_one_dashboard(request)

# ====================
# DEBUG VIEWS
# ====================
def debug_videos(request):
    """Debug view to see all videos"""
    if not is_admin_logged_in(request):
        return JsonResponse({'error': 'Not authenticated'})
    
    videos = MonthlyVideo.objects.all()
    result = []
    for v in videos:
        result.append({
            'id': v.id,
            'title': v.title,
            'expire_date': v.expire_date.strftime('%Y-%m-%d %H:%M:%S') if v.expire_date else None,
            'is_expired': v.is_expired(),
            'date_uploaded': v.date_uploaded.strftime('%Y-%m-%d %H:%M:%S'),
            'thumbnail': v.thumbnail.url if v.thumbnail else None,
            'video_url': v.video.url if v.video else None,
            'trailer_url': v.trailer.url if v.trailer else None,
        })
    
    return JsonResponse({'videos': result})

def debug_database(request):
    """Debug view to see database counts"""
    if not is_admin_logged_in(request):
        return JsonResponse({'error': 'Not authenticated'})
    
    data = {
        'total_videos': MonthlyVideo.objects.count(),
        'active_videos': MonthlyVideo.objects.filter(expire_date__gte=timezone.now()).count(),
        'expired_videos': MonthlyVideo.objects.filter(expire_date__lt=timezone.now()).count(),
        'total_payments': Payment.objects.count(),
        'paid_payments': Payment.objects.filter(status=True).count(),
        'pending_payments': Payment.objects.filter(status=False).count(),
        'unique_users': Payment.objects.values('phone').distinct().count(),
    }
    
    return JsonResponse(data)

# ====================
# MEDIA TEST VIEW
# ====================
def test_media(request):
    """Test if media files are working"""
    return JsonResponse({
        'media_root': settings.MEDIA_ROOT,
        'media_url': settings.MEDIA_URL,
        'debug': settings.DEBUG,
        'directory_exists': os.path.exists(settings.MEDIA_ROOT),
    })

# ====================
# PAYMENT TEST VIEW
# ====================
def test_phone_validation(request):
    """Test phone validation"""
    if request.method == 'POST':
        phone = request.POST.get('phone', '')
        is_valid, paystack_phone, display_phone, phone_digits = validate_and_format_phone_for_paystack(phone)
        
        return JsonResponse({
            'success': True,
            'original': phone,
            'display_format': display_phone,
            'paystack_format': paystack_phone,
            'phone_digits': phone_digits,
            'is_valid': is_valid,
            'formatted_display': format_kenyan_phone(display_phone) if is_valid else 'N/A',
        })
    
    return render(request, 'test_phone.html')

# ====================
# TEST PAYMENT VIEW
# ====================
@csrf_exempt
def test_payment(request):
    """Test payment endpoint for debugging"""
    if request.method == 'POST':
        print("🧪 TEST PAYMENT ENDPOINT CALLED")
        print(f"Data: {request.POST}")
        
        # Simulate a successful response
        return JsonResponse({
            'success': True,
            'message': 'Test payment successful!',
            'payment_id': 999,
            'reference': 'TEST_REF_123',
            'status': 'pending'
        })
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})

# ====================
# PAYSTACK TEST CONNECTION
# ====================
def test_paystack_connection(request):
    """Test Paystack API connection"""
    if not is_admin_logged_in(request):
        return JsonResponse({'error': 'Not authenticated'})
    
    try:
        headers = {
            'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
        }
        
        # Test 1: Check balance
        response = requests.get(f'{PAYSTACK_BASE_URL}/balance', headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            # Test 2: Check if M-PESA is available
            bank_response = requests.get(f'{PAYSTACK_BASE_URL}/bank?currency=KES', headers=headers, timeout=10)
            banks = bank_response.json() if bank_response.status_code == 200 else {}
            
            return JsonResponse({
                'success': True,
                'balance': data.get('data', {}),
                'mpesa_available': any('mpesa' in str(bank).lower() for bank in banks.get('data', [])),
                'api_key_type': 'LIVE' if 'live' in PAYSTACK_SECRET_KEY.lower() else 'TEST',
                'status': 'connected'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': f'Paystack API error: {response.status_code}',
                'response': response.json() if response.text else {}
            })
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

# ====================
# PAYSTACK TEST TRANSACTION
# ====================
@csrf_exempt
def test_paystack_transaction(request):
    """Test Paystack transaction with test phone numbers"""
    if request.method == 'POST':
        try:
            # Use Paystack test numbers for M-PESA
            test_numbers = [
                '254700000000',
                '254700000001', 
                '254700000002',
                '254700000003',
                '254700000004'
            ]
            
            # Get video for testing
            video = MonthlyVideo.objects.filter(is_active=True).first()
            if not video:
                return JsonResponse({'success': False, 'error': 'No active videos found'})
            
            # Pick a test number
            import random
            test_phone = random.choice(test_numbers)
            
            # Create reference
            reference = f"TEST_{uuid.uuid4().hex[:10].upper()}"
            
            # Create test payment record
            payment = Payment.objects.create(
                phone=test_phone,
                name='Test User',
                amount=10.00,
                movie=video,
                status=False,
                payment_reference=reference,
                payment_method='PAYSTACK_TEST'
            )
            
            # Call Paystack API
            headers = {
                'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'email': f'test@{reference}.com',
                'amount': 1000,
                'reference': reference,
                'currency': 'KES',
                'mobile_money': {
                    'phone': test_phone,
                    'provider': 'mpesa'
                },
                'metadata': {
                    'custom_fields': [
                        {
                            'display_name': 'Test Payment',
                            'variable_name': 'test_payment',
                            'value': 'true'
                        }
                    ]
                }
            }
            
            response = requests.post(
                f'{PAYSTACK_BASE_URL}/charge',
                json=payload,
                headers=headers,
                timeout=30
            )
            
            data = response.json()
            
            return JsonResponse({
                'success': True if data.get('status') else False,
                'test_phone': test_phone,
                'reference': reference,
                'payment_id': payment.id,
                'paystack_response': data,
                'message': 'Test transaction initiated with Paystack test number'
            })
            
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })
    
    return JsonResponse({'success': False, 'error': 'Invalid method'})

# ====================
# QUICK PAYSTACK TEST
# ====================
@csrf_exempt
def quick_test_paystack(request):
    """Quick test Paystack API"""
    headers = {
        'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
        'Content-Type': 'application/json'
    }
    
    # Test with a known working test number
    test_data = {
        'email': 'test@lumendeo.tv',
        'amount': 1000,
        'reference': f'QUICK_TEST_{uuid.uuid4().hex[:8]}',
        'currency': 'KES',
        'mobile_money': {
            'phone': '254700000001',  # Paystack test number
            'provider': 'mpesa'
        }
    }
    
    print(f"🧪 Quick Paystack Test: {json.dumps(test_data, indent=2)}")
    
    try:
        response = requests.post(
            f'{PAYSTACK_BASE_URL}/charge',
            json=test_data,
            headers=headers,
            timeout=10
        )
        
        print(f"📡 Test Response Status: {response.status_code}")
        print(f"📊 Test Response: {response.text}")
        
        if response.status_code == 200:
            data = response.json()
            return JsonResponse({
                'success': data.get('status', False),
                'message': data.get('message', 'Test completed'),
                'data': data
            })
        else:
            return JsonResponse({
                'success': False,
                'status_code': response.status_code,
                'response': response.text
            })
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        })