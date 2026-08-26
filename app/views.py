from datetime import datetime, date, timedelta
from decimal import Decimal
from collections import defaultdict
from functools import wraps
from io import BytesIO
import os
import re
import uuid
import random
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse, Http404, HttpResponseForbidden
from django.urls import reverse
from django.utils import timezone
from django.db import transaction
from django.core.paginator import Paginator
from django.db import ProgrammingError
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout as auth_logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.core.files.storage import default_storage
import razorpay
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from django.core.files.base import ContentFile
from urllib3 import request
from django.core.exceptions import FieldError

from .models import (
    Inventory,
    History,
    BookingExtension,
    UserDetail,
    Payment,
    Services,
    SupportService,
    SupportServiceContact,
    Cart,
    CartItem,
    Receipt,
    Customer,
    NotifyRequest,
    BloodRequest,
    CampOrganizer,
    BloodDonor,
    EventVolunteer,
    Role,
    UserRole,
    BloodBank,
    user_has_permission,
    user_has_any_permission,
)

def rbac_view_permission(permission_name):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('signin')

            if not user_has_permission(request.user, permission_name):
                return render(request, 'permission_denied.html', status=403)

            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def ensure_module_access(request, permission_name):
    """Enforce module-level access according to role-assignment policy.

    - Superuser/staff: always allowed.
    - If the user has no Role assigned: allow (default access to normal modules).
    - If the user has one or more Roles assigned: require the given permission
      (checked via `user_has_permission`).
    - Anonymous users are allowed for public views (this helper returns None
      to indicate allowed). Views that require login must still use
      `@login_required` or check authentication separately.

    Returns: None when access is allowed; an HttpResponse (403 or redirect)
    when access is denied or user should sign in.
    """
    # Admins are always allowed
    if request.user.is_authenticated and (request.user.is_superuser or request.user.is_staff):
        return None

    # If not authenticated, treat as public — allow here (views may require login)
    if not request.user.is_authenticated:
        return None

    # If user has no role assignments, allow default normal-module access
    from .models import user_has_assigned_role
    if not user_has_assigned_role(request.user):
        return None

    # User has a role assigned: enforce permission
    if not user_has_permission(request.user, permission_name):
        return render(request, 'permission_denied.html', status=403)

    return None
from .forms import BloodRequestForm, CampOrganizerForm, BloodDonorForm, EventVolunteerForm, AssignEmployeeForm
from .utils import send_overdue_email, generate_sequential_order_id, generate_receipt, receipt_filename, send_whatsapp_message, send_notification, build_booking_receipt_breakdown

def index(request):
    # Reminder and overdue notification logic has been moved out of the homepage
    # request path so regular page loads stay fast. Use the management command
    # `python manage.py send_reminders` or a scheduled job instead.
    featured_items = Inventory.objects.all().order_by('-available', 'title')[:4]

    return render(request, 'index.html', {
        'featured_items': featured_items
    })


def logout(request):
    if request.user.is_authenticated:
        Cart.objects.filter(user_id=request.user.id).delete()

    auth_logout(request)
    return redirect('signin')

def signup(request):
    if request.method == 'POST':
        if request.POST.get('otp'):
            mobile = request.POST.get('mobile')
            otp = request.POST.get('otp')

            otp_data = request.session.get('otp_data')
            if not otp_data:
                messages.error(request, "No OTP session found. Please register again.")
                return redirect('signup')

            digits = re.sub(r"\D", "", str(mobile or ""))
            try:
                exp = datetime.fromisoformat(otp_data.get('expires'))
            except Exception:
                exp = None

            if exp and timezone.now() > exp:
                request.session.pop('otp_data', None)
                messages.error(request, "OTP expired. Please register again.")
                return redirect('signup')

            if digits != otp_data.get('mobile') or otp != otp_data.get('otp'):
                messages.error(request, "Invalid OTP or mobile number.")
                ctx = {'show_otp': True, 'mobile': digits}
                if getattr(settings, 'DEBUG', False):
                    ctx['debug_otp'] = otp_data.get('otp')
                return render(request, 'signup.html', ctx)

            username = otp_data.get('username')
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                messages.error(request, "User not found; please register again.")
                return redirect('signup')

            ab = getattr(settings, 'AUTHENTICATION_BACKENDS', None)
            backend = ab[0] if ab else 'django.contrib.auth.backends.ModelBackend'
            user.backend = backend
            login(request, user)
            request.session.pop('otp_data', None)
            messages.success(request, "Registration complete and logged in.")
            return redirect('index')

        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        mobile = request.POST.get('mobile')

        field_errors = {}
        if not username:
            field_errors['username'] = "Username is required."
        elif username[0].isdigit():
            field_errors['username'] = "Username should not start with a digit."
        elif User.objects.filter(username=username).exists():
            field_errors['username'] = "Username already taken."

        if not mobile:
            field_errors['mobile'] = "Mobile number is required."
        else:
            clean_mob = re.sub(r'\D', '', mobile)
            if len(clean_mob) != 10:
                field_errors['mobile'] = "Contact number must be exactly 10 digits."

        if not password:
            field_errors['password'] = "Password is required."
        elif len(password) < 6:
            field_errors['password'] = "Password must be at least 6 characters long."
        elif not re.search(r'[A-Z]', password):
            field_errors['password'] = "Password must contain at least one uppercase letter."
        elif not re.search(r'[a-z]', password):
            field_errors['password'] = "Password must contain at least one lowercase letter."
        elif not re.search(r'\d', password):
            field_errors['password'] = "Password must contain at least one digit."
        elif not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            field_errors['password'] = "Password must contain at least one special character."

        if confirm_password != password:
            field_errors['confirm_password'] = "Passwords do not match."

        if field_errors:
            return render(request, 'signup.html', {
                'field_errors': field_errors,
                'username': username,
                'email': email,
                'mobile': mobile,
            })

        user = User.objects.create_user(username=username, email=email, password=password)
        user.save()

        try:
            send_notification(
                title="New User Registered",
                message=f"New user registered: {user.username} ({user.email}).",
                notification_type='user',
                link=f"/admin/auth/user/{user.id}/change/"
            )
        except Exception as e:
            print(f"[notification signup error] {e}")

        digits = re.sub(r"\D", "", str(mobile or ""))
        otp = str(random.randint(100000, 999999))
        expires = (timezone.now() + timedelta(minutes=5)).isoformat()

        request.session['otp_data'] = {
            'mobile': digits,
            'otp': otp,
            'expires': expires,
            'username': username,
        }

        message = f"Your QuickNest OTP is {otp}. It expires in 5 minutes."
        send_whatsapp_message(digits, message)

        messages.success(request, "Account created. OTP sent via WhatsApp (simulated if not configured).")
        ctx = {'show_otp': True, 'mobile': digits}
        if getattr(settings, 'DEBUG', False):
            ctx['debug_otp'] = otp
        return render(request, 'signup.html', ctx)

    if request.user.is_authenticated:
        return redirect('index')

    return render(request, 'signup.html')

def signin(request):
    if request.user.is_authenticated:
        next_url = request.GET.get('next') or request.POST.get('next')
        if next_url and next_url not in ['/signin/', '/signin', 'signin']:
            return redirect(next_url)
        return redirect('index')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        field_errors = {}
        if not username:
            field_errors['username'] = "Username is required."
        if not password:
            field_errors['password'] = "Password is required."

        if not field_errors:
            try:
                user = User.objects.get(username=username)
                if password.isdigit():
                    field_errors['password'] = "Password should contain alphabets or special characters."
                else:
                    authenticated_user = authenticate(request, username=username, password=password)
                    if authenticated_user is not None:
                        login(request, authenticated_user)
                        return redirect('index')
                    else:
                        field_errors['password'] = "Invalid username or password."
            except User.DoesNotExist:
                field_errors['username'] = "User not found."

        if field_errors:
            return render(request, 'signin.html', {
                'field_errors': field_errors,
                'username': username,
            })

    return render(request, 'signin.html')


def signin_mobile(request):
    """Start login via mobile number. Generates OTP and sends via WhatsApp.
    - POST with `mobile` sends OTP and shows verify page
    - GET renders a simple mobile input form
    """
    if request.method == 'POST':
        mobile = request.POST.get('mobile')
        if not mobile:
            messages.error(request, "Please enter a mobile number.")
            return redirect('signin_mobile')

        digits = re.sub(r"\D", "", mobile)
        if not digits:
            messages.error(request, "Enter a valid mobile number.")
            return redirect('signin_mobile')

        otp = str(random.randint(100000, 999999))
        expires = (timezone.now() + timedelta(minutes=5)).isoformat()

        request.session['otp_data'] = {
            'mobile': digits,
            'otp': otp,
            'expires': expires,
        }

        message = f"Your QuickNest OTP is {otp}. It expires in 5 minutes."
        send_whatsapp_message(digits, message)

        messages.success(request, "OTP sent via WhatsApp (simulated if not configured).")
        return redirect('verify_otp')

    return render(request, 'signin_mobile.html')

def verify_otp(request):
    """Verify OTP entered by user and log them in (creates user if needed)."""
    otp_data = request.session.get('otp_data')

    if request.method == 'POST':
        mobile = request.POST.get('mobile')
        otp = request.POST.get('otp')

        if not otp_data:
            messages.error(request, "No OTP request found. Please request a new OTP.")
            return redirect('signin_mobile')

        digits = re.sub(r"\D", "", mobile or "")

        if digits != otp_data.get('mobile'):
            messages.error(request, "Mobile number mismatch.")
            return redirect('signin_mobile')
        try:
            exp = datetime.fromisoformat(otp_data.get('expires'))
        except Exception:
            exp = None

        if exp and timezone.now() > exp:
            request.session.pop('otp_data', None)
            messages.error(request, "OTP expired. Please request a new one.")
            return redirect('signin_mobile')

        if otp and otp == otp_data.get('otp'):
            username = otp_data.get('mobile')
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                user = User.objects.create_user(username=username)
                user.set_unusable_password()
                user.save()

            ab = getattr(settings, 'AUTHENTICATION_BACKENDS', None)
            backend = ab[0] if ab else 'django.contrib.auth.backends.ModelBackend'
            user.backend = backend
            login(request, user)
            request.session.pop('otp_data', None)
            return redirect('index')
        else:
            messages.error(request, "Invalid OTP.")
            return redirect('verify_otp')

    mobile_prefill = otp_data.get('mobile') if otp_data else ''
    ctx = {'mobile': mobile_prefill}
    if getattr(settings, 'DEBUG', False) and otp_data:
        ctx['debug_otp'] = otp_data.get('otp')
    return render(request, 'verify_otp.html', ctx)


def forgot(request):
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        if not username:
            return render(request, 'forgot.html', {'field_errors': {'username': 'Username is required.'}})
        try:
            user = User.objects.get(username=username)
            return redirect('resetpass', username=username)
        except User.DoesNotExist:
            return render(request, 'forgot.html', {'field_errors': {'username': 'Username does not exist.'}, 'username': username})
    return render(request, 'forgot.html')

def resetpass(request, username):
    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        field_errors = {}
        if not new_password:
            field_errors['new_password'] = "New password is required."
        elif len(new_password) < 6:
            field_errors['new_password'] = "Password must be at least 6 characters long."

        if not confirm_password:
            field_errors['confirm_password'] = "Confirm password is required."
        elif new_password and confirm_password and new_password != confirm_password:
            field_errors['confirm_password'] = "Passwords do not match."

        if field_errors:
            return render(request, 'resetpass.html', {'username': username, 'field_errors': field_errors})

        try:
            user = User.objects.get(username=username)
            user.password = make_password(new_password)
            user.save()
            messages.success(request, "Password reset successfully. Please sign in.")
            return redirect('signin')
        except User.DoesNotExist:
            return render(request, 'forgot.html', {'field_errors': {'username': 'User not found.'}})

    return render(request, 'resetpass.html', {'username': username})

def items(request):
    # Enforce module access: equipment rental maps to 'can_access_inventory'
    resp = ensure_module_access(request, 'can_access_inventory')
    if resp:
        return resp
    items = Inventory.objects.all().order_by('-available', 'title')
    search_query = request.GET.get('q', '').strip()
    if search_query:
        items = items.filter(title__icontains=search_query)

    paginator = Paginator(items, 16)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'items.html', {
        'items': page_obj,
        'page_obj': page_obj,
        'search_query': search_query,
    })

