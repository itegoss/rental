from datetime import datetime, date, timedelta
from decimal import Decimal
from collections import defaultdict
from io import BytesIO
import os
import re
import uuid
import random
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.db import transaction
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

from .models import (
    Inventory,
    History,
    UserDetail,
    Payment,
    Services,
    Cart,
    CartItem,
    Receipt,
    Customer,
    NotifyRequest,
)
from .utils import send_overdue_email, generate_sequential_order_id, generate_receipt, receipt_filename, send_whatsapp_message, send_notification

def index(request):

    today = timezone.now().date()
    rentals = History.objects.filter(status='approved')

    for rental in rentals:
        if rental.end_date - timedelta(days=1) == today and not rental.is_reminder_sent:
            send_reminder_email(rental.user, rental)
            rental.is_reminder_sent = True
            rental.save(update_fields=['is_reminder_sent'])

        if rental.end_date < today and not rental.is_overdue_email_sent:
            send_overdue_email(rental.user, rental)
            rental.is_overdue_email_sent = True
            rental.save(update_fields=['is_overdue_email_sent'])
            try:
                send_notification(
                    title="Late Return Detected",
                    message=(
                        f"Late return detected for order {rental.order_id}. "
                        f"Renter: {rental.user.username}, due date: {rental.end_date}."
                    ),
                    notification_type='late_return',
                    link=f"/admin/app/history/{rental.id}/change/"
                )
            except Exception as e:
                print(f"[notification late-return error] {e}")

    featured_items = Inventory.objects.all().order_by('-available', 'title')[:4]

    return render(request, 'index.html', {
        'featured_items': featured_items
    })


def logout(request):
    if request.user.is_authenticated:
        Cart.objects.filter(user=request.user).delete()

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

        if not all([username, password, confirm_password]):
            messages.error(request, "Please fill all fields.")
            return render(request, 'signup.html')

        if password != confirm_password:
            messages.error(request, "Password and confirm password do not match.")
            return render(request, 'signup.html')

        if len(password) < 6:
            messages.error(request, "Password must be at least 6 characters long.")
            return render(request, 'signup.html')

        if username[0].isdigit():
            messages.error(request, "Username should not start with a digit.")
            return render(request, 'signup.html')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already taken.")
            return render(request, 'signup.html')

        if not re.search(r'[A-Z]', password):
            messages.error(request, "Password must contain at least one uppercase letter.")
            return render(request, 'signup.html')

        if not re.search(r'[a-z]', password):
            messages.error(request, "Password must contain at least one lowercase letter.")
            return render(request, 'signup.html')

        if not re.search(r'\d', password):
            messages.error(request, "Password must contain at least one digit.")
            return render(request, 'signup.html')

        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            messages.error(request, "Password must contain at least one special character.")
            return render(request, 'signup.html')

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

    return render(request, 'signup.html')

