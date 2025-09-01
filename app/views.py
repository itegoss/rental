from datetime import datetime
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout as auth_logout
from django.contrib.auth.hashers import make_password 
from django.contrib.auth.models import User
from django.shortcuts import render, redirect, get_object_or_404
import re
from .models import RentalItem, RentalRequest, UserDetail
from decimal import Decimal
from django.core.mail import send_mail 
from django.utils import timezone
from datetime import timedelta
from django.conf import settings
import razorpay
from .utils import send_overdue_email
from .utils import generate_order_id

from django.db import transaction


def index(request):
    today = timezone.now().date()
    rentals = RentalRequest.objects.filter(status='approved')

    for rental in rentals:
      if rental.end_date - timedelta(days=1) == today and not rental.is_reminder_sent:
        rent_days = rental.rental_days   # ✅ Correct way
        send_reminder_email(rental.user, rental)
        rental.is_reminder_sent = True
        rental.save(update_fields=['is_reminder_sent'])


        # Overdue: after end date
        if rental.end_date < today and not rental.is_overdue_email_sent:
            send_overdue_email(rental.user, rental)
            rental.is_overdue_email_sent = True
            rental.save(update_fields=['is_overdue_email_sent'])

    return render(request, 'index.html')


# Logout view
def logout(request):
    auth_logout(request)
    return redirect('signin')