@login_required
@user_passes_test(lambda u: user_has_permission(u, 'can_access_inventory'))
def inventory(request):
    items = Inventory.objects.all().order_by('-available', 'title')
    search_query = request.GET.get('q', '').strip()
    if search_query:
        items = items.filter(title__icontains=search_query)

    paginator = Paginator(items, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Availability is maintained by booking signals when rentals are created/updated.
    # Avoid recomputing availability here on every page load to keep the inventory page fast.
    return render(request, 'inventory.html', {
        'items': page_obj,
        'page_obj': page_obj,
        'search_query': search_query,
    })

@login_required
@user_passes_test(lambda u: user_has_permission(u, 'can_access_inventory'))
def add_inventory_item(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        price_per_day = request.POST.get('price_per_day', 0)
        deposit = request.POST.get('deposit', 0)
        total_quantity = int(request.POST.get('total_quantity', 1) or 1)
        next_available_date = request.POST.get('next_available_date') or None
        available = request.POST.get('available') == 'on'
        item_qty = int(request.POST.get('item_qty', 1) or 1)
        price = request.POST.get('price', 0)
        donation = request.POST.get('donation') == 'on'
        donor_name = request.POST.get('donor_name', '').strip()
        donor_contact = request.POST.get('donor_contact', '').strip()
        uploaded_image = request.FILES.get('image')

        existing_item = Inventory.objects.filter(title__iexact=title).first()

        if existing_item:
            existing_item.total_quantity += total_quantity
            existing_item.item_qty += item_qty
            if description:
                existing_item.description = description
            if price_per_day:
                existing_item.price_per_day = price_per_day
            if deposit:
                existing_item.deposit = deposit
            if price:
                existing_item.price = price
            if donor_name:
                existing_item.donor_name = donor_name
            if donor_contact:
                existing_item.donor_contact = donor_contact
            if uploaded_image:
                existing_item.image = uploaded_image
            existing_item.donation = donation or existing_item.donation
            existing_item.save()
            existing_item.update_availability()
            messages.success(
                request,
                f"Item '{existing_item.title}' already exists. Added +{total_quantity} quantity to the existing item record."
            )
        else:
            item = Inventory.objects.create(
                title=title,
                description=description,
                price_per_day=price_per_day,
                deposit=deposit,
                total_quantity=total_quantity,
                available_quantity=total_quantity,
                booked_quantity=0,
                available=available,
                next_available_date=next_available_date,
                image=uploaded_image,
                item_qty=item_qty,
                price=price,
                donation=donation,
                donor_name=donor_name,
                donor_contact=donor_contact,
            )
            item.update_availability()
            messages.success(request, f"New rental item '{item.title}' added successfully.")
        return redirect('inventory')

    return redirect('inventory')

@login_required
@user_passes_test(lambda u: user_has_permission(u, 'can_access_inventory'))
def delete_inventory_item(request, item_id):
    item = get_object_or_404(Inventory, id=item_id)
    item.delete()
    messages.success(request, f"Item '{item.title}' deleted successfully.")
    return redirect('inventory')

@login_required
@user_passes_test(lambda u: user_has_permission(u, 'can_access_inventory'))
def edit_inventory_item(request, item_id):
    item = get_object_or_404(Inventory, id=item_id)
    if request.method == 'POST':
        item.title = request.POST.get('title', '').strip()
        item.description = request.POST.get('description', '').strip()
        item.price_per_day = request.POST.get('price_per_day', 0)
        item.deposit = request.POST.get('deposit', 0)
        item.total_quantity = int(request.POST.get('total_quantity', 1) or 1)
        item.available = request.POST.get('available') == 'on'
        
        item.item_qty = int(request.POST.get('item_qty', 1) or 1)
        item.price = request.POST.get('price', 0)
        item.donation = request.POST.get('donation') == 'on'
        item.donor_name = request.POST.get('donor_name', '').strip()
        item.donor_contact = request.POST.get('donor_contact', '').strip()
        
        if request.FILES.get('image'):
            item.image = request.FILES.get('image')
            
        item.save()
        item.update_availability()
        messages.success(request, f"Item '{item.title}' updated successfully.")
        return redirect('inventory')
    
    return redirect('inventory')

def notify_request(request):
    if request.method == 'POST':
        item_id = request.POST.get('item_id')
        email = request.POST.get('email')
        mobile = request.POST.get('mobile')
        item = get_object_or_404(Inventory, id=item_id)

        NotifyRequest.objects.create(
            item=item,
            email=email,
            mobile=mobile
        )
        send_notify_emails(item, email, mobile)
        
        messages.success(request, "We'll notify you when this item becomes available!")
        return redirect('items')
    
    return redirect('items')

from django.db import transaction
@transaction.atomic
def add_to_cart(request, item_id):
    resp = ensure_module_access(request, 'can_access_inventory')
    if resp:
        return resp
    if not request.user.is_authenticated:
        messages.warning(request, "Please login to rent items")
        return redirect('signin')

    item = get_object_or_404(Inventory, id=item_id)

    if item.available_quantity <= 0:
        messages.error(request, "Item is out of stock.")
        return redirect('items')

    cart, _ = Cart.objects.get_or_create(user_id=request.user.id)

    cart_item, created = CartItem.objects.get_or_create(
        cart=cart,
        rental_item=item
    )
    if created:
        cart_item.quantity = 1
    else:
        if cart_item.quantity >= item.available_quantity:
            messages.error(request, f"Only {item.available_quantity} {item.title} item(s) are available.")
            return redirect('cart')
        cart_item.quantity += 1

    cart_item.save()
    messages.success(request, "Item added to cart.")
    return redirect('cart')

@login_required
def cart_view(request):
    resp = ensure_module_access(request, 'can_access_inventory')
    if resp:
        return resp
    cart, _ = Cart.objects.get_or_create(user_id=request.user.id)
    cart_items = cart.items.select_related("rental_item")

    if request.method == "POST":
        start_date = request.POST.get("start_date")
        end_date = request.POST.get("end_date")

        if not start_date or not end_date:
            messages.error(request, "Please select rental dates.")
            return redirect("cart")

        try:
            start_date_value = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_date_value = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            messages.error(request, "Please select valid rental dates.")
            return redirect("cart")

        if not user_has_any_permission(request.user):
            today = timezone.localdate()
            if start_date_value < today or end_date_value < today:
                messages.error(request, "Past dates are not allowed. Please select today or a future date.")
                return redirect("cart")

        if end_date_value < start_date_value:
            messages.error(request, "End date cannot be before start date.")
            return redirect("cart")

        for cart_item in cart_items:
            available_quantity = cart_item.rental_item.available_quantity
            if available_quantity <= 0:
                messages.error(request, f"{cart_item.rental_item.title} is out of stock.")
                return redirect("cart")
            if cart_item.quantity > available_quantity:
                messages.error(
                    request,
                    f"Only {available_quantity} {cart_item.rental_item.title} item(s) are available."
                )
                return redirect("cart")

        request.session["start_date"] = start_date
        request.session["end_date"] = end_date
        request.session["paid_amount"] = request.POST.get("paid_amount", "0")
        request.session["is_paid"] = request.POST.get("is_paid") == "on"
        if user_has_any_permission(request.user) and request.session.get("details_filled"):
            if cart_items:
                return redirect("select_delivery", pk=cart_items.first().rental_item.id)

        return redirect("userdetail")

    return render(request, "cart.html", {"cart_items": cart_items, "is_admin": user_has_any_permission(request.user)})

@login_required
def select_delivery(request, pk):
    item = get_object_or_404(Inventory, pk=pk)
    request.session['item_id'] = pk
    cart = Cart.objects.filter(user_id=request.user.id).first()
    has_cart_items = bool(cart and cart.items.exists())

    start_date = request.session.get("start_date")
    end_date = request.session.get("end_date")
    try:
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    except Exception:
        start_date = None
    try:
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
    except Exception:
        end_date = None

    if request.method == 'POST':
        delivery_option = request.POST.get('delivery_option')
        delivery_charge_str = request.POST.get('delivery_charge', '').strip()

        request.session['delivery_option'] = delivery_option

        rental = None if has_cart_items else History.objects.filter(rental_item=item, user_id=request.user.id).last()
        if rental:
            if delivery_option and delivery_option.lower() == "delivery":
                if delivery_charge_str:
                    try:
                        rental.delivery_charge = Decimal(re.sub(r"[^0-9.]", "", delivery_charge_str))
                    except Exception:
                        rental.delivery_charge = Decimal('500')
                else:
                    rental.delivery_charge = Decimal('500')
            else:
                rental.delivery_charge = Decimal('0')

            rental.delivery_option = delivery_option
            rental.save()

            request.session['rental_id'] = rental.id
            request.session['delivery_charge'] = str(rental.delivery_charge)
        else:
        
            if delivery_option and delivery_option.lower() == "delivery":
                if delivery_charge_str:
                    try:
                        delivery_charge_val = Decimal(re.sub(r"[^0-9.]", "", delivery_charge_str))
                    except Exception:
                        delivery_charge_val = Decimal('500')
                else:
                    delivery_charge_val = Decimal('500')
            else:
                delivery_charge_val = Decimal('0')

            request.session['delivery_option'] = delivery_option
            request.session['delivery_charge'] = str(delivery_charge_val)

        return redirect('paymentmethod')

    rental = None if has_cart_items else History.objects.filter(rental_item=item, user_id=request.user.id).last()

    cart_items = []
    total_rent = 0
    total_deposit = 0

    if rental and rental.order_id:
        related = History.objects.filter(order_id=rental.order_id, user_id=request.user.id).select_related('rental_item')
        for r in related:
            cart_items.append(r)
            total_rent += r.total_rent
            total_deposit += (r.deposit * r.quantity)

    elif rental:
        cart_items = [rental]
        total_rent = rental.total_rent
        total_deposit = rental.deposit * rental.quantity
    else:
        if cart:
            days = 1
            if start_date and end_date:
                try:
                    days = (end_date - start_date).days or 1
                except Exception:
                    days = 1

            for ci in cart.items.select_related('rental_item'):
                ci_total_rent = (ci.rental_item.price_per_day * days) * ci.quantity
                cart_items.append(ci)
                total_rent += ci_total_rent
                total_deposit += (ci.rental_item.deposit * ci.quantity)

    return render(request, 'select_delivery.html', {
        'item': item,
        'rental_id': pk,
        'cart_items': cart_items,
        'total_rent': total_rent,
        'total_deposit': total_deposit,
    })
from datetime import datetime
@login_required
@transaction.atomic
def paymentmethod(request):

    cart = Cart.objects.filter(user_id=request.user.id).first()
    renter_name = request.session.get("renter_name")
    patient_name = request.session.get("patient_name")
    phone = request.session.get("phone")
    address = request.session.get("address")
    id_proof_type = request.session.get("id_proof_type")
    id_proof_number = request.session.get("id_proof_number")
    start_date = request.session.get("start_date")
    end_date = request.session.get("end_date")

    try:
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    except Exception:
        start_date = None

    try:
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
    except Exception:
        end_date = None

    delivery_option = request.session.get('delivery_option')
    try:
        delivery_charge = Decimal(request.session.get('delivery_charge', '0'))
    except Exception:
        delivery_charge = Decimal('0')

    order_id = generate_sequential_order_id()

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method')
        created_rentals = []

        if not cart:
            messages.error(request, "Your cart is empty.")
            return redirect('bookingsammry')

        session_paid_amount_str = request.session.get("paid_amount", "0")
        try:
            session_paid_amount = Decimal(session_paid_amount_str or "0")
        except Exception:
            session_paid_amount = Decimal("0")
        session_is_paid = request.session.get("is_paid", False)

        renter_email = request.session.get("renter_email")
        if not renter_email and not user_has_any_permission(request.user):
            user_detail = UserDetail.objects.filter(user_id=request.user.id).first()
            if user_detail:
                renter_email = user_detail.email
        if not renter_email:
            renter_email = request.user.email

        for idx, ci in enumerate(cart.items.select_related("rental_item")):
            item = ci.rental_item
            if item.available_quantity < ci.quantity:
                messages.error(request, f"{item.title} is out of stock.")
                return redirect('cart')

            rental_paid = session_paid_amount if idx == 0 and session_is_paid else Decimal("0")
            rental_delivery_paid = session_is_paid if idx == 0 else False

            rental = History.objects.create(
                user_id=request.user.id,
                renter_name=renter_name,
                email=renter_email,
                patient_name=patient_name,
                phone=phone,
                address=address,
                rental_item=item,
                start_date=start_date,
                end_date=end_date,
                quantity=ci.quantity,
                deposit=item.deposit,
                payment_method=payment_method.lower(),
                order_id=order_id,
                id_proof_type=id_proof_type,
                id_proof_number=id_proof_number,
                delivery_option=delivery_option.lower() if delivery_option else None,
                delivery_charge=delivery_charge,
                is_today_reminder_sent=False,
                amount_paid=rental_paid,
                is_delivery_paid=rental_delivery_paid,
            )

            try:
                to_phone = rental.phone
                if not to_phone:
                    try:
                        ud = UserDetail.objects.filter(user_id=request.user.id).first()
                        to_phone = ud.phone if ud else None
                    except Exception:
                        to_phone = None

                if to_phone:
                    to_digits = re.sub(r"\D", "", str(to_phone))
                    customer_name = rental.renter_name or (request.user.get_full_name() or request.user.username)
                    msg = (
                        f"Hi {customer_name}, your rental request {rental.order_id} for '{item.title}' "
                        f"(Qty: {rental.quantity}) from {rental.start_date} to {rental.end_date} has been submitted. "
                        "We'll notify you when it's confirmed. - Kutch Yuvak Sangh"
                    )
                    send_whatsapp_message(to_digits, msg)
            except Exception as e:
                print(f"[whatsapp notify error] {e}")

            created_rentals.append(rental)

        print("HISTORY CREATED")

        try:
            send_notification(
                title="New Booking Created",
                message=(
                    f"New booking created for order {order_id} by {request.user.username}. "
                    f"{len(created_rentals)} item(s), total rental period {start_date} to {end_date}."
                ),
                notification_type='booking',
                link=f"/admin/app/history/?order_id={order_id}",
                order_id=order_id,
                rental=created_rentals[0]
            )
        except Exception as e:
            print(f"[notification booking error] {e}")

        cart.delete()

        # ================= PAYMENT =================
        if payment_method.lower() == 'online':
            return redirect('payment', rental_id=created_rentals[0].id)

        elif payment_method.lower() in ['cod', 'cash on delivery']:
            is_admin = user_has_any_permission(request.user)
            for rental in created_rentals:
                rental.payment_method = 'cod'
                rental.status = 'approved' if is_admin else 'pending'
                rental.save(update_fields=['payment_method', 'status'])

                Payment.objects.create(rental_request=rental, payment_status='PENDING', order_id=generate_order_id())

                if is_admin:
                    try:
                        rental.rental_item.update_availability()
                    except Exception:
                        pass

            if is_admin:
                messages.success(request, "Order placed and approved successfully!")
            else:
                messages.success(request, "Order placed successfully! Awaiting admin approval.")

            return redirect('success', rental_id=created_rentals[0].id)

        else:
            messages.error(request, "Please select a valid payment method.")

    return render(request, 'paymentmethod.html', {
        'delivery_charge': delivery_charge,
        'delivery_option': delivery_option
    })

from .models import Receipt
@csrf_exempt
def success(request, rental_id):
    if request.method != "GET":
        return HttpResponse("Method not allowed", status=405)

    razorpay_payment_id = request.GET.get("razorpay_payment_id")
    razorpay_signature = request.GET.get("razorpay_signature")
    donate_deposit = request.GET.get("donate_deposit") == "true"

    rental = get_object_or_404(History, id=rental_id)

    payment = Payment.objects.filter(rental_request=rental).order_by("-payment_date").first()

    if not payment:
        return HttpResponse("Payment record not found", status=404)

    related_rentals = History.objects.filter( user=rental.user,order_id=rental.order_id).select_related("rental_item")

    if rental.payment_method == "online":
        payment.payment_id = razorpay_payment_id
        payment.payment_status = "SUCCESS"
        payment.save(update_fields=["payment_id", "payment_status"])

        try:
            send_notification(
                title="Payment Successful",
                message=(
                    f"Payment recorded successfully for order {rental.order_id} by {rental.user.username}. "
                    f"Amount: ₹{payment.amount}."
                ),
                notification_type='payment',
                link=f"/admin/app/payment/{payment.id}/change/",
                order_id=rental.order_id,
                rental=rental
            )
        except Exception as e:
            print(f"[notification payment error] {e}")

        # ================== ADJUST STOCK NOW (ORDER CONFIRMED) ==================

        with transaction.atomic():
            to_process = related_rentals.exclude(status="approved")
            for rr in to_process:
                item = rr.rental_item
                rr.status = "approved"
                rr.save(update_fields=["status"]) 

                try:
                    item.update_availability()
                    item.save(update_fields=["available_quantity", "booked_quantity", "available", "next_available_date"])
                except Exception:
                    item.save()

    grouped_items = defaultdict(lambda: {
        "title": "",
        "quantity": 0,
        "price_per_day": 0,
        "deposit": 0,
        "rent": 0,
        "total": 0
    })

    for rr in related_rentals:
        key = rr.rental_item.id

        grouped_items[key]["title"] = rr.rental_item.title
        grouped_items[key]["price_per_day"] = rr.rental_item.price_per_day
        grouped_items[key]["deposit"] = rr.deposit
        grouped_items[key]["quantity"] += rr.quantity          
        grouped_items[key]["rent"] += rr.total_rent         

    # ================== CONVERT TO LIST ==================
    item_totals = []
    for item in grouped_items.values():
        item["total"] = item["rent"]
        item_totals.append(item)

    # ================== FINAL TOTALS ==================
    total_quantity = sum(item["quantity"] for item in item_totals)
    total_rent = sum(item["rent"] for item in item_totals)
    total_deposit = sum(item["deposit"] * item["quantity"] for item in item_totals)

    delivery_option = rental.delivery_option
    delivery_charge = 500 if delivery_option == "delivery" else 0

    if donate_deposit:
        total_amount = total_rent + delivery_charge
        for rr in related_rentals:
            rr.deposit_donated = True
            rr.save(update_fields=["deposit_donated"])
        payment.amount = total_amount
        payment.save(update_fields=["amount"])
    else:
        total_amount = total_rent + total_deposit + delivery_charge
    user_detail = UserDetail.objects.filter(user=rental.user).first()

    customer_name = rental.renter_name or (user_detail.patient_name if user_detail else (rental.user.get_full_name() or rental.user.username))
    customer_phone = rental.phone or (user_detail.phone if user_detail else None)
    customer_address = rental.address or (user_detail.address_line1 if user_detail else None)
    customer_patient_name = rental.patient_name or (user_detail.patient_name if user_detail else None)

    existing = rental.receipts.order_by('-created_at').first()
    if not existing:
        content_file = generate_receipt(rental)
        new_receipt = Receipt.objects.create(rental_request=rental, receipt_type="booking")
        new_receipt.file.save(receipt_filename(rental), content_file)
        new_receipt.save()

    for k in ("renter_name", "patient_name", "phone", "address", "id_proof_type", "id_proof_number", "start_date", "end_date", "details_filled", "delivery_option", "delivery_charge", "rental_id", "item_id", "paid_amount", "is_paid", "renter_email"):
        request.session.pop(k, None)

    return redirect('bookingsammry')


def about(request):
    return render(request, 'about.html')


def send_reminder_email(user, rental):
    order_id = getattr(rental, 'order_id', None) or 'N/A'
    subject = f"{order_id} Rental Reminder"
    recipient_email = user.email
    renter_name = rental.renter_name or (user.get_full_name() or user.username)
    user_detail = UserDetail.objects.filter(user=user).first() if user else None
    patient_name = rental.patient_name or (user_detail.patient_name if user_detail else None) or "N/A"

    related_rentals = History.objects.filter(order_id=rental.order_id).select_related('rental_item') if rental.order_id else [rental]
    items_str = ", ".join(f"{rr.rental_item.title} (Qty: {rr.quantity})" for rr in related_rentals if rr.rental_item)
    
    total_rent = sum((rr.total_rent for rr in related_rentals), Decimal("0"))
    total_deposit = sum((rr.deposit * rr.quantity for rr in related_rentals), Decimal("0"))

    body_lines = [
        f"* Renter Name: {renter_name}",
        f"* Patient Name: {patient_name}",
        f"* Item(s): {items_str}",
        f"* From Date: {rental.start_date}",
        f"* To Date: {rental.billing_end_date or rental.end_date}",
    ]
    if total_rent > 0:
        body_lines.append(f"* Rent Amount: Rs. {total_rent:.2f}")
    if total_deposit > 0:
        body_lines.append(f"* Deposit: Rs. {total_deposit:.2f}")

    message = (
        f"{subject}\n\n"
        f"Dear {renter_name},\n\n"
        f"This is a reminder that your rental order {order_id} is ending soon.\n\n" +
        "\n".join(body_lines) +
        "\n\nFor any further assistance call 9867348169 / 9820247550 or login to sickbed.itegoss.in\n\n"
        "Thank you"
    )

    from django.core.mail import EmailMessage
    email_msg = EmailMessage(
        subject=subject,
        body=message,
        from_email=getattr(settings, 'EMAIL_HOST_USER', settings.DEFAULT_FROM_EMAIL),
        to=[recipient_email],
    )
    try:
        pdf_file = generate_receipt(rental)
        pdf_content = pdf_file.read()
        pdf_name = receipt_filename(rental)
        email_msg.attach(pdf_name, pdf_content, "application/pdf")
    except Exception as ex:
        print(f"[send_reminder_email pdf attachment error] {ex}")

    try:
        email_msg.send(fail_silently=False)
    except Exception as e:
        print(f"[send_reminder_email error] {e}")

    rental.is_reminder_sent = True
    rental.save()


def send_today_reminder_email(user, rental):
    order_id = getattr(rental, 'order_id', None) or 'N/A'
    subject = f"{order_id} Rental Reminder"
    recipient_email = user.email
    renter_name = rental.renter_name or (user.get_full_name() or user.username)
    user_detail = UserDetail.objects.filter(user=user).first() if user else None
    patient_name = rental.patient_name or (user_detail.patient_name if user_detail else None) or "N/A"

    related_rentals = History.objects.filter(order_id=rental.order_id).select_related('rental_item') if rental.order_id else [rental]
    items_str = ", ".join(f"{rr.rental_item.title} (Qty: {rr.quantity})" for rr in related_rentals if rr.rental_item)
    
    total_rent = sum((rr.total_rent for rr in related_rentals), Decimal("0"))
    total_deposit = sum((rr.deposit * rr.quantity for rr in related_rentals), Decimal("0"))

    body_lines = [
        f"* Renter Name: {renter_name}",
        f"* Patient Name: {patient_name}",
        f"* Item(s): {items_str}",
        f"* From Date: {rental.start_date}",
        f"* To Date: {rental.billing_end_date or rental.end_date}",
    ]
    if total_rent > 0:
        body_lines.append(f"* Rent Amount: Rs. {total_rent:.2f}")
    if total_deposit > 0:
        body_lines.append(f"* Deposit: Rs. {total_deposit:.2f}")

    message = (
        f"{subject}\n\n"
        f"Dear {renter_name},\n\n"
        f"This is a reminder that today is the return date for your rental order {order_id}.\n\n" +
        "\n".join(body_lines) +
        "\n\nFor any further assistance call 9867348169 / 9820247550 or login to sickbed.itegoss.in\n\n"
        "Thank you"
    )

    from django.core.mail import EmailMessage
    email_msg = EmailMessage(
        subject=subject,
        body=message,
        from_email=getattr(settings, 'EMAIL_HOST_USER', settings.DEFAULT_FROM_EMAIL),
        to=[recipient_email],
    )
    try:
        pdf_file = generate_receipt(rental)
        pdf_content = pdf_file.read()
        pdf_name = receipt_filename(rental)
        email_msg.attach(pdf_name, pdf_content, "application/pdf")
    except Exception as ex:
        print(f"[send_today_reminder_email pdf attachment error] {ex}")

    try:
        email_msg.send(fail_silently=False)
    except Exception as e:
        print(f"[send_today_reminder_email error] {e}")


def send_overdue_emails(user, rental):
    send_overdue_email(user, rental)
    rental.is_overdue_email_sent = True
    rental.save()


def send_notify_emails(item, user_email, user_mobile):
    from django.core.mail import send_mail
    from django.conf import settings
    
    user_subject = f'Notification Request Received - {item.title}'
    item_lines = [f"* Item: {item.title}"]
    if item.price_per_day and item.price_per_day > 0:
        item_lines.append(f"* Price per day: Rs. {item.price_per_day:.2f}")
    if item.deposit and item.deposit > 0:
        item_lines.append(f"* Deposit: Rs. {item.deposit:.2f}")

    user_message = (
        f"{user_subject}\n\n"
        "Thank you for your interest. We have received your notification request and will inform you as soon as this item becomes available.\n\n" +
        "\n".join(item_lines) +
        "\n\nFor any further assistance call 9867348169 / 9820247550 or login to sickbed.itegoss.in\n\n"
        "Thank you"
    )
    
    admin_subject = f'New Notify Request - {item.title}'
    admin_message = (
        f"{admin_subject}\n\n"
        f"* Item: {item.title}\n"
        f"* User Email: {user_email or 'N/A'}\n"
        f"* User Mobile: {user_mobile or 'N/A'}\n\n"
        "Please restock this item soon.\n\n"
        "Thank you"
    )
    
    try:
        send_mail(
            user_subject,
            user_message,
            getattr(settings, 'EMAIL_HOST_USER', settings.DEFAULT_FROM_EMAIL),
            [user_email],
            fail_silently=False
        )
    except Exception as e:
        print(f"❌ Failed to send user email: {e}")
    
    try:
        send_mail(
            admin_subject,
            admin_message,
            getattr(settings, 'EMAIL_HOST_USER', settings.DEFAULT_FROM_EMAIL),
            [settings.ADMIN_EMAIL],
            fail_silently=False
        )
    except Exception as e:
        print(f"❌ Failed to send admin email: {e}")


def payment(request, rental_id):
    rental = get_object_or_404(History, id=rental_id)
    user = request.user

    if rental.order_id:
        related_rentals = History.objects.filter(order_id=rental.order_id, user=rental.user).select_related('rental_item')
    else:
        related_rentals = [rental]

    from decimal import Decimal as _Decimal
    total_amount = sum(((_Decimal(rr.total_rent) if rr.total_rent is not None else _Decimal('0')) for rr in related_rentals), _Decimal('0'))
    total_deposit = sum(((_Decimal(rr.deposit) * _Decimal(rr.quantity) if rr.deposit is not None else _Decimal('0')) for rr in related_rentals), _Decimal('0'))

    if rental.delivery_charge:
        try:
            total_amount += _Decimal(str(rental.delivery_charge))
        except Exception:
            total_amount += _Decimal('0')

    total_amount += total_deposit

    razorpay_amount = int((total_amount * _Decimal('100')))

    client = razorpay.Client(auth=("rzp_test_wH0ggQnd7iT3nB", "eZseshY3oSsz2fcHZkTiSlCm"))

    data = {
        "amount": razorpay_amount,
        "currency": "INR",
        "receipt": f"rental_rcpt_{rental.id}",
        "payment_capture": 1
    }

    razorpay_order = client.order.create(data=data)

    payment_obj = Payment.objects.create(
        rental_request=rental,
        amount=total_amount,
        payment_status="Pending"
    )

    payment_obj.order_id = generate_order_id()
    payment_obj.save()

    try:
        rent_days = (rental.end_date - rental.start_date).days
    except Exception:
        rent_days = 1

    context = {
        "user": user,
        "items": related_rentals,
        "rent_days": rent_days,
        "total_amount": total_amount,
        "total_deposit": total_deposit,
        "razorpay_amount": razorpay_amount,
        "razorpay_order_id": razorpay_order["id"],
        "payment": payment_obj,
        "custom_order_id": payment_obj.order_id,
        "rental_id": rental.id,
        "razorpay_key": "rzp_test_wH0ggQnd7iT3nB",
    }
    return render(request, "payment.html", context)


def generate_order_id():
    today = timezone.now().strftime("%Y%m") 
    prefix = f"ORD{today}"

    last_order = Payment.objects.filter(order_id__startswith=prefix).order_by("order_id").last()

    if last_order and last_order.order_id:
        match = re.search(r"(\d{3})$", last_order.order_id)
        if match:
            last_num = int(match.group(1)) + 1
            new_num = str(last_num).zfill(3)
        else:
            new_num = "001"
    else:
        new_num = "001"

    return f"{prefix}{new_num}"


@login_required
@user_passes_test(lambda u: user_has_permission(u, 'can_access_inventory'))
def approve_order(request, order_id):
    orders = History.objects.filter(order_id=order_id)
    if not orders.exists():
        raise Http404("Order not found")
    
    orders.update(status="approved")
    for item in Inventory.objects.filter(rentalrequest_set__order_id=order_id).distinct():
        item.update_availability()
    
    first_order = orders.first()
    if not first_order.receipts.exists():
        content_file = generate_receipt(first_order)
        new_receipt = Receipt.objects.create(rental_request=first_order, receipt_type='booking')
        new_receipt.file.save(receipt_filename(first_order), content_file)
        new_receipt.save()

    try:
        send_notification(
            title=f"Order Approved: {order_id}",
            message=f"Order {order_id} has been approved by admin {request.user.username}.",
            notification_type='booking',
            link=f"/admin/app/history/?order_id={order_id}",
            order_id=order_id,
            rental=first_order
        )
    except Exception as e:
        print(f"[notification error] {e}")

    messages.success(request, f"Order {order_id} approved successfully.")
    return redirect("bookingsammry")

@login_required
@user_passes_test(lambda u: user_has_permission(u, 'can_access_inventory'))
@transaction.atomic
def approve_return_order(request, order_id):
    rentals = History.objects.select_for_update().filter(order_id=order_id, is_returned=False)
    if not rentals.exists():
        messages.error(request, "No return request found for this order.")
        return redirect("bookingsammry")
    
    for index, rr in enumerate(rentals):
        rr.is_returned = True
        rr.is_return_requested = False
        rr.status = "approved"
        rr.actual_return_date = timezone.localdate()
        rr.save()
        try:
            rr.rental_item.update_availability()
        except Exception:
            try:
                rr.rental_item.save()
            except Exception:
                pass
    
    try:
        send_notification(
            title=f"Return Approved for {order_id}",
            message=f"Admin {request.user.username} approved the return for order {order_id}.",
            notification_type='return',
            link=f"/admin/app/history/?order_id={order_id}",
            order_id=order_id,
            rental=rentals[0]
        )
    except Exception as e:
        print(f"[notification error] {e}")

    messages.success(request, "Return approved successfully.")
    return redirect("bookingsammry")

@login_required
@user_passes_test(lambda u: user_has_permission(u, 'can_access_inventory'))
def download_rental_report(request):
    if request.method == 'POST':
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        
        if start_date_str and end_date_str:
            from datetime import datetime
            from .utils import generate_rental_report_pdf
            
            start = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            queryset = History.objects.filter(
                start_date__gte=start,
                start_date__lte=end
            ).select_related('user', 'rental_item')
            
            return generate_rental_report_pdf(queryset, start, end)
            
    messages.error(request, "Invalid report parameters.")
    return redirect("bookingsammry")

def terms(request):
    return render(request, 'terms.html')

def services(request):
    active_services = SupportService.objects.filter(is_active=True).prefetch_related('contacts')
    return render(request, 'services.html', {'services': active_services})

from django.utils import timezone
@login_required
@transaction.atomic
def userdetail(request):
    is_admin = user_has_any_permission(request.user)
    cart = Cart.objects.filter(user_id=request.user.id).first()
    cart_items = cart.items.select_related("rental_item") if cart else []
    customers = []

    if is_admin and request.session.get("details_filled"):
        if cart_items:
            return redirect("select_delivery", pk=cart_items.first().rental_item.id)
        else:
            return redirect("items")

    if request.method == "POST":
        id_proof_type = request.POST.get("id_proof_type", "").strip()
        id_proof_number = request.POST.get("id_proof_number", "").strip()

        if is_admin and not request.session.get("details_filled"):
            request.session["renter_name"] = request.POST.get("name") or request.user.username
            request.session["renter_email"] = request.POST.get("email", "").strip()
            request.session["patient_name"] = request.POST.get("patient_name")
            request.session["phone"] = request.POST.get("phone")
            request.session["address"] = request.POST.get("address")
            request.session["pincode"] = request.POST.get("pincode")
            request.session["start_date"] = request.POST.get("start_date")
            request.session["end_date"] = request.POST.get("end_date")
            request.session["id_proof_type"] = id_proof_type
            request.session["id_proof_number"] = id_proof_number
            request.session["details_filled"] = True

            if cart_items:
                return redirect("select_delivery", pk=cart_items.first().rental_item.id)
            return redirect("items")

        if not cart_items:
            messages.error(request, "Your cart is empty.")
            return redirect("cart")

        for cart_item in cart_items:
            available_quantity = cart_item.rental_item.available_quantity
            if available_quantity <= 0:
                messages.error(request, f"{cart_item.rental_item.title} is out of stock.")
                return redirect("cart")
            if cart_item.quantity > available_quantity:
                messages.error(
                    request,
                    f"Only {available_quantity} {cart_item.rental_item.title} item(s) are available."
                )
                return redirect("cart")

        phone = request.POST.get("phone", "").strip()
        address = request.POST.get("address", "").strip()
        pincode = request.POST.get("pincode", "").strip()
        email = request.POST.get("email", "").strip()
        patient_name = request.POST.get("patient_name", "").strip()

        start_date_str = request.POST.get("start_date") or request.session.get("start_date")
        end_date_str = request.POST.get("end_date") or request.session.get("end_date")
        first_cart_item = cart_items.first()
        rental_item_id = first_cart_item.rental_item.id
        saved_address = request.session.get("address") or address
        saved_pincode = request.session.get("pincode") or pincode
        history_address = saved_address
        if saved_pincode and saved_pincode not in history_address:
            history_address = f"{history_address}, {saved_pincode}"

        with transaction.atomic():
            user_detail = None
            if not is_admin:
                user_detail, _ = UserDetail.objects.update_or_create(
                    user_id=request.user.id,
                    defaults={
                        "phone": phone,
                        "id_proof_type": id_proof_type,
                        "id_proof_number": id_proof_number,
                        "address_line1": address,
                        "pincode": pincode,
                        "email": email or None,
                        "patient_name": patient_name,
                    }
                )

            # Store details in session for the next steps
            request.session["renter_name"] = request.POST.get("name") or request.user.get_full_name() or request.user.username
            request.session["renter_email"] = email or request.user.email
            request.session["patient_name"] = patient_name
            request.session["phone"] = phone
            request.session["address"] = history_address
            request.session["pincode"] = pincode
            request.session["start_date"] = start_date_str
            request.session["end_date"] = end_date_str
            request.session["id_proof_type"] = id_proof_type
            request.session["id_proof_number"] = id_proof_number
            request.session["details_filled"] = True

        return redirect("select_delivery", pk=rental_item_id)

    if not cart_items:
        if is_admin and not request.session.get("details_filled"):
            customers = Customer.objects.all().order_by('-created_at')
        else:
            messages.error(request, "Your cart is empty.")
            return redirect("cart")

    context = {
        "items": [],
        "rental_days": 0,
        "total_rent": 0,
        "total_deposit": 0,
        "total_amount": 0,
        "is_admin": is_admin
    }

    if is_admin and not request.session.get("details_filled"):
        context["customers"] = customers

    return render(request, "userdetail.html", context)

def update_cart_item(request, item_id):
    if request.method == 'POST':
        action = request.POST.get('action')
        cart_item = get_object_or_404(CartItem, id=item_id, cart__user_id=request.user.id)

        if action == 'increment':
            available_quantity = cart_item.rental_item.available_quantity
            if available_quantity <= 0:
                return JsonResponse({
                    'success': False,
                    'quantity': cart_item.quantity,
                    'message': f"{cart_item.rental_item.title} is out of stock."
                }, status=400)
            if cart_item.quantity >= available_quantity:
                return JsonResponse({
                    'success': False,
                    'quantity': cart_item.quantity,
                    'message': f"Only {available_quantity} item(s) are available."
                }, status=400)
            cart_item.quantity += 1
            cart_item.save()
        elif action == 'decrement':
            if cart_item.quantity > 1:
                cart_item.quantity -= 1
                cart_item.save()
            else:
                cart_item.delete()
        return JsonResponse({'success': True, 'quantity': cart_item.quantity if cart_item.id else 0})

def remove_cart_item(request, item_id):
    if request.method == 'POST':
        cart_item = get_object_or_404(CartItem, id=item_id, cart__user_id=request.user.id)
        cart_item.delete()
        return JsonResponse({'success': True})

from collections import defaultdict

@login_required
def bookingsammry(request):
    rental_requests = History.objects.select_related('user', 'user__userdetail', 'rental_item').order_by('-created_at')
    if not user_has_any_permission(request.user):
        rental_requests = rental_requests.filter(user_id=request.user.id)

    paginator = Paginator(rental_requests, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    grouped = defaultdict(list)

    for rr in page_obj:
        key = rr.order_id or f"SINGLE-{rr.id}"
        rr.display_order_id = key
        rr.display_item_title = rr.rental_item.title
        grouped[key].append(rr)

    booking_summaries = []

    for order_id, items in grouped.items():
        total_deposit = sum((item.deposit * item.quantity for item in items), Decimal("0"))

        booking_summaries.append({
            "order_id": order_id,
            "date": items[0].start_date,
            "items": items,
            "total_deposit": total_deposit,
            "customer": items[0].user if user_has_any_permission(request.user) else None,
        })

    return render(
        request,
        "bookingsammry.html",
        {
             "booking_summaries": booking_summaries,
            "page_obj": page_obj,
        },
    )


@login_required
def mark_returned(request, rental_id, item_id):
    rr = get_object_or_404(History, id=rental_id, rental_item_id=item_id, user_id=request.user.id)
    
    if not rr.is_return_requested:
        rr.is_return_requested = True
        rr.save()

        admin_email = getattr(settings, 'ADMIN_EMAIL', None)
        subject = f'Return Request from {request.user.username}'
        print(f"[email suppressed] To: {admin_email} Subject: {subject} User: {request.user.email} Item: {rr.rental_item}")

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect('bookingsammry')

@login_required
def view_rental(request, rental_id):
    rentals = History.objects.all()
    if not user_has_any_permission(request.user):
        rentals = rentals.filter(user_id=request.user.id)

    rental = get_object_or_404(rentals, id=rental_id)
    related_rentals = rentals.filter(order_id=rental.order_id).select_related("rental_item")

    breakdown = build_booking_receipt_breakdown(rental, related_rentals)
    payment = Payment.objects.filter(rental_request=rental).order_by("-payment_date").first()

    user_detail = UserDetail.objects.filter(user=rental.user).first()
    delivery_option = rental.delivery_option
    delivery_charge = rental.delivery_charge if delivery_option == "delivery" else 0

    customer_name = rental.renter_name or (user_detail.patient_name if user_detail else (rental.user.get_full_name() or rental.user.username))
    customer_phone = rental.phone or (user_detail.phone if user_detail else None)
    customer_address = rental.address or (user_detail.address_line1 if user_detail else None)
    customer_patient_name = rental.patient_name or (user_detail.patient_name if user_detail else None)

    context = {
        "order_id": rental.order_id,
        "date": breakdown["original_booking_date"],
        "rental": rental,
        "payment": payment,
        "patient_name": customer_patient_name,
        "user_detail": user_detail,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "customer_address": customer_address,
        "rent_start_date": breakdown["original_start_date"],
        "total_days": breakdown["total_rent_days"],
        "total_rent_days": breakdown["total_rent_days"],
        "effective_return_date": breakdown["effective_return_date"],
        "return_date": breakdown["effective_return_date"],
        "item_totals": breakdown["original_item_totals"],
        "total_quantity": breakdown["total_quantity"],
        "total_rent": breakdown["original_total_rent"],
        "total_deposit": breakdown["original_total_deposit"],
        "delivery_charge": delivery_charge,
        "delivery_option": delivery_option,
        "total_amount": breakdown["final_total_amount"],
        "payment_mode": "Online Payment",
        "original_booking_date": breakdown["original_booking_date"],
        "original_start_date": breakdown["original_start_date"],
        "original_return_date": breakdown["original_return_date"],
        "original_days": breakdown["original_days"],
        "original_total_amount": breakdown["original_total_amount"],
        "extension_history": breakdown["extension_history"],
        "extension_total": breakdown["extension_total"],
        "final_total_amount": breakdown["final_total_amount"],
        "amount_paid": breakdown["amount_paid"],
        "amount_remaining": breakdown["amount_remaining"],
        "delivery_paid": breakdown["delivery_paid"],
    }

    return render(request, "success.html", context)

@login_required
@transaction.atomic

def extend_return_date(request, order_id):
    rentals = (
        History.objects.select_for_update()
        .filter(order_id=order_id, is_returned=False)
        .select_related("rental_item")
    )
    if not user_has_any_permission(request.user):
        rentals = rentals.filter(user_id=request.user.id)

    if not rentals.exists():
        messages.error(request, "Order not found or already returned.")
        return redirect("bookingsammry")

    rental_rows = list(rentals)
    current_end_date = rental_rows[0].billing_end_date
    min_extend_date = current_end_date + timedelta(days=1)

    if request.method == "POST":
        extended_date_str = request.POST.get("extended_end_date")
        if not extended_date_str:
            messages.error(request, "Please select a new return date.")
            return redirect("extend_return_date", order_id=order_id)

        try:
            new_date = datetime.strptime(extended_date_str, "%Y-%m-%d").date()
        except ValueError:
            messages.error(request, "Invalid date format.")
            return redirect("extend_return_date", order_id=order_id)

        if new_date <= current_end_date:
            messages.error(request, f"Please select a date after {current_end_date.strftime('%Y-%m-%d')}.")
            return redirect("extend_return_date", order_id=order_id)

        last_extension_no = (
            BookingExtension.objects
            .filter(rental_request__in=rental_rows)
            .order_by("-extension_no")
            .values_list("extension_no", flat=True)
            .first()
        ) or 0
        extension_no = last_extension_no + 1
        extra_days = (new_date - current_end_date).days

        for rr in rental_rows:
            additional_deposit = Decimal("0")
            additional_rent = rr.rental_item.price_per_day * rr.quantity * extra_days
            BookingExtension.objects.create(
                rental_request=rr,
                extension_no=extension_no,
                previous_return_date=current_end_date,
                new_return_date=new_date,
                extra_days=extra_days,
                quantity=rr.quantity,
                rent_per_day=rr.rental_item.price_per_day,
                additional_rent=additional_rent,
                additional_deposit=additional_deposit,
                extension_total=additional_rent + additional_deposit,
            )
            rr.extended_end_date = new_date
            rr.save()

        # Regenerate receipt PDF for the rental request
        first_rental = rental_rows[0]
        first_rental.receipts.filter(receipt_type='booking').delete()
        content_file = generate_receipt(first_rental)
        new_receipt = Receipt.objects.create(rental_request=first_rental, receipt_type='booking')
        new_receipt.file.save(receipt_filename(first_rental), content_file)
        new_receipt.save()

        try:
            send_notification(
                title=f"Return Date Extended for {order_id}",
                message=(
                    f"User {request.user.username} extended return date for order {order_id} "
                    f"to {new_date.strftime('%Y-%m-%d')}."
                ),
                notification_type='return',
                link=f"/admin/app/history/?order_id={order_id}",
                order_id=order_id,
                rental=first_rental
            )
        except Exception as e:
            print(f"[notification extend return error] {e}")

        messages.success(request, f"Return date extended to {new_date.strftime('%d %b %Y')}. Charges have been updated.")
        return redirect("bookingsammry")

    item_totals = []
    for rr in rental_rows:
        item_totals.append({
            "title": rr.rental_item.title,
            "quantity": rr.quantity,
            "price_per_day": rr.rental_item.price_per_day,
            "days": rr.rental_days,
            "deposit": rr.deposit * rr.quantity,
            "total": rr.total_rent,
        })

    context = {
        "order_id": order_id,
        "current_end_date": current_end_date,
        "min_extend_date": min_extend_date,
        "item_totals": item_totals,
        "total_rent": sum(item["total"] for item in item_totals),
        "total_deposit": sum(item["deposit"] for item in item_totals),
        "delivery_charge": rental_rows[0].delivery_charge,
        "order": rental_rows[0],
    }
    return render(request, "extend_return.html", context)

@login_required
@transaction.atomic

def return_order(request, order_id):
    donate_deposit = request.GET.get("donate_deposit") == "true"
    return_delivery = request.GET.get("return_delivery") == "true"
    return_delivery_charge = Decimal("0")
    if return_delivery:
        try:
            return_delivery_charge = Decimal(request.GET.get("return_delivery_charge", "500"))
        except Exception:
            return_delivery_charge = Decimal("500")
    donation_amount = Decimal("0")
    donation_comment = request.GET.get("donation_comment", "").strip()

    rentals = (
        History.objects
        .select_for_update()
        .filter(
            order_id=order_id,
            is_returned=False
        )
        .select_related("rental_item")
    )
    if not user_has_any_permission(request.user):
        rentals = rentals.filter(user_id=request.user.id)

    if not rentals.exists():
        messages.info(request, "Return already requested or completed.")
        return redirect("bookingsammry")

    rental_rows = list(rentals)

    def format_return_item_details(rows):
        details = ["Rental Details:"]
        for rr in rows:
            details.extend([
                f"Item Name: {rr.rental_item.title}",
                f"Item Quantity: {rr.quantity}",
                f"Renter Name: {rr.renter_name or rr.user.username}",
                f"Start Date: {rr.start_date}",
                f"End Date: {rr.billing_end_date}",
                f"Amount: Rs. {rr.total_rent}",
                "",
            ])
        return "\n".join(details).strip()

    item_details = format_return_item_details(rental_rows)
    item_count = len(rental_rows)
    total_deposit = sum((rr.deposit * rr.quantity for rr in rental_rows), Decimal("0"))
    if donate_deposit:
        try:
            donation_amount = Decimal(request.GET.get("donation_amount", "0"))
        except Exception:
            donation_amount = Decimal("0")

        if donation_amount <= 0:
            messages.error(request, "Please enter a valid donation amount.")
            return redirect("bookingsammry")

        if donation_amount > total_deposit:
            messages.error(request, f"Donation amount cannot be more than the total deposit of ₹{total_deposit}.")
            return redirect("bookingsammry")

    if user_has_any_permission(request.user):
        for index, rr in enumerate(rental_rows):
            rr.is_return_requested = False
            rr.is_returned = True
            rr.status = "approved"
            rr.actual_return_date = timezone.localdate()
            rr.deposit_donated = donate_deposit
            rr.donation_amount = donation_amount if index == 0 else Decimal("0")
            rr.donation_comment = donation_comment if index == 0 else ""
            if return_delivery:
                rr.return_pickup_charge = return_delivery_charge if index == 0 else Decimal("0")
            else:
                rr.return_pickup_charge = Decimal("0")
            update_fields = [
                "is_return_requested",
                "is_returned",
                "status",
                "actual_return_date",
                "deposit_donated",
                "donation_amount",
                "donation_comment",
                "return_pickup_charge",
            ]
            rr.save(update_fields=update_fields)
            try:
                rr.rental_item.update_availability()
            except Exception:
                try:
                    rr.rental_item.save()
                except Exception:
                    pass

        try:
            send_notification(
                title=f"Order Returned for {order_id}",
                message=(
                    f"Admin {request.user.username} marked order {order_id} as returned. "
                    f"{item_count} item(s) returned.\n\n"
                    f"{item_details}"
                ),
                notification_type='return',
                link=f"/admin/app/history/?order_id={order_id}",
                order_id=order_id,
                rental=rental_rows[0]
            )
        except Exception as e:
            print(f"[notification direct return error] {e}")

        messages.success(request, "Order marked as returned successfully.")
        return redirect("bookingsammry")

    for index, rr in enumerate(rental_rows):
        rr.is_return_requested = True
        rr.status = "pending"      
        rr.deposit_donated = donate_deposit
        rr.donation_amount = donation_amount if index == 0 else Decimal("0")
        rr.donation_comment = donation_comment if index == 0 else ""
        if return_delivery:
            rr.return_pickup_charge = return_delivery_charge if index == 0 else Decimal("0")
        else:
            rr.return_pickup_charge = Decimal("0")
        rr.save(update_fields=[
            "is_return_requested",
            "status",
            "deposit_donated",
            "donation_amount",
            "donation_comment",
            "return_pickup_charge",
        ])

    try:
        send_notification(
            title=f"Return Request Submitted for {order_id}",
            message=(
                f"User {request.user.username} requested return for order {order_id}. "
                f"{item_count} item(s) are awaiting approval.\n\n"
                f"{item_details}"
            ),
            notification_type='return',
            link=f"/admin/app/history/?order_id={order_id}",
            order_id=order_id,
            rental=rental_rows[0]
        )
    except Exception as e:
        print(f"[notification return request error] {e}")

    if donate_deposit:
        messages.success(
            request, "Return request sent successfully. Deposit donation selected. Waiting for admin approval.")
    else:
        messages.success( request,"Return request sent successfully. Waiting for admin approval.")
    return redirect("bookingsammry")

@login_required
def cancel_order(request, order_id):
    rentals = History.objects.filter(
        order_id=order_id,
        is_returned=False
    ).exclude(status='cancelled')

    if not user_has_any_permission(request.user):
        rentals = rentals.filter(user_id=request.user.id)

    if not rentals.exists():
        messages.error(request, "Order not found or cannot be cancelled.")
        return redirect('bookingsammry')

    for rr in rentals:
        rr.status = 'cancelled'
        rr.is_return_requested = False
        rr.save(update_fields=['status', 'is_return_requested'])
        try:
            rr.rental_item.update_availability()
        except Exception:
            try:
                rr.rental_item.save()
            except Exception:
                pass

    try:
        send_notification(
            title="Booking Cancelled",
            message=(
                f"Order {order_id} was cancelled by {request.user.username}. "
                f"{rentals.count()} item(s) affected."
            ),
            notification_type='cancelled',
            link=f"/admin/app/history/?order_id={order_id}",
            order_id=order_id,
            rental=rentals.first()
        )
    except Exception as e:
        print(f"[notification cancel error] {e}")

    messages.success(request, "Booking cancelled successfully.")
    return redirect('bookingsammry')

@login_required
def admin_notifications(request):
    from django.db.models import Q
    from .models import Notification
    try:
        user = request.user
        if user.is_superuser or user.is_staff:
            filter_q = Q(recipient=user) | Q(recipient__isnull=True)
        else:
            filter_q = Q(recipient=user)

        notifications = Notification.objects.filter(filter_q).order_by('-created_at')
        unread_count = notifications.filter(is_read=False).count()
    except ProgrammingError:
        notifications = Notification.objects.none()
        unread_count = 0
    return render(request, 'notifications/list.html', {
        'notifications': notifications,
        'unread_count': unread_count,
    })

@login_required(login_url='signin')
def users(request):
    if not user_has_permission(request.user, 'can_manage_users'):
        return redirect('index')

    q = request.GET.get('q', '').strip()
    users = User.objects.all().order_by('username').prefetch_related('role_assignments__role')
    if q:
        users = users.filter(
            Q(username__icontains=q) |
            Q(email__icontains=q)
        )

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'assign_role':
            user_id = request.POST.get('user_id')
            role_id = request.POST.get('role_id')
            if not user_id:
                messages.error(request, "No user specified for role assignment.")
            elif not role_id:
                messages.error(request, "Please select a role to assign.")
            else:
                try:
                    user_id_int = int(user_id)
                    role_id_int = int(role_id)
                except Exception:
                    messages.error(request, "Invalid user or role identifier.")
                else:
                    target_user = User.objects.filter(id=user_id_int).first()
                    target_role = Role.objects.filter(id=role_id_int).first()
                    if not target_user or not target_role:
                        messages.error(request, "Invalid user or role selected.")
                    else:
                        from django.db import transaction
                        try:
                            with transaction.atomic():
                                assignment, created = UserRole.objects.get_or_create(user=target_user, role=target_role)
                                if created:
                                    messages.success(request, f"Role '{target_role.name}' assigned to {target_user.username}.")
                                else:
                                    messages.info(request, f"{target_user.username} already has the role '{target_role.name}'.")
                        except Exception as e:
                            print(f"[assign_role error] user_id={user_id_int} role_id={role_id_int} error={e}")
                            messages.error(request, "Failed to assign role due to a server error.")
        elif action == 'remove_role':
            assignment_id = request.POST.get('assignment_id')
            assignment = UserRole.objects.filter(id=assignment_id).first()
            if assignment:
                assignment.delete()
                messages.success(request, "Role removed successfully.")
            else:
                messages.error(request, "Role assignment not found.")
        return redirect('users')

    page_size = request.GET.get('page_size', '10')
    try:
        page_size_int = int(page_size)
        if page_size_int <= 0:
            page_size_int = 10
    except ValueError:
        page_size_int = 10
    page_size = str(page_size_int)

    paginator = Paginator(users, page_size_int)
    page_obj = paginator.get_page(request.GET.get('page'))
    roles = Role.objects.all().order_by('name')

    return render(request, 'users.html', {
        'page_obj': page_obj,
        'search_query': q,
        'page_size': page_size,
        'roles': roles,
    })

@login_required(login_url='signin')
def roles(request):
    if not user_has_permission(request.user, 'can_manage_roles'):
        return redirect('index')

    q = request.GET.get('q', '').strip()
    page_size = request.GET.get('page_size', '10')
    try:
        page_size_int = int(page_size)
        if page_size_int <= 0:
            page_size_int = 10
    except ValueError:
        page_size_int = 10
    page_size = str(page_size_int)

    roles = Role.objects.all().order_by('name')
    edit_role = None
    edit_role_id = request.GET.get('edit')
    if edit_role_id:
        edit_role = Role.objects.filter(id=edit_role_id).first()

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save_role':
            role_id = request.POST.get('role_id')
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()
            permissions = request.POST.getlist('permission')

            if not name:
                messages.error(request, 'Please provide a role name.')
                return redirect('roles')

            if role_id:
                role = Role.objects.filter(id=role_id).first()
                if not role:
                    messages.error(request, 'Role not found.')
                    return redirect('roles')
            else:
                role = Role()

            role.name = name
            role.description = description
            role.can_access_inventory = 'can_access_inventory' in permissions
            role.can_manage_blood_requests = 'can_manage_blood_requests' in permissions
            role.can_manage_camps = 'can_manage_camps' in permissions
            role.can_manage_donors = 'can_manage_donors' in permissions
            role.can_manage_volunteers = 'can_manage_volunteers' in permissions
            role.can_manage_services = 'can_manage_services' in permissions
            role.can_manage_users = 'can_manage_users' in permissions
            role.can_manage_roles = 'can_manage_roles' in permissions

            try:
                role.save()
                messages.success(request, f"Role '{role.name}' saved successfully.")
            except Exception as e:
                messages.error(request, f"Could not save role: {e}")
            return redirect('roles')

        if action == 'delete_role':
            role_id = request.POST.get('role_id')
            role = Role.objects.filter(id=role_id).first()
            if role:
                role.delete()
                messages.success(request, f"Role '{role.name}' deleted successfully.")
            else:
                messages.error(request, 'Role not found.')
            return redirect('roles')

    if q:
        roles = roles.filter(name__icontains=q)

    paginator = Paginator(roles, page_size_int)
    page_obj = paginator.get_page(request.GET.get('page'))
    permission_fields = [
        ('can_access_inventory', 'Inventory Access'),
        ('can_manage_blood_requests', 'Blood Requests'),
        ('can_manage_camps', 'Camps'),
        ('can_manage_donors', 'Donors'),
        ('can_manage_volunteers', 'Volunteers'),
        ('can_manage_services', 'Services'),
        ('can_manage_users', 'Users'),
        ('can_manage_roles', 'Roles'),
    ]

    edit_role_permissions = set()
    if edit_role:
        for field, _ in permission_fields:
            if getattr(edit_role, field, False):
                edit_role_permissions.add(field)

    return render(request, 'roles.html', {
        'page_obj': page_obj,
        'search_query': q,
        'page_size': page_size,
        'edit_role': edit_role,
        'permission_fields': permission_fields,
        'edit_role_permissions': edit_role_permissions,
    })

@login_required
@user_passes_test(lambda u: user_has_any_permission(u))
def mark_notification_read(request, notification_id):
    from django.db.models import Q
    from .models import Notification
    notification = get_object_or_404(
        Notification,
        Q(id=notification_id),
        Q(recipient=request.user) | Q(recipient__isnull=True)
    )
    notification.is_read = True
    notification.save(update_fields=['is_read'])
    next_url = request.GET.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('admin_notifications')

@login_required
def mark_all_notifications_read(request):
    from django.db.models import Q
    from .models import Notification
    try:
        Notification.objects.filter(
            is_read=False,
        ).filter(
            Q(recipient=request.user) | Q(recipient__isnull=True)
        ).update(is_read=True)
    except ProgrammingError:
        pass
    next_url = request.GET.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('admin_notifications')

@login_required
@transaction.atomic
def return_cart_item(request, cart_item_id):

    rr = get_object_or_404(History.objects.select_for_update(),id=cart_item_id,user_id=request.user.id)

    if rr.is_return_requested:
        messages.info(request, "Return request already sent.")
        return redirect("userdetail")

    rr.is_return_requested = True
    rr.status = "pending"
    rr.save(update_fields=["is_return_requested", "status"])

    try:
        send_notification(
            title=f"Return Request Submitted for {rr.order_id}",
            message=(
                f"User {request.user.username} requested a return for item {rr.rental_item.title} "
                f"(Order {rr.order_id})."
            ),
            notification_type='return',
            link=f"/admin/app/history/{rr.id}/change/",
            order_id=rr.order_id,
            rental=rr
        )
    except Exception as e:
        print(f"[notification cart return error] {e}")

    messages.success(request, "Return request sent to admin for approval.")
    return redirect("userdetail")

@login_required
def return_receipt(request, order_id):

    rentals = (
        History.objects
        .filter(
            order_id=order_id,
            is_returned=True
        )
        .select_related("rental_item")
    )
    if not user_has_any_permission(request.user):
        rentals = rentals.filter(user_id=request.user.id)

    if not rentals.exists():
        messages.error(request, "Return receipt not available.")
        return redirect("bookingsammry")

    rental = rentals.first()
    user_detail = UserDetail.objects.filter(user=rental.user).first()

    breakdown = build_booking_receipt_breakdown(rental, rentals)

    donation_amount = sum((rr.donation_amount for rr in rentals), Decimal("0"))
    donation_comment = next((rr.donation_comment for rr in rentals if rr.donation_comment), "")
    
    total_deposit = breakdown["original_total_deposit"]
    additional_deposit = sum((ext["additional_deposit"] for ext in breakdown["extension_history"]), Decimal("0"))
    final_deposit = total_deposit + additional_deposit
    
    delivery_charge = rental.delivery_charge
    all_order_rentals = History.objects.filter(order_id=order_id)
    return_pickup_charge = max((rr.return_pickup_charge for rr in all_order_rentals), default=Decimal("0"))
    
    total_rent_with_extensions = breakdown["original_total_rent"] + breakdown["extension_total"]
    total_amount = total_rent_with_extensions + delivery_charge + return_pickup_charge + donation_amount
    amount_paid = breakdown["amount_paid"]

    net_balance = amount_paid - total_amount
    if rental.deposit_donated:
        refund_amount = Decimal("0")
    elif net_balance > 0:
        refund_amount = min(net_balance, final_deposit)
    else:
        refund_amount = Decimal("0")

    amount_remaining = max(total_amount - amount_paid, Decimal("0"))

    context = {
        "order": rental,          
        "rental": rental,
        "order_id": order_id,
        "return_date": rental.actual_return_date,
        "user_detail": user_detail,
        "patient_name": rental.patient_name,
        "item_totals": breakdown["original_item_totals"],
        "total_quantity": breakdown["total_quantity"],
        "total_rent": breakdown["original_total_rent"],
        "total_deposit": final_deposit,
        "donation_amount": donation_amount,
        "donation_comment": donation_comment,
        "total_amount": total_amount,
        "amount_paid": amount_paid,
        "amount_remaining": amount_remaining,
        "refund_amount": refund_amount,
        "delivery_option": rental.delivery_option,
        "delivery_charge": rental.delivery_charge,
        "return_pickup_charge": return_pickup_charge,
        
        # Extension history fields
        "original_booking_date": breakdown["original_booking_date"],
        "original_start_date": breakdown["original_start_date"],
        "original_return_date": breakdown["original_return_date"],
        "original_days": breakdown["original_days"],
        "total_rent_days": breakdown["total_rent_days"],
        "effective_return_date": breakdown["effective_return_date"],
        "extension_history": breakdown["extension_history"],
        "extension_total": breakdown["extension_total"],
    }

    return render(request, "return_receipt.html", context)


def send_submission_email(subject, details_dict, attachment=None):
    """
    Safely sends email to ADMIN_EMAIL with full submission details.
    Omits zero amounts, empty strings, None, and N/A values.
    Supports optional file attachments.
    """
    from django.core.mail import EmailMessage
    import os
    admin_email = getattr(settings, 'ADMIN_EMAIL', 'bhayander@kutchyuvaksangh.org')
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'bhayander@kutchyuvaksangh.org')
    
    body_lines = [f"{subject}\n"]
    for key, value in details_dict.items():
        if value is None:
            continue
        val_str = str(value).strip()
        if not val_str or val_str.lower() == 'n/a':
            continue
        if val_str in ("0", "0.0", "0.00", "Rs. 0", "Rs. 0.00", "₹0", "₹0.00"):
            continue
        body_lines.append(f"* {key}: {val_str}")
        
    body_lines.append("\nFor any further assistance call 9867348169 / 9820247550 or login to sickbed.itegoss.in\n\nThank you")
    body = "\n".join(body_lines)
    
    try:
        email_msg = EmailMessage(
            subject=subject,
            body=body,
            from_email=from_email,
            to=[admin_email],
        )
        if attachment:
            try:
                if hasattr(attachment, 'file'):
                    attachment_file = attachment.file
                else:
                    attachment_file = attachment
                if hasattr(attachment_file, 'read'):
                    filename = os.path.basename(attachment.name if hasattr(attachment, 'name') else 'attachment')
                    content = attachment_file.read()
                    if hasattr(attachment_file, 'seek'):
                        attachment_file.seek(0)
                    email_msg.attach(filename, content)
            except Exception as att_err:
                print(f"[send_submission_email attachment error] {att_err}")

        email_msg.send(fail_silently=False)
        print(f"Submission email sent to {admin_email}")
    except Exception as e:
        print(f"Error sending submission email: {e}")


from django.contrib.auth.decorators import login_required

@login_required(login_url='signin')
def request_blood(request):
    resp = ensure_module_access(request, 'can_manage_blood_requests')
    if resp:
        return resp
    # Admin users see the management table on GET. Regular users see the form.
    if request.method == 'POST':
        form = BloodRequestForm(request.POST, request.FILES)
        print("[blood_request] POST received")
        print("[blood_request] form.is_valid() =", form.is_valid())
        if not form.is_valid():
            print("[blood_request] form errors =", form.errors)
            return render(request, 'request_blood.html', {'form': form})

        blood_request = form.save(commit=False)
        print("[blood_request] form.save(commit=False) succeeded")
        blood_request.created_by = request.user
        blood_request.updated_by = request.user
        blood_request.save()
        blood_request.append_status_history('Pending', changed_by=request.user, note='Request submitted')
        print("[blood_request] model save() succeeded, id=", blood_request.id)

        details = {
            "Patient Name": blood_request.patient_name,
            "Hospital Name": blood_request.hospital_name,
            "Hospital Area": blood_request.hospital_area,
            "Blood Group Required": blood_request.blood_group,
            "Relative/Coordinator Name": blood_request.coordinator_name,
            "Coordinator Contact": blood_request.coordinator_contact,
            "Reference Name": blood_request.reference_name or "N/A",
            "Reference Contact": blood_request.reference_contact or "N/A",
            "Submission Date": blood_request.created_at,
        }

        send_submission_email("New Blood Request Received", details, attachment=blood_request.prescription if blood_request.prescription else None)

        whatsapp_msg = (
            f"Hello {blood_request.coordinator_name},\n\n"
            f"Thank you for submitting a blood request for patient {blood_request.patient_name} ({blood_request.blood_group}). "
            f"Our team is reviewing the request and will match with available blood banks/donors.\n\n"
            f"Regards,\nKYS Bhayander Team"
        )

        send_whatsapp_message(blood_request.coordinator_contact, whatsapp_msg)

        if request.user.is_authenticated:
            try:
                send_notification(
                    title="Blood Request Submitted",
                    message=f"Your blood request for patient {blood_request.patient_name} ({blood_request.blood_group}) at {blood_request.hospital_name} has been submitted successfully.",
                    notification_type="info",
                    link=f"/request-blood/view/{blood_request.id}/",
                    recipient=request.user,
                )
            except Exception:
                pass

        try:
            send_notification(
                title="New Blood Request Received",
                message=f"New blood request for patient {blood_request.patient_name} ({blood_request.blood_group}) at {blood_request.hospital_name}.",
                notification_type="info",
                link=f"/request-blood/view/{blood_request.id}/",
                recipient=None,
            )
        except Exception:
            pass

        messages.success(request, "Your request for blood has been submitted successfully! We will coordinate shortly.")
        return redirect('index')

    # GET handling
    if user_has_permission(request.user, 'can_manage_blood_requests'):
        # Admin: show management table
        q = request.GET.get('q', '').strip()
        page_size = request.GET.get('page_size', '20')
        try:
            page_size_int = int(page_size)
            if page_size_int <= 0:
                page_size_int = 20
        except ValueError:
            page_size_int = 20
        page_size = str(page_size_int)
        qs = BloodRequest.objects.all().order_by('-created_at')
        if q:
            qs = qs.filter(
                Q(request_id__icontains=q) |
                Q(patient_name__icontains=q) |
                Q(hospital_name__icontains=q) |
                Q(hospital_area__icontains=q) |
                Q(coordinator_name__icontains=q) |
                Q(coordinator_contact__icontains=q) |
                Q(reference_name__icontains=q) |
                Q(reference_contact__icontains=q) |
                Q(blood_group__icontains=q)
            )

        if request.GET.get('export') == 'csv':
            import csv
            from django.http import HttpResponse
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = 'attachment; filename="blood_requests.csv"'
            writer = csv.writer(response)
            writer.writerow([
                'ID', 'Patient Name', 'Blood Group', 'Blood Component',
                'Price', 'Blood Bank', 'Hospital Name', 'Hospital Area',
                'Status', 'Submitted Date'
            ])
            for req_item in qs:
                writer.writerow([
                    req_item.request_id or req_item.formatted_request_id,
                    req_item.patient_name,
                    req_item.blood_group or '-',
                    req_item.blood_component or '-',
                    req_item.price if req_item.price is not None else '-',
                    req_item.blood_bank or '-',
                    req_item.hospital_name,
                    req_item.hospital_area,
                    req_item.status,
                    req_item.created_at.strftime('%d %b, %Y %H:%M') if req_item.created_at else '-'
                ])
            return response

        paginator = Paginator(qs, page_size_int)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)

        return render(request, 'blood_requests_admin.html', {
            'page_obj': page_obj,
            'search_query': q,
            'page_size': page_size,
            'active_employees': User.objects.filter(
                Q(role_assignments__isnull=False) | Q(is_staff=True) | Q(is_superuser=True),
                is_active=True
            ).distinct().order_by('username'),
        })

    # Regular user: show submission form
    form = BloodRequestForm()
    blood_banks = BloodBank.objects.all()
    return render(request, 'request_blood.html', {'form': form, 'blood_banks': blood_banks})


@login_required
def edit_blood_request(request, request_id):
    req = get_object_or_404(BloodRequest, id=request_id)
    is_allowed = (
        request.user.is_superuser
        or request.user.is_staff
        or user_has_permission(request.user, 'can_manage_blood_requests')
        or (req.assigned_employee_id and req.assigned_employee_id == request.user.id)
    )
    if not is_allowed:
        messages.error(request, "You do not have permission to edit this request.")
        return redirect('index')

    blood_banks = BloodBank.objects.all()
    if request.method == 'POST' and 'patient_name' in request.POST:
        form = BloodRequestForm(request.POST, request.FILES, instance=req)
        if form.is_valid():
            blood_request = form.save(commit=False)
            if blood_request.blood_bank and blood_request.blood_bank.strip():
                if blood_request.status in {'Assigned', 'Pending', 'Accepted', 'Searching'}:
                    blood_request.status = 'Fulfilled'
                    try:
                        blood_request.append_status_history('Fulfilled', changed_by=request.user, note=f'Blood bank selected: {blood_request.blood_bank}')
                    except Exception:
                        pass
            blood_request.updated_by = request.user
            blood_request.save()

            if blood_request.created_by:
                try:
                    send_notification(
                        title=f"Blood Request Update: {blood_request.status}",
                        message=f"Your blood request for patient {blood_request.patient_name} status was updated to {blood_request.status}.",
                        notification_type="info",
                        link=f"/request-blood/view/{blood_request.id}/",
                        recipient=blood_request.created_by,
                    )
                except Exception:
                    pass

            if blood_request.assigned_employee and blood_request.assigned_employee != request.user:
                try:
                    send_notification(
                        title=f"Assigned Request Update: {blood_request.status}",
                        message=f"Blood request for {blood_request.patient_name} assigned to you was updated to {blood_request.status}.",
                        notification_type="info",
                        link=f"/request-blood/view/{blood_request.id}/",
                        recipient=blood_request.assigned_employee,
                    )
                except Exception:
                    pass

            messages.success(request, "Blood request updated successfully.")
            if user_has_permission(request.user, 'can_manage_blood_requests'):
                return redirect('request_blood')
            return redirect('employee_blood_requests')
        return render(request, 'request_blood.html', {'form': form, 'is_edit': True, 'req': req, 'blood_banks': blood_banks})
    else:
        form = BloodRequestForm(instance=req)
        return render(request, 'request_blood.html', {'form': form, 'is_edit': True, 'req': req, 'blood_banks': blood_banks})


@login_required
def admin_view_blood_request(request, request_id):
    req = get_object_or_404(BloodRequest, id=request_id)
    is_allowed = (
        request.user.is_superuser
        or request.user.is_staff
        or user_has_permission(request.user, 'can_manage_blood_requests')
        or (req.assigned_employee_id and req.assigned_employee_id == request.user.id)
    )
    if not is_allowed:
        messages.error(request, "You do not have permission to view this request.")
        return redirect('index')
    return render(request, 'blood_request_detail.html', {'req': req})


@login_required
@user_passes_test(lambda u: user_has_permission(u, 'can_manage_blood_requests'))
def assign_blood_request_employee(request, request_id):
    req = get_object_or_404(BloodRequest, id=request_id)
    if request.method != 'POST':
        messages.error(request, 'Invalid assignment request.')
        return redirect('request_blood')

    form = AssignEmployeeForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Please select a valid active user.')
        return redirect('request_blood')

    employee = form.cleaned_data['assigned_employee']
    prev_employee = req.assigned_employee

    req.assigned_employee = employee
    req.assigned_by = request.user
    req.assigned_at = timezone.now()
    if req.status in {'Pending', 'Accepted'}:
        req.status = 'Assigned'
    req.updated_by = request.user
    if form.cleaned_data.get('remarks'):
        req.remarks = form.cleaned_data.get('remarks')
    req.save()

    note_text = f'Reassigned to {employee.username}' if prev_employee else f'Assigned to {employee.username}'
    req.append_status_history('Assigned', changed_by=request.user, note=note_text)
    try:
        send_notification(
            title='Blood Request Assigned',
            message=(
                f'You have been assigned to blood request for {req.patient_name} '
                f'({req.blood_group}) at {req.hospital_name}. Please review the request.'
            ),
            recipient=employee,
            link=f'/request-blood/view/{req.id}/',
        )
    except Exception:
        pass
    messages.success(request, f'Successfully assigned blood request to {employee.get_full_name() or employee.username}.')
    return redirect('request_blood')


@login_required
def admin_edit_blood_request_status(request, request_id):
    req = get_object_or_404(BloodRequest, id=request_id)
    is_allowed = (
        request.user.is_superuser
        or request.user.is_staff
        or user_has_permission(request.user, 'can_manage_blood_requests')
        or (req.assigned_employee_id and req.assigned_employee_id == request.user.id)
    )
    if not is_allowed:
        messages.error(request, "You do not have permission to update status.")
        return redirect('index')
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'accept':
            if req.status != 'Pending':
                messages.error(request, 'Only pending requests can be accepted.')
            else:
                req.status = 'Accepted'
                req.updated_by = request.user
                req.remarks = request.POST.get('remarks', req.remarks)
                req.save()
                req.append_status_history('Accepted', changed_by=request.user, note='Accepted by admin')
                messages.success(request, 'Request accepted.')
        elif action == 'reject':
            if req.status in {'Completed', 'Rejected'}:
                messages.error(request, 'This request cannot be rejected again.')
            else:
                req.status = 'Rejected'
                req.updated_by = request.user
                req.remarks = request.POST.get('remarks', req.remarks)
                req.save()
                req.append_status_history('Rejected', changed_by=request.user, note='Rejected by admin')
                messages.success(request, 'Request rejected.')
        elif action == 'assign':
            return assign_blood_request_employee(request, request_id)
        elif action == 'advance':
            if req.status == 'Assigned':
                req.status = 'Searching'
            elif req.status == 'Searching':
                req.status = 'Blood Available'
            elif req.status == 'Blood Available':
                req.status = 'Ready for Pickup'
            elif req.status == 'Ready for Pickup':
                req.status = 'Received'
            elif req.status == 'Received':
                req.status = 'Completed'
            else:
                messages.error(request, 'This request cannot be advanced from the current status.')
                return redirect('request_blood')
            req.updated_by = request.user
            req.save()
            req.append_status_history(req.status, changed_by=request.user, note='Workflow advanced')
            messages.success(request, f'Status updated to {req.status}.')
        elif action == 'ready_for_pickup':
            if req.status != 'Blood Available':
                messages.error(request, 'Only blood-available requests can be marked ready for pickup.')
            else:
                req.status = 'Ready for Pickup'
                req.updated_by = request.user
                req.save()
                req.append_status_history('Ready for Pickup', changed_by=request.user, note='Marked ready for pickup')
                try:
                    send_notification(
                        title='Blood Ready for Pickup',
                        message=f'Blood for {req.patient_name} is ready for pickup.',
                        notification_type='info',
                        link=f'/request-blood/view/{req.id}/',
                        user=req.created_by
                    )
                except Exception:
                    pass
                messages.success(request, 'Marked ready for pickup.')
        elif action == 'complete':
            if req.status != 'Received':
                messages.error(request, 'Only received requests can be completed.')
            else:
                req.status = 'Completed'
                req.updated_by = request.user
                req.save()
                req.append_status_history('Completed', changed_by=request.user, note='Completed by admin')
                messages.success(request, 'Request completed.')
        elif action == 'cancel':
            if req.status in {'Completed', 'Cancelled', 'Rejected'}:
                messages.error(request, 'This request is already completed, cancelled, or rejected.')
            else:
                req.status = 'Cancelled'
                req.updated_by = request.user
                # Save cancellation reason
                req.cancellation_reason = request.POST.get('cancellation_reason', '').strip()
                # Preserve existing remarks or add note
                if not req.remarks:
                    req.remarks = request.POST.get('remarks') or 'Cancelled by admin'
                req.save()
                req.append_status_history('Cancelled', changed_by=request.user, note='Cancelled: ' + (req.cancellation_reason or 'No reason'))
                if req.created_by:
                    try:
                        send_notification(
                            title='Blood Request Cancelled',
                            message=f'Your blood request for patient {req.patient_name} ({req.blood_group}) was cancelled as blood was not available.',
                            notification_type='cancelled',
                            link=f'/request-blood/view/{req.id}/',
                            recipient=req.created_by
                        )
                    except Exception:
                        pass
                if req.assigned_employee and req.assigned_employee != request.user:
                    try:
                        send_notification(
                            title='Assigned Request Cancelled',
                            message=f'Blood request for patient {req.patient_name} assigned to you was cancelled.',
                            notification_type='cancelled',
                            link=f'/request-blood/view/{req.id}/',
                            recipient=req.assigned_employee
                        )
                    except Exception:
                        pass
                messages.success(request, 'Blood request cancelled successfully.')
        elif action == 'employee_searching':
            if req.assigned_employee_id != request.user.id:
                messages.error(request, 'You are not assigned to this request.')
            else:
                req.status = 'Searching'
                req.updated_by = request.user
                req.remarks = request.POST.get('remarks', req.remarks)
                req.save()
                req.append_status_history('Searching', changed_by=request.user, note='Employee continued searching')
                try:
                    send_notification(
                        title='Blood Search Update',
                        message=f'Employee updated request for {req.patient_name} to Searching.',
                        notification_type='info',
                        link=f'/request-blood/view/{req.id}/',
                        user=req.created_by
                    )
                except Exception:
                    pass
                messages.success(request, 'Status updated to Searching.')
        elif action == 'employee_blood_available':
            if req.assigned_employee_id != request.user.id:
                messages.error(request, 'You are not assigned to this request.')
            else:
                req.status = 'Blood Available'
                req.updated_by = request.user
                req.remarks = request.POST.get('remarks', req.remarks)
                req.save()
                req.append_status_history('Blood Available', changed_by=request.user, note='Employee marked blood available')
                try:
                    send_notification(
                        title='Blood Available',
                        message=f'Blood is available for {req.patient_name}.',
                        notification_type='info',
                        link=f'/request-blood/view/{req.id}/',
                        user=req.created_by
                    )
                except Exception:
                    pass
                messages.success(request, 'Status updated to Blood Available.')
        elif action == 'user_received':
            if req.status != 'Ready for Pickup':
                messages.error(request, 'Only ready-for-pickup requests can be marked received.')
            else:
                req.status = 'Received'
                req.updated_by = request.user
                req.save()
                req.append_status_history('Received', changed_by=request.user, note='User marked received')
                messages.success(request, 'Blood marked as received.')
        elif action == 'edit':
            return edit_blood_request(request, request_id)
        else:
            messages.error(request, 'Invalid action.')
    return redirect('request_blood')


@login_required
@user_passes_test(lambda u: user_has_permission(u, 'can_manage_blood_requests'))
def delete_blood_request(request, request_id):
    req = get_object_or_404(BloodRequest, id=request_id)
    req.delete()
    messages.success(request, "Blood request deleted.")
    return redirect('request_blood')


@login_required
def employee_blood_requests(request):
    if not request.user.is_authenticated:
        return redirect('signin')
    qs = BloodRequest.objects.filter(assigned_employee=request.user).order_by('-created_at')
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'employee_blood_requests.html', {
        'page_obj': page_obj,
        'search_query': request.GET.get('q', '').strip(),
    })