def signin(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        if not username or not password:
            messages.error(request, "All fields are required.", extra_tags="signin")
            return redirect('signin')

        try:
            user = User.objects.get(username=username)
            if password.isdigit():
                messages.error(request, "Password should contain alphabets or special characters.", extra_tags="signin")
                return redirect('signin')

            authenticated_user = authenticate(request, username=username, password=password)
            if authenticated_user is not None:
                login(request, authenticated_user)

                return redirect('index')
            else:
                messages.error(request, "Invalid username or password.", extra_tags="signin")
                return redirect('signin')
        except User.DoesNotExist:
            messages.error(request, "User not found.", extra_tags="signin")
            return redirect('signin')

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
        username = request.POST.get('username')
        try:
            user = User.objects.get(username=username)
            return redirect('resetpass', username=username)
        except User.DoesNotExist:
            messages.error(request, "Username does not exist.")
    return render(request, 'forgot.html')

def resetpass(request, username):
    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if not new_password or not confirm_password:
            messages.error(request, "Both password fields are required.")
            return redirect('resetpass', username=username)

        if new_password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return redirect('resetpass', username=username)

        try:
            user = User.objects.get(username=username)
            user.password = make_password(new_password)
            user.save()
            messages.success(request, "Password reset successfully. Please sign in.")
            return redirect('signin')
        except User.DoesNotExist:
            messages.error(request, "User not found.")
            return redirect('forgot')

    return render(request, 'resetpass.html', {'username': username})

def items(request):
    items = Inventory.objects.all().order_by('-available', 'title')
    search_query = request.GET.get('q', '').strip()
    if search_query:
        items = items.filter(title__icontains=search_query)
    return render(request, 'items.html', {
        'items': items,
        'search_query': search_query,
    })

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def inventory(request):
    items = Inventory.objects.all().order_by('-available', 'title')
    search_query = request.GET.get('q', '').strip()
    if search_query:
        items = items.filter(title__icontains=search_query)
    return render(request, 'inventory.html', {
        'items': items,
        'search_query': search_query,
    })

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def add_inventory_item(request):
    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        description = request.POST.get('description', '').strip()
        price_per_day = request.POST.get('price_per_day', 0)
        deposit = request.POST.get('deposit', 0)
        total_quantity = int(request.POST.get('total_quantity', 1) or 1)
        available_quantity = int(request.POST.get('available_quantity', 1) or 1)
        booked_quantity = int(request.POST.get('booked_quantity', 0) or 0)
        next_available_date = request.POST.get('next_available_date') or None
        available = request.POST.get('available') == 'on'
        item_qty = int(request.POST.get('item_qty', 1) or 1)
        price = request.POST.get('price', 0)
        donation = request.POST.get('donation') == 'on'
        donor_name = request.POST.get('donor_name', '').strip()
        donor_contact = request.POST.get('donor_contact', '').strip()

        Inventory.objects.create(
            title=title,
            description=description,
            price_per_day=price_per_day,
            deposit=deposit,
            total_quantity=total_quantity,
            available_quantity=available_quantity,
            booked_quantity=booked_quantity,
            available=available,
            next_available_date=next_available_date,
            image=request.FILES.get('image'),
            item_qty=item_qty,
            price=price,
            donation=donation,
            donor_name=donor_name,
            donor_contact=donor_contact,
        )
        messages.success(request, "New rental item added successfully.")
        return redirect('inventory')

    return redirect('inventory')

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def delete_inventory_item(request, item_id):
    item = get_object_or_404(Inventory, id=item_id)
    item.delete()
    messages.success(request, f"Item '{item.title}' deleted successfully.")
    return redirect('inventory')

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def edit_inventory_item(request, item_id):
    item = get_object_or_404(Inventory, id=item_id)
    if request.method == 'POST':
        item.title = request.POST.get('title', '').strip()
        item.description = request.POST.get('description', '').strip()
        item.price_per_day = request.POST.get('price_per_day', 0)
        item.deposit = request.POST.get('deposit', 0)
        item.total_quantity = int(request.POST.get('total_quantity', 1) or 1)
        item.available_quantity = int(request.POST.get('available_quantity', 0) or 0)
        item.booked_quantity = int(request.POST.get('booked_quantity', 0) or 0)
        item.available = request.POST.get('available') == 'on'
        
        next_avail = request.POST.get('next_available_date')
        item.next_available_date = next_avail if next_avail else None
        
        item.item_qty = int(request.POST.get('item_qty', 1) or 1)
        item.price = request.POST.get('price', 0)
        item.donation = request.POST.get('donation') == 'on'
        item.donor_name = request.POST.get('donor_name', '').strip()
        item.donor_contact = request.POST.get('donor_contact', '').strip()
        
        if request.FILES.get('image'):
            item.image = request.FILES.get('image')
            
        item.save()
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

    if not request.user.is_authenticated:
        messages.warning(request, "Please login to rent items")
        return redirect('signin')

    item = get_object_or_404(Inventory, id=item_id)

    if item.available_quantity <= 0:
        messages.error(request, "Item is out of stock.")
        return redirect('items')

    cart, _ = Cart.objects.get_or_create(user=request.user)

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

def cart_view(request):
    cart, _ = Cart.objects.get_or_create(user=request.user)
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

        if not request.user.is_superuser:
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
        if request.user.is_superuser and request.session.get("details_filled"):
            if cart_items:
                return redirect("select_delivery", pk=cart_items.first().rental_item.id)

        return redirect("userdetail")

    return render(request, "cart.html", {"cart_items": cart_items, "is_admin": request.user.is_superuser})

def select_delivery(request, pk):
    item = get_object_or_404(Inventory, pk=pk)
    request.session['item_id'] = pk
    cart = Cart.objects.filter(user=request.user).first()
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

        rental = None if has_cart_items else History.objects.filter(rental_item=item, user=request.user).last()
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

    rental = None if has_cart_items else History.objects.filter(rental_item=item, user=request.user).last()

    cart_items = []
    total_rent = 0
    total_deposit = 0

    if rental and rental.order_id:
        related = History.objects.filter(order_id=rental.order_id, user=request.user).select_related('rental_item')
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
@transaction.atomic
def paymentmethod(request):

    cart = Cart.objects.filter(user=request.user).first()
    renter_name = request.session.get("renter_name")
    patient_name = request.session.get("patient_name")
    phone = request.session.get("phone")
    address = request.session.get("address")
    id_proof_type = request.session.get("id_proof_type")
    id_proof_number = request.session.get("id_proof_number")
    id_proof_file = request.session.get("id_proof_file")
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

        for ci in cart.items.select_related("rental_item"):
            item = ci.rental_item
            if item.available_quantity < ci.quantity:
                messages.error(request, f"{item.title} is out of stock.")
                return redirect('cart')

            rental = History.objects.create(
                user=request.user,
                renter_name=renter_name,
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
                id_proof_file=id_proof_file,
                delivery_option=delivery_option.lower() if delivery_option else None,
                delivery_charge=delivery_charge,
            )

            try:
                to_phone = rental.phone
                if not to_phone:
                    try:
                        ud = UserDetail.objects.filter(user=request.user).first()
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
                link=f"/admin/app/history/?order_id={order_id}"
            )
        except Exception as e:
            print(f"[notification booking error] {e}")

        cart.delete()

        # ================= PAYMENT =================
        if payment_method.lower() == 'online':
            return redirect('payment', rental_id=created_rentals[0].id)

        elif payment_method.lower() in ['cod', 'cash on delivery']:
            for rental in created_rentals:
                rental.payment_method = 'cod'
                rental.status = 'approved'
                rental.save(update_fields=['payment_method', 'status'])

                item = rental.rental_item
                try:
                    item.update_availability()
                except Exception:
                    try:
                        item.save()
                    except Exception:
                        pass

                Payment.objects.create( rental_request=rental,payment_status='SUCCESS',order_id=generate_order_id())

            messages.success(request, "Order placed successfully with Cash on Delivery!")

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
            link=f"/admin/app/payment/{payment.id}/change/"
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

    for k in ("renter_name", "patient_name", "phone", "address", "id_proof_type", "id_proof_number", "id_proof_file", "start_date", "end_date", "details_filled", "delivery_option", "delivery_charge", "rental_id", "item_id"):
        request.session.pop(k, None)

    return render(request, "success.html", {
    "rental": rental,
    "payment": payment,
    "order_id": rental.order_id,
    "item_totals": item_totals,
    "total_quantity": total_quantity,
    "total_deposit": total_deposit,
    "total_rent": total_rent,
    "total_amount": total_amount,
    "delivery_charge": delivery_charge,
    "delivery_option": delivery_option,
    "signature": razorpay_signature, 
    "user_detail": user_detail,
    "customer_name": customer_name,
    "customer_phone": customer_phone,
    "customer_address": customer_address,
    "patient_name": customer_patient_name,
    })