# Signup view
def signup(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')

        # Basic checks
        if not all([username, email, password, confirm_password]):
            messages.error(request, "Please fill all fields.")
            return redirect('signup')

        if password != confirm_password:
            messages.error(request, "Password and confirm password do not match.")
            return redirect('signup')

        if len(password) < 6:
            messages.error(request, "Password must be at least 6 characters long.")
            return redirect('signup')

        if username[0].isdigit():
            messages.error(request, "Username should not start with a digit.")
            return redirect('signup')

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            messages.error(request, "Enter a valid email address.")
            return redirect('signup')

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already taken.")
            return redirect('signup')

        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already registered.")
            return redirect('signup')

        # Password strength checks
        if not re.search(r'[A-Z]', password):
            messages.error(request, "Password must contain at least one uppercase letter.")
            return redirect('signup')

        if not re.search(r'[a-z]', password):
            messages.error(request, "Password must contain at least one lowercase letter.")
            return redirect('signup')

        if not re.search(r'\d', password):
            messages.error(request, "Password must contain at least one digit.")
            return redirect('signup')

        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            messages.error(request, "Password must contain at least one special character.")
            return redirect('signup')

        # Create user
        user = User.objects.create_user(username=username, email=email, password=password)
        user.save()
        messages.success(request, "Account created successfully! Please log in.")
        return redirect('signin')

    return render(request, 'signup.html')
# Signin view
def signin(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        if not username or not password:
            messages.error(request, "All fields are required.", extra_tags="signin")
            return redirect('signin')

        try:
            user = User.objects.get(username=username)

            # Check if password is only digits
            if password.isdigit():
                messages.error(request, "Password should contain alphabets or special characters.", extra_tags="signin")
                return redirect('signin')

            # Authenticate user
            authenticated_user = authenticate(request, username=username, password=password)
            if authenticated_user is not None:
                login(request, authenticated_user)
                messages.success(request, "Login successful.", extra_tags="signin")
                return redirect('index')
            else:
                messages.error(request, "Invalid username or password.", extra_tags="signin")
                return redirect('signin')
        except User.DoesNotExist:
            messages.error(request, "User not found.", extra_tags="signin")
            return redirect('signin')

    return render(request, 'signin.html')


# Forgot password (step 1: enter username)
def forgot(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        try:
            user = User.objects.get(username=username)
            return redirect('resetpass', username=username)
        except User.DoesNotExist:
            messages.error(request, "Username does not exist.")
    return render(request, 'forgot.html')

# Password reset view
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


# List all items
def items(request):
    items = RentalItem.objects.all()
    return render(request, 'items.html', {'items': items})
from datetime import datetime, date
from datetime import datetime, date  # Add date import

def buy(request, item_id):
    item = get_object_or_404(RentalItem, id=item_id)
    today = date.today()

    if request.method == "POST":
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')

        # ✅ Debug prints (safe inside POST only)
        print("START STR:", start_date_str)
        print("END STR:", end_date_str)

        if not (start_date_str and end_date_str):
            messages.error(request, "Please select start and end dates.", extra_tags="buy")
            return redirect('buy', item_id=item_id)

        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

            # ✅ More debug prints
            print("START DATE OBJECT:", start_date)
            print("END DATE OBJECT:", end_date)

            # Check 1: start date not in the past
            if start_date < today:
                messages.error(request, "Start date cannot be in the past.", extra_tags="buy")
                return redirect('buy', item_id=item_id)

            # Check 2: end date not in the past
            if end_date < today:
                messages.error(request, "End date cannot be in the past.", extra_tags="buy")
                return redirect('buy', item_id=item_id)

            # Check 3: end date >= start date
            if end_date < start_date:
                messages.error(request, "End date cannot be before start date.", extra_tags="buy")
                return redirect('buy', item_id=item_id)

            rent_days = (end_date - start_date).days + 1  # inclusive
            rent_amount = rent_days * item.price_per_day
            amount_in_paise = int(rent_amount * 100)

            # Save in session
            request.session['start_date'] = start_date_str
            request.session['end_date'] = end_date_str
            request.session['item_id'] = item_id
            request.session['amount_in_paise'] = amount_in_paise

            return redirect('select_delivery', pk=item_id)

        except Exception as e:
            messages.error(request, f"Invalid date format: {e}", extra_tags="buy")
            return redirect('buy', item_id=item_id)

    # For GET request, render the form
    return render(request, "buy.html", {"item": item, "today": today})


def select_delivery(request, pk):
    item = get_object_or_404(RentalItem, pk=pk)
    amount_in_paise = request.session.get('amount_in_paise', 0)
    if request.method == 'POST':
        delivery_option = request.POST.get('delivery_option')
        # Save delivery option in session
        request.session['delivery_option'] = delivery_option
        return redirect(f"/userdetail/?item_id={pk}")

    return render(request, 'select_delivery.html', {
        'item': item,
        'amount_in_paise': amount_in_paise
    })


def userdetail(request):
    # Fetch amount in paise from session (default 0)
    raw_amount = request.session.get('amount_in_paise', 0)
    try:
        amount_in_paise = int(raw_amount) if raw_amount else 0
    except (ValueError, TypeError):
        amount_in_paise = 0

    rent_amount = amount_in_paise / 100

    # Get item from session
    item_id = request.session.get('item_id')
    item = get_object_or_404(RentalItem, id=item_id) if item_id else None

    # Delivery option
    delivery_option = (
        request.session.get('delivery_option') or
        request.POST.get('delivery_option') or
        request.GET.get('delivery_option')
    )
    delivery_charge = 50 if delivery_option == 'Delivery' else 0
    total_amount = rent_amount + delivery_charge

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        aadhar = request.POST.get('aadhar', '').strip()
        address = request.POST.get('address', '').strip()

        # Validation
        if not all([name, email, phone, aadhar, address]):
            messages.error(request, "Please fill in all fields.")
        elif not phone.isdigit() or len(phone) != 10:
            messages.error(request, "Phone number must be 10 digits and numeric.")
        elif not aadhar.isdigit() or len(aadhar) != 12:
            messages.error(request, "Aadhaar number must be 12 digits and numeric.")
        elif any(char.isdigit() for char in address):
            messages.error(request, "Address cannot contain digits.")
        else:
    # Create rental with actual selected dates from session
            from datetime import datetime

            start_date_str = request.session.get('start_date')
            end_date_str = request.session.get('end_date')

            if not start_date_str or not end_date_str:
                messages.error(request, "Rental dates missing. Please select again.")
                return redirect('buy', item_id=item.id)

            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

            rental = RentalRequest.objects.create(
                user=request.user,
                rental_item=item,
                start_date=start_date,
                end_date=end_date,
                payment_method='online',  # default, updated in paymentmethod if COD
                total_amount=total_amount
            )

            # Save user details
            UserDetail.objects.update_or_create(
                user=request.user,
                defaults={
                    'phone': phone,
                    'aadhar': aadhar,
                    'email': email,
                    'address_line1': address,
                    'city': '',
                    'state': '',
                    'pincode': '000000',
                }
            )


            # Save session data
            request.session['user_name'] = name
            request.session['user_email'] = email
            request.session['user_phone'] = phone
            request.session['user_aadhar'] = aadhar
            request.session['user_address'] = address
            request.session['delivery_option'] = delivery_option
            request.session['rental_id'] = rental.id

            # Redirect to paymentmethod view
            return redirect('paymentmethod')

    # GET request or validation failed
    return render(request, 'userdetail.html', {
        'item': item,
        'rent_amount': rent_amount,
        'delivery_charge': delivery_charge,
        'total_amount': total_amount,
        'delivery_option': delivery_option,
    })

@transaction.atomic
def paymentmethod(request):
    rental_id = request.session.get('rental_id')
    if not rental_id:
        messages.error(request, "Rental not found. Please fill your details again.")
        return redirect('userdetail')

    rental = get_object_or_404(RentalRequest, id=rental_id)
    total_amount = rental.total_amount

    # Create or get existing Payment object for the rental
    payment_obj, created = Payment.objects.get_or_create(
        rental_request=rental,
        defaults={
            'payment_status': 'PENDING',
            'order_id': generate_order_id()  # Make sure your generate_order_id() returns a unique ID
        }
    )

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method')

        if payment_method == 'online':
            # Redirect to payment view for Razorpay processing
            return redirect('payment', rental_id=rental.id)

        elif payment_method == 'cod':
            rental.payment_method = 'cod'
            rental.save()

            # Update payment object for COD
            payment_obj.payment_status = 'SUCCESS'
            payment_obj.payment_id = None
            payment_obj.razorpay_order_id = None
            payment_obj.save()

            # ✅ Send email confirmation for COD
            recipient_email = rental.user.email
            if recipient_email:
                subject = "Booking Confirmed - Cash on Delivery"
                message = (
                    f"Dear {rental.user.get_full_name() or rental.user.username},\n\n"
                    f"Your booking has been confirmed!\n\n"
                    f"Item: {rental.rental_item.title}\n"
                    f"Total Amount: ₹{total_amount}\n"
                    f"Payment Method: Cash on Delivery\n\n"
                    f"Please come and collect your item from our service center.\n\n"
                    "Thank you for choosing Sick Bed Services!"
                )
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [recipient_email],
                    fail_silently=False,
                )

            messages.success(request, "Order placed successfully with Cash on Delivery! Confirmation email sent.")
            return redirect('success', rental_id=rental.id)

        else:
            messages.error(request, "Please select a valid payment method.")

    return render(request, 'paymentmethod.html', {'total_amount': total_amount})


from .models import Payment, RentalRequest
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
@csrf_exempt

def success(request, rental_id):
    if request.method == "GET":
        razorpay_payment_id = request.GET.get('razorpay_payment_id')
        request.session.pop('razorpay_order_id', None)
        razorpay_signature = request.GET.get('razorpay_signature')

        rental_request = get_object_or_404(RentalRequest, id=rental_id)

        # ✅ Fetch existing Payment record
        try:
          payment = Payment.objects.filter(rental_request=rental_request).order_by('-payment_date').first()
        except Payment.DoesNotExist:
            return HttpResponse("Payment record not found", status=404)

        # ✅ Update payment details only
        payment.payment_id = razorpay_payment_id
        payment.payment_status = "Success"
        payment.save()

        # ✅ Always use DB-generated order_id
        order_id = payment.order_id  

        # Approve rental request
        rental_request.status = "approved"
        rental_request.save()

        # ----------- ✉️ Send Email to the User -----------
        subject = "Sick Bed Services Booking Confirmed "
        message = f"""
Dear {rental_request.user.first_name or rental_request.user.username},

Thank you for your booking with Sick Bed Services! 

Here are your booking details:

Item: {rental_request.rental_item.title}
 Rental Duration: {rental_request.start_date} to {rental_request.end_date}
 Order ID: {order_id}
 Payment ID: {razorpay_payment_id}

Your booking has been successfully confirmed. You can now take the item or wait for delivery as per the schedule.

If you have any questions, feel free to contact our support team.

Regards,  
Sick Bed Services Team
        """
        from_email = settings.DEFAULT_FROM_EMAIL
        recipient_list = [rental_request.user.email]

        try:
            send_mail(subject, message, from_email, recipient_list)
        except Exception as e:
            print("Email failed:", e)

        # ----------- Render Success Page -----------
        return render(request, "success.html", {
            "rental": rental_request,
            "payment_id": razorpay_payment_id,
            "order_id": order_id,
            "signature": razorpay_signature,
            "message": "Thank you for your booking! Your payment has been received successfully."
        })

    return HttpResponse("Method not allowed", status=405)



def about(request):
    return render(request, 'about.html')




from django.template.loader import render_to_string
from django.core.mail import EmailMessage
def send_reminder_email(user, rental):
    subject = 'Reminder: Your Rental Ends Tomorrow - Sick Bed Services'
    recipient_email = user.email

    # direct inline HTML message
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

    email = EmailMessage(subject, message, from_email=None, to=[recipient_email])
    email.content_subtype = 'html'  # important: render as HTML

    try:
        email.send()
        rental.is_reminder_sent = True
        rental.save()
    except Exception as e:
        print("Reminder Email Failed:", e)

def send_overdue_emails(user, rental):
    subject = 'Overdue Rental Notice - Sick Bed Services'
    recipient_email = user.email

    context = {
        'user': user,
        'rental_item': rental.rental_item,
        'end_date': rental.end_date
    }

    message = render_to_string('emails/overdue.html', context)

    email = EmailMessage(
        subject=subject,
        body=message,
        from_email=None,  
        to=[recipient_email]
    )
    email.content_subtype = 'html'

    try:
        email.send()
        print(f"Overdue notice sent to {recipient_email}")
        rental.is_overdue_email_sent = True
        rental.save()
    except Exception as e:
        print(f"Overdue email failed for {recipient_email}: {str(e)}")

def payment(request, rental_id):
    rental = get_object_or_404(RentalRequest, id=rental_id)
    item = rental.rental_item
    user = request.user

    # Rent calculation
    rent_days = (rental.end_date - rental.start_date).days
    total_amount = int(rent_days * item.price_per_day)  # in rupees

    # Razorpay requires amount in paise
    razorpay_amount = total_amount * 100

    # Razorpay client
    client = razorpay.Client(auth=("rzp_test_wH0ggQnd7iT3nB", "eZseshY3oSsz2fcHZkTiSlCm"))

    # Create Razorpay Order
    data = {
        "amount": razorpay_amount,
        "currency": "INR",
        "receipt": f"rental_rcpt_{rental.id}",
        "payment_capture": 1
    }
    razorpay_order = client.order.create(data=data)

    # Generate custom order_id before creating Payment object
    today = timezone.now().strftime("%Y%m%d")  # daily prefix
    prefix = f"ORD{today}"

    last_order = (
        Payment.objects.filter(order_id__startswith=prefix)
        .order_by("order_id")
        .last()
    )

    if last_order:
        match = re.search(r"(\d{3})$", last_order.order_id)
        if match:
            last_number = int(match.group(1))
            new_number = str(last_number + 1).zfill(3)
        else:
            new_number = "001"
    else:
        new_number = "001"

    order_id = f"{prefix}{new_number}"

    # Save Payment object in DB with explicit order_id
    payment_obj = Payment.objects.create(
        rental_request=rental,
        razorpay_order_id=razorpay_order["id"],  
        payment_status="PENDING",
        order_id=order_id  # Explicitly set the order_id
    )

    # Context for template
    context = {
        "user": user,
        "item_name": item.title,
        "total_amount": total_amount,
        "razorpay_amount": razorpay_amount,
        "razorpay_order_id": razorpay_order["id"],
        "payment": payment_obj,  
        "custom_order_id": payment_obj.order_id,
        "rental_id": rental.id,
        "razorpay_key": "rzp_test_wH0ggQnd7iT3nB",
    }
    return render(request, "payment.html", context)



def generate_order_id():
    today = timezone.now().strftime("%Y%m%d")
    prefix = f"ORD{today}"

    last_order = Payment.objects.filter(order_id__startswith=prefix).order_by("order_id").last()
    
    if last_order:
        match = re.search(r"(\d{3})$", last_order.order_id)
        if match:
            last_number = int(match.group(1))
            new_number = str(last_number + 1).zfill(3)
        else:
            new_number = "001"
    else:
        new_number = "001"

    return f"{prefix}{new_number}"

from reportlab.pdfgen import canvas
from io import BytesIO
from django.core.files.base import ContentFile

def generate_receipt(rental):
    buffer = BytesIO()
    c = canvas.Canvas(buffer)
    c.setFont("Helvetica", 12)
    
    c.drawString(50, 800, f"Order ID: {rental.order_id}")
    c.drawString(50, 780, f"Customer: {rental.user.username}")
    c.drawString(50, 760, f"Item: {rental.rental_item.title}")
    c.drawString(50, 740, f"Rental Duration: {rental.start_date} to {rental.end_date}")
    c.drawString(50, 720, f"Total Amount: ₹{rental.total_amount}")
    c.drawString(50, 700, f"Payment Method: {rental.payment_method}")
    c.drawString(50, 680, "Thank you for renting with Sick Bed Services!")
    
    c.showPage()
    c.save()
    
    buffer.seek(0)
    file_name = f"receipt_{rental.order_id}.pdf"
    rental.receipt.save(file_name, ContentFile(buffer.read()))
    buffer.close()
    rental.save()



def approve_order(request, order_id):
    order = get_object_or_404(RentalRequest, order_id=order_id)

    # Approve the order
    order.status = "approved"
    order.save()

    # Generate receipt if not exists
    if not order.receipt:
        order.receipt.save(
            f"receipt_{order.order_id}.pdf",
            generate_receipt(order)
        )

    return redirect("order_detail", order_id=order.order_id)


def terms(request):
    return render(request, 'terms.html')


from .models import Services
def services(request):
    all_services = Services.objects.all()
    return render(request, 'services.html', {'services': all_services})