from django.contrib.auth.decorators import login_required

def organize_camp(request):
    if request.method == 'POST':
        form = CampOrganizerForm(request.POST)
        if form.is_valid():
            camp = form.save(commit=False)

            if request.user.is_authenticated:
                camp.created_by = request.user
                camp.updated_by = request.user
            else:
                camp.created_by = None
                camp.updated_by = None

            camp.save()

            # Send Email to Admin
            details = {
                "Organizer Name": camp.organizer_name,
                "Organization/Group": camp.organization_name,
                "Contact Number": camp.contact_number,
                "Email": camp.email,
                "Proposed Date": camp.proposed_date,
                "Proposed Venue": camp.proposed_venue,
                "Expected Donors": camp.expected_donors,
                "Mobile Van Required": "Yes" if camp.mobile_van_required else "No",
                "Volunteers Available": "Yes" if camp.volunteers_available else "No",
                "Submission Date": camp.created_at,
            }

            send_submission_email("New Blood Donation Camp Proposal", details)

            # Send WhatsApp notification
            whatsapp_msg = (
                f"Hello {camp.organizer_name},\n\n"
                f"We deeply appreciate your initiative to organize a blood donation camp with {camp.organization_name} at {camp.proposed_venue} on {camp.proposed_date}. "
                f"Our team will contact you shortly to coordinate details.\n\n"
                f"Regards,\nKYS Bhayander Team"
            )

            send_whatsapp_message(camp.contact_number, whatsapp_msg)

            messages.success(
                request,
                "Thank you for organizing the blood donation camp! We will contact you shortly."
            )
            return redirect('index')
        else:
            print("CampOrganizerForm invalid:", form.errors.as_json())
            return render(request, 'organize_camp.html', {'form': form})
    # Admin: show management table
    if user_has_permission(request.user, 'can_manage_camps'):
        q = request.GET.get('q', '').strip()
        page_size = request.GET.get('page_size', '10')
        try:
            page_size_int = int(page_size)
            if page_size_int <= 0:
                page_size_int = 10
        except ValueError:
            page_size_int = 10
        page_size = str(page_size_int)

        qs = CampOrganizer.objects.all().order_by('-created_at')
        if q:
            from django.db.models import Q
            qs = qs.filter(
                Q(organizer_name__icontains=q) |
                Q(organization_name__icontains=q) |
                Q(contact_number__icontains=q) |
                Q(proposed_venue__icontains=q)
            )
        paginator = Paginator(qs, page_size_int)
        page_obj = paginator.get_page(request.GET.get('page'))
        return render(request, 'camps_admin.html', {'page_obj': page_obj, 'search_query': q, 'page_size': page_size})

    else:
        form = CampOrganizerForm()

    return render(request, 'organize_camp.html', {'form': form})