def about(request):
    return render(request, 'about.html')


def send_reminder_email(user, rental):
    subject = 'Reminder: Your Rental Ends Tomorrow - Sick Bed Services'
    recipient_email = user.email

    message = f"""
    <html>
    <body>
        <p>Hi {user.username},</p>
        <p>This is a reminder that your rental item <b>{rental.rental_item.title}</b> 
        is ending on <b>{rental.end_date}</b>.</p>
        <p>Please make sure to return it on time.</p>
        <br>
        <p>Regards,<br>Sick Bed Services Team</p>
    </body>
    </html>
    """
    print(f"[email suppressed] Reminder for {recipient_email} Subject: {subject}")
    rental.is_reminder_sent = True
    rental.save()

def send_overdue_emails(user, rental):
    subject = 'Overdue Rental Notice - Sick Bed Services'
    recipient_email = user.email

    context = {
        'user': user,
        'rental_item': rental.rental_item,
        'end_date': rental.end_date
    }

    message = render_to_string('emails/overdue.html', context)
    print(f"[email suppressed] Overdue notice for {recipient_email} Subject: {subject}")
    rental.is_overdue_email_sent = True
    rental.save()


def send_notify_emails(item, user_email, user_mobile):
    from django.core.mail import send_mail
    from django.conf import settings
    
    user_subject = f'Notification Request Received - {item.title}'
    user_message = f"""
    <html>
    <body>
        <p>Hi,</p>
        <p>Thank you for your interest in <b>{item.title}</b>.</p>
        <p>We have received your notification request and will email you as soon as this item becomes available , on First Come First Serve basis .</p>
        <p>Item Details:</p>
        <ul>
            <li>Price per day: ₹{item.price_per_day}</li>
            <li>Deposit: ₹{item.deposit}</li>
        </ul>
        <br>
        <p>Regards,<br>Kutch Yuvak Sangh Team</p>
    </body>
    </html>
    """
    
    admin_subject = f'New Notify Request - {item.title}'
    admin_message = f"""
    <html>
    <body>
        <p>New notification request received.</p>
        <p>Item: {item.title}</p>
        <p>User Email: {user_email}</p>
        <p>User Mobile: {user_mobile}</p>
        <br>
        <p>Please restock this item soon.</p>
    </body>
    </html>
    """
    
    try:
        send_mail(
            user_subject,
            '',
            settings.DEFAULT_FROM_EMAIL,
            [user_email],
            html_message=user_message
        )
        print(f"✅ Notification email sent to user: {user_email}")
    except Exception as e:
        print(f"❌ Failed to send user email: {e}")
    
    try:
        send_mail(
            admin_subject,
            '',
            settings.DEFAULT_FROM_EMAIL,
            [settings.ADMIN_EMAIL],
            html_message=admin_message
        )
        print(f"✅ Notification email sent to admin: {settings.ADMIN_EMAIL}")
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
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def approve_order(request, order_id):
    orders = History.objects.filter(order_id=order_id)
    if not orders.exists():
        raise Http404("Order not found")
    
    orders.update(status="approved")
    
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
            link=f"/admin/app/history/?order_id={order_id}"
        )
    except Exception as e:
        print(f"[notification error] {e}")

    messages.success(request, f"Order {order_id} approved successfully.")
    return redirect("bookingsammry")

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
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
            link=f"/admin/app/history/?order_id={order_id}"
        )
    except Exception as e:
        print(f"[notification error] {e}")

    messages.success(request, "Return approved successfully.")
    return redirect("bookingsammry")

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
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
    all_services = Services.objects.all()
    return render(request, 'services.html', {'services': all_services})