@login_required
def update_camp_status(request, camp_id):
    if not (user_has_permission(request.user, 'can_manage_camps') or request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'success': False, 'error': 'Permission denied.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    camp = get_object_or_404(CampOrganizer, id=camp_id)

    new_status = request.POST.get('status')
    if not new_status and request.body:
        try:
            import json
            data = json.loads(request.body)
            new_status = data.get('status')
        except Exception:
            pass

    allowed_statuses = ['Completed', 'Pending', 'Cancelled']
    if new_status not in allowed_statuses:
        return JsonResponse({
            'success': False,
            'error': f"Invalid status '{new_status}'. Allowed values are: {', '.join(allowed_statuses)}."
        }, status=400)

    camp.status = new_status
    camp.updated_by = request.user
    camp.save()

    return JsonResponse({
        'success': True,
        'camp_id': camp.id,
        'status': camp.status,
        'message': f"Status updated to {camp.status} successfully."
    })

def be_donor(request):
    if request.method == 'POST':
        form = BloodDonorForm(request.POST)
        if form.is_valid():
            donor = form.save(commit=False)

            if request.user.is_authenticated:
                donor.created_by = request.user
                donor.updated_by = request.user
            else:
                donor.created_by = None
                donor.updated_by = None

            donor.save()

            # Send Email to Admin
            details = {
                "Donor Name": donor.get_full_name(),
                "Contact Number": donor.contact_number,
                "DOB": donor.date_of_birth,
                "Gender": donor.gender,
                "Blood Group": donor.blood_group,
                "Area of Residence": donor.area_of_residence,
                "Reference Name": donor.reference_name or "N/A",
                "Reference Contact": donor.reference_contact or "N/A",
                "Registration Date": donor.created_at,
            }

            send_submission_email("New Donor Registration Received", details)

            # Send WhatsApp notification
            whatsapp_msg = (
                f"Hello {donor.get_full_name()},\n\n"
                f"Congratulations on registering as a blood donor! You are a hero. "
                f"We will contact you whenever there is a requirement matching your blood group ({donor.blood_group}).\n\n"
                f"Regards,\nKYS Bhayander Team"
            )

            send_whatsapp_message(donor.contact_number, whatsapp_msg)

            messages.success(
                request,
                "Congratulations! You have registered as a blood donor successfully."
            )
            return redirect('index')
        else:
            print("BloodDonorForm invalid:", form.errors.as_json())
            return render(request, 'be_donor.html', {'form': form})
    # Admin: show management table
    if user_has_permission(request.user, 'can_manage_donors'):
        q = request.GET.get('q', '').strip()
        page_size = request.GET.get('page_size', '10')
        try:
            page_size_int = int(page_size)
            if page_size_int <= 0:
                page_size_int = 10
        except ValueError:
            page_size_int = 10
        page_size = str(page_size_int)
        qs = BloodDonor.objects.all().order_by('-created_at')
        if q:
            qs = qs.filter(
                Q(full_name__icontains=q) |
                Q(contact_number__icontains=q) |
                Q(area_of_residence__icontains=q) |
                Q(blood_group__icontains=q)
            )
        paginator = Paginator(qs, page_size_int)
        page_obj = paginator.get_page(request.GET.get('page'))
        return render(request, 'donors_admin.html', {'page_obj': page_obj, 'search_query': q, 'page_size': page_size})

    else:
        form = BloodDonorForm()

    return render(request, 'be_donor.html', {'form': form})
from django.contrib.auth.decorators import login_required

def medical_services(request):
    # Admin: show services management
    if user_has_permission(request.user, 'can_manage_services'):
        q = request.GET.get('q', '').strip()
        page_size = request.GET.get('page_size', '10')
        try:
            page_size_int = int(page_size)
            if page_size_int <= 0:
                page_size_int = 10
        except ValueError:
            page_size_int = 10
        page_size = str(page_size_int)
        qs = SupportService.objects.all().prefetch_related('contacts').order_by('name')
        if q:
            from django.db.models import Q
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(description__icontains=q) |
                Q(contacts__contact_name__icontains=q) |
                Q(contacts__contact_number__icontains=q)
            ).distinct()
        paginator = Paginator(qs, page_size_int)
        page_obj = paginator.get_page(request.GET.get('page'))
        return render(request, 'services_admin.html', {'page_obj': page_obj, 'search_query': q, 'page_size': page_size})

    active_services = SupportService.objects.filter(is_active=True).prefetch_related('contacts').order_by('name')
    return render(request, 'medical_services.html', {'services': active_services})