from django.utils import timezone
@transaction.atomic
def userdetail(request):
    is_admin = request.user.is_superuser
    cart = Cart.objects.filter(user=request.user).first()
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
        id_proof_file = request.FILES.get("id_proof_file")

        allowed_extensions = {".png", ".jpg", ".jpeg", ".pdf"}
        if not id_proof_file:
            messages.error(request, "Please upload your ID proof.")
            return redirect("userdetail")

        file_extension = os.path.splitext(id_proof_file.name)[1].lower()
        if file_extension not in allowed_extensions:
            messages.error(request, "ID proof must be a PNG, JPG, JPEG, or PDF file.")
            return redirect("userdetail")

        if id_proof_file.size > 5 * 1024 * 1024:
            messages.error(request, "ID proof file must be below 5 MB.")
            return redirect("userdetail")

        if is_admin and not request.session.get("details_filled"):
            request.session["renter_name"] = request.POST.get("name") or request.user.username
            request.session["patient_name"] = request.POST.get("patient_name")
            request.session["phone"] = request.POST.get("phone")
            request.session["address"] = request.POST.get("address")
            request.session["pincode"] = request.POST.get("pincode")
            request.session["start_date"] = request.POST.get("start_date")
            request.session["end_date"] = request.POST.get("end_date")
            request.session["id_proof_type"] = id_proof_type
            request.session["id_proof_number"] = id_proof_number
            request.session["id_proof_file"] = default_storage.save(
                f"id_proofs/{id_proof_file.name}",
                id_proof_file,
            )
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

        order_id = generate_sequential_order_id()
        phone = request.POST.get("phone", "").strip()
        address = request.POST.get("address", "").strip()
        pincode = request.POST.get("pincode", "").strip()
        email = request.POST.get("email", "").strip()
        patient_name = request.POST.get("patient_name", "").strip()

        start_date = datetime.strptime(request.session.get("start_date"), "%Y-%m-%d").date()
        end_date = datetime.strptime(request.session.get("end_date"), "%Y-%m-%d").date()
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
                    user=request.user,
                    defaults={
                        "phone": phone,
                        "id_proof_type": id_proof_type,
                        "id_proof_number": id_proof_number,
                        "id_proof_file": id_proof_file,
                        "address_line1": address,
                        "pincode": pincode,
                        "email": email or None,
                        "patient_name": patient_name,
                    }
                )

            for ci in cart_items:
                History.objects.create(
                    user=request.user,
                    renter_name=(request.session.get("renter_name") or request.user.get_full_name() or request.user.username),
                    rental_item=ci.rental_item,
                    start_date=start_date,
                    end_date=end_date,
                    quantity=ci.quantity,
                    deposit=ci.rental_item.deposit,
                    payment_method="online",
                    order_id=order_id,
                    patient_name=(request.session.get("patient_name") or patient_name),
                    phone=(request.session.get("phone") or phone),
                    address=history_address,
                    id_proof_type=id_proof_type,
                    id_proof_number=id_proof_number,
                    id_proof_file=user_detail.id_proof_file.name if user_detail and user_detail.id_proof_file else None,
                )
            try:
                if cart:
                    cart.delete()
            except Exception:
                pass

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
        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)

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
        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
        cart_item.delete()
        return JsonResponse({'success': True})