@login_required(login_url='signin')
def add_service(request):
    resp = ensure_module_access(request, 'can_manage_services')
    if resp:
        return resp
    if request.method == 'POST':
        name = (request.POST.get('name') or request.POST.get('title') or '').strip()
        description = (request.POST.get('description') or '').strip()
        is_active = 'is_active' in request.POST or request.POST.get('is_active') == 'on'
        if name and description:
            service = SupportService.objects.create(
                name=name,
                description=description,
                is_active=is_active
            )
            seen_contacts = set()
            for i in range(1, 5):
                s_name = (request.POST.get(f'service_name_{i}') or '').strip()
                c_name = (request.POST.get(f'contact_name_{i}') or '').strip()
                c_num = (request.POST.get(f'contact_number_{i}') or '').strip()
                if c_name or c_num or s_name:
                    key = (s_name.lower(), c_name.lower(), c_num)
                    if key not in seen_contacts:
                        seen_contacts.add(key)
                        SupportServiceContact.objects.create(
                            service=service,
                            service_name=s_name,
                            contact_name=c_name,
                            contact_number=c_num,
                            display_order=i
                        )
            messages.success(request, 'Service created successfully.')
            return redirect('medical_services')
        field_errors = {}
        if not name:
            field_errors['name'] = 'Service title is required.'
        if not description:
            field_errors['description'] = 'Description is required.'
        return render(request, 'add_service.html', {
            'field_errors': field_errors,
            'name': name,
            'description': description,
            'is_active': is_active
        })
    return render(request, 'add_service.html')

@login_required(login_url='signin')
def edit_service(request, pk):
    resp = ensure_module_access(request, 'can_manage_services')
    if resp:
        return resp
    service = get_object_or_404(SupportService, pk=pk)
    if request.method == 'POST':
        name = (request.POST.get('name') or request.POST.get('title') or '').strip()
        description = (request.POST.get('description') or '').strip()
        is_active = 'is_active' in request.POST or request.POST.get('is_active') == 'on'
        if name and description:
            service.name = name
            service.description = description
            service.is_active = is_active
            service.save()

            service.contacts.all().delete()
            seen_contacts = set()
            for i in range(1, 5):
                s_name = (request.POST.get(f'service_name_{i}') or '').strip()
                c_name = (request.POST.get(f'contact_name_{i}') or '').strip()
                c_num = (request.POST.get(f'contact_number_{i}') or '').strip()
                if c_name or c_num or s_name:
                    key = (s_name.lower(), c_name.lower(), c_num)
                    if key not in seen_contacts:
                        seen_contacts.add(key)
                        SupportServiceContact.objects.create(
                            service=service,
                            service_name=s_name,
                            contact_name=c_name,
                            contact_number=c_num,
                            display_order=i
                        )
            messages.success(request, 'Service updated successfully.')
            return redirect('medical_services')
        field_errors = {}
        if not name:
            field_errors['name'] = 'Service title is required.'
        if not description:
            field_errors['description'] = 'Description is required.'
        contacts_list = list(service.contacts.all().order_by('display_order'))
        contacts = []
        for i in range(4):
            if i < len(contacts_list):
                contacts.append(contacts_list[i])
            else:
                contacts.append({'service_name': '', 'contact_name': '', 'contact_number': ''})
        return render(request, 'edit_service.html', {
            'service': service,
            'contacts': contacts,
            'field_errors': field_errors
        })

    contacts_list = list(service.contacts.all().order_by('display_order'))
    contacts = []
    for i in range(4):
        if i < len(contacts_list):
            contacts.append(contacts_list[i])
        else:
            contacts.append({'service_name': '', 'contact_name': '', 'contact_number': ''})

    return render(request, 'edit_service.html', {'service': service, 'contacts': contacts})