from collections import defaultdict

def bookingsammry(request):
    rental_requests = History.objects.select_related('user', 'user__userdetail', 'rental_item').order_by('-created_at')
    if not request.user.is_staff and not request.user.is_superuser:
        rental_requests = rental_requests.filter(user=request.user)

    grouped = defaultdict(list)

    for rr in rental_requests:
        key = rr.order_id or f"SINGLE-{rr.id}"
        rr.display_order_id = key
        rr.display_item_title = rr.rental_item.title
        grouped[key].append(rr)

    booking_summaries = []

    for order_id, items in grouped.items():
        total_deposit = sum((item.deposit * item.quantity for item in items), Decimal("0"))
        id_proof_url = ""
        for item in items:
            if item.id_proof_file:
                id_proof_url = item.id_proof_file.url
                break
        if not id_proof_url:
            try:
                user_detail = items[0].user.userdetail
                if user_detail.id_proof_file:
                    id_proof_url = user_detail.id_proof_file.url
            except Exception:
                id_proof_url = ""

        booking_summaries.append({
            "order_id": order_id,
            "date": items[0].start_date,
            "items": items,
            "total_deposit": total_deposit,
            "customer": items[0].user if request.user.is_staff or request.user.is_superuser else None,
            "id_proof_url": id_proof_url,
        })

    returned_order_ids = (
        rental_requests
        .filter(is_returned=True)
        .values_list('order_id', flat=True)
        .distinct()
    )

    return render(
        request,
        "bookingsammry.html",
        {
             "booking_summaries": booking_summaries,
            "returned_order_ids": returned_order_ids,
        },
    )