@login_required(login_url='signin')
def delete_service(request, pk):
    resp = ensure_module_access(request, 'can_manage_services')
    if resp:
        return resp
    service = get_object_or_404(SupportService, pk=pk)
    service.delete()
    messages.success(request, 'Service deleted successfully.')
    return redirect('medical_services')

def volunteer_event(request):
    if request.method == 'POST':
        form = EventVolunteerForm(request.POST)
        if form.is_valid():
            volunteer = form.save(commit=False)

            if request.user.is_authenticated:
                volunteer.created_by = request.user
                volunteer.updated_by = request.user
            else:
                volunteer.created_by = None
                volunteer.updated_by = None

            volunteer.save()

            # Send Email to Admin
            details = {
                "Volunteer Name": volunteer.full_name,
                "Contact Number": volunteer.contact_number,
                "Email": volunteer.email,
                "DOB": volunteer.date_of_birth or "N/A",
                "Gender": volunteer.gender or "N/A",
                "Area of Residence": volunteer.area_of_residence,
                "Event Interest": volunteer.event_interest or "General Volunteer",
                "Skills & Remarks": volunteer.skills_remarks or "N/A",
                "Registration Date": volunteer.created_at,
            }

            send_submission_email("New Event Volunteer Registration", details)

            # Send WhatsApp notification
            whatsapp_msg = (
                f"Hello {volunteer.full_name},\n\n"
                f"Thank you for registering as a volunteer with KYS Bhayander! "
                f"Your dedication to community service helps us drive positive social impact. "
                f"Our team will notify you regarding upcoming drives and events.\n\n"
                f"Regards,\nKYS Bhayander Team"
            )

            send_whatsapp_message(volunteer.contact_number, whatsapp_msg)

            messages.success(
                request,
                "Thank you for volunteering! Your registration has been submitted successfully."
            )
            return redirect('index')
        else:
            print("EventVolunteerForm invalid:", form.errors.as_json())
            return render(request, 'volunteer_event.html', {'form': form})
    # Admin: show volunteers management
    if user_has_permission(request.user, 'can_manage_volunteers'):
        q = request.GET.get('q', '').strip()
        page_size = request.GET.get('page_size', '10')
        try:
            page_size_int = int(page_size)
            if page_size_int <= 0:
                page_size_int = 10
        except ValueError:
            page_size_int = 10
        page_size = str(page_size_int)
        qs = EventVolunteer.objects.all().order_by('-created_at')
        if q:
            from django.db.models import Q
            qs = qs.filter(
                Q(full_name__icontains=q) |
                Q(contact_number__icontains=q) |
                Q(email__icontains=q) |
                Q(area_of_residence__icontains=q)
            )
        paginator = Paginator(qs, page_size_int)
        page_obj = paginator.get_page(request.GET.get('page'))
        return render(request, 'volunteers_admin.html', {'page_obj': page_obj, 'search_query': q, 'page_size': page_size})

    else:
        form = EventVolunteerForm()

    return render(request, 'volunteer_event.html', {'form': form})

from django.http import FileResponse
from django.conf import settings
import os
def service_worker(request):
    file_path = os.path.join(
        settings.BASE_DIR,
        "static",
        "pwa",
        "service-worker.js"
    )

    return FileResponse(
        open(file_path, "rb"),
        content_type="application/javascript"
    )