@login_required
def mark_returned(request, rental_id, item_id):
    rr = get_object_or_404(History, id=rental_id, rental_item_id=item_id, user=request.user)
    
    if not rr.is_return_requested:
        rr.is_return_requested = True
        rr.save()

        admin_email = getattr(settings, 'ADMIN_EMAIL', None)
        subject = f'Return Request from {request.user.username}'
        print(f"[email suppressed] To: {admin_email} Subject: {subject} User: {request.user.email} Item: {rr.rental_item}")

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True})

    return redirect('bookingsammry')

def view_rental(request, rental_id):
    rentals = History.objects.all()
    if not (request.user.is_staff or request.user.is_superuser):
        rentals = rentals.filter(user=request.user)

    rental = get_object_or_404(rentals, id=rental_id)
    related_rentals = rentals.filter(order_id=rental.order_id).select_related("rental_item")

    item_totals = []
    total_rent = 0
    total_deposit = 0
    total_quantity = 0

    for rr in related_rentals:
        rent = rr.total_rent
        deposit = rr.deposit * rr.quantity

        item_totals.append({
            "title": rr.rental_item.title,
            "quantity": rr.quantity,
            "price_per_day": rr.rental_item.price_per_day,
            "days": rr.rental_days,
            "rent": rent,
            "deposit": deposit,
            "total": rent,
        })

        total_rent += rent
        total_deposit += deposit
        total_quantity += rr.quantity

    start_date = rental.start_date
    end_date = rental.billing_end_date
    total_days = (end_date - start_date).days + 1
    delivery_option = rental.delivery_option
    delivery_charge = rental.delivery_charge if delivery_option == "delivery" else 0
    total_amount = total_rent + total_deposit + delivery_charge
    user_detail = UserDetail.objects.filter(user=rental.user).first()

    context = {
        "order_id": rental.order_id,
        "date": rental.created_at.date(),
        "rental": rental,
        "patient_name": rental.patient_name,
        "user_detail": user_detail,
        "rent_start_date": start_date,
        "rent_end_date": end_date,
        "total_days": total_days,
        "return_date": end_date,
        "item_totals": item_totals,
        "total_quantity": total_quantity,
        "total_rent": total_rent,
        "total_deposit": total_deposit,
        "delivery_charge": delivery_charge,
        "delivery_option": delivery_option,
        "total_amount": total_amount,
        "payment_mode": "Online Payment",
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
    if not (request.user.is_staff or request.user.is_superuser):
        rentals = rentals.filter(user=request.user)

    if not rentals.exists():
        messages.error(request, "Order not found or already returned.")
        return redirect("bookingsammry")

    current_end_date = rentals.first().billing_end_date
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

        for rr in rentals:
            rr.extended_end_date = new_date
            rr.save()

        try:
            send_notification(
                title=f"Return Date Extended for {order_id}",
                message=(
                    f"User {request.user.username} extended return date for order {order_id} "
                    f"to {new_date.strftime('%Y-%m-%d')}."
                ),
                notification_type='info',
                link=f"/admin/app/history/?order_id={order_id}"
            )
        except Exception as e:
            print(f"[notification extend return error] {e}")

        messages.success(request, f"Return date extended to {new_date.strftime('%d %b %Y')}. Charges have been updated.")
        return redirect("bookingsammry")

    item_totals = []
    for rr in rentals:
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
        "delivery_charge": rentals.first().delivery_charge,
        "order": rentals.first(),
    }
    return render(request, "extend_return.html", context)

@login_required
@transaction.atomic

def return_order(request, order_id):
    donate_deposit = request.GET.get("donate_deposit") == "true"
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
    if not (request.user.is_staff or request.user.is_superuser):
        rentals = rentals.filter(user=request.user)

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

    if request.user.is_staff or request.user.is_superuser:
        for index, rr in enumerate(rental_rows):
            rr.is_return_requested = False
            rr.is_returned = True
            rr.status = "approved"
            rr.actual_return_date = timezone.localdate()
            rr.deposit_donated = donate_deposit
            rr.donation_amount = donation_amount if index == 0 else Decimal("0")
            rr.donation_comment = donation_comment if index == 0 else ""
            update_fields = [
                "is_return_requested",
                "is_returned",
                "status",
                "actual_return_date",
                "deposit_donated",
                "donation_amount",
                "donation_comment",
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
                link=f"/admin/app/history/?order_id={order_id}"
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
        if donate_deposit:
            rr.save(update_fields=[
                "is_return_requested",
                "status",
                "deposit_donated",
                "donation_amount",
                "donation_comment",
            ])
        else:
            rr.save(update_fields=[
                "is_return_requested",
                "status",
                "deposit_donated",
                "donation_amount",
                "donation_comment",
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
            link=f"/admin/app/history/?order_id={order_id}"
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

    if not (request.user.is_staff or request.user.is_superuser):
        rentals = rentals.filter(user=request.user)

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
            link=f"/admin/app/history/?order_id={order_id}"
        )
    except Exception as e:
        print(f"[notification cancel error] {e}")

    messages.success(request, "Booking cancelled successfully.")
    return redirect('bookingsammry')

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def admin_notifications(request):
    from .models import Notification
    notifications = Notification.objects.all()
    unread_count = notifications.filter(is_read=False).count()
    return render(request, 'notifications/list.html', {
        'notifications': notifications,
        'unread_count': unread_count,
    })

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def mark_notification_read(request, notification_id):
    from .models import Notification
    notification = get_object_or_404(Notification, id=notification_id)
    notification.is_read = True
    notification.save(update_fields=['is_read'])
    next_url = request.GET.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('admin_notifications')

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def mark_all_notifications_read(request):
    from .models import Notification
    Notification.objects.filter(is_read=False).update(is_read=True)
    next_url = request.GET.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('admin_notifications')

@login_required
@transaction.atomic
def return_cart_item(request, cart_item_id):

    rr = get_object_or_404(History.objects.select_for_update(),id=cart_item_id,user=request.user)

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
            link=f"/admin/app/history/{rr.id}/change/"
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
    if not (request.user.is_staff or request.user.is_superuser):
        rentals = rentals.filter(user=request.user)

    if not rentals.exists():
        messages.error(request, "Return receipt not available.")
        return redirect("bookingsammry")

    rental = rentals.first()
    user_detail = UserDetail.objects.filter(user=rental.user).first()

    grouped_items = defaultdict(lambda: {
        "title": "",
        "quantity": 0,
        "deposit": 0,
        "price_per_day": 0,
        "days": 0,
        "total_rent": 0,
    })

    for rr in rentals:
        key = rr.rental_item.id

        grouped_items[key]["title"] = rr.rental_item.title
        grouped_items[key]["quantity"] += rr.quantity
        grouped_items[key]["deposit"] += rr.deposit * rr.quantity
        grouped_items[key]["price_per_day"] = rr.rental_item.price_per_day
        grouped_items[key]["days"] = rr.rental_days             
        grouped_items[key]["total_rent"] += rr.total_rent      

    item_totals = list(grouped_items.values())
    total_quantity = sum(i["quantity"] for i in item_totals)
    total_deposit = sum(i["deposit"] for i in item_totals)
    total_rent = sum(rr.total_rent for rr in rentals)
    donation_amount = sum((rr.donation_amount for rr in rentals), Decimal("0"))
    donation_comment = next((rr.donation_comment for rr in rentals if rr.donation_comment), "")
    delivery_charge = rental.delivery_charge
    return_pickup_charge = rental.return_pickup_charge
    refund_amount = max(total_deposit - donation_amount - delivery_charge - return_pickup_charge, Decimal("0"))
    total_amount = total_rent + delivery_charge + return_pickup_charge + donation_amount

    context = {
        "order": rental,          
        "rental": rental,
        "order_id": order_id,
        "return_date": rental.actual_return_date,
        "user_detail": user_detail,
        "patient_name": rental.patient_name,
        "item_totals": item_totals,
        "total_quantity": total_quantity,
        "total_rent": total_rent,
        "total_deposit": total_deposit,
        "donation_amount": donation_amount,
        "donation_comment": donation_comment,
        "total_amount": total_amount,
        "refund_amount": refund_amount,
        "delivery_option": rental.delivery_option,
        "delivery_charge": rental.delivery_charge,
        "return_pickup_charge": rental.return_pickup_charge,
    }

    return render(request, "return_receipt.html", context)
