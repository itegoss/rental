from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from .models import Payment

from django.core.files.base import ContentFile
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from io import BytesIO


def send_overdue_email(user, rental):
    subject = "Rental Overdue Notice"
    message = (
        f"Dear {user.get_full_name() or user.username},\n\n"
        f"This is a reminder that your rental (ID: {rental.id}) was due on {rental.end_date} "
        "and is now overdue. Please return the rental item as soon as possible or contact us if you need assistance.\n\n"
        "Thank you,\nQuickNest Team"
    )
    recipient_list = [user.email]
    email_from = settings.DEFAULT_FROM_EMAIL

    send_mail(
        subject,
        message,
        email_from,
        recipient_list,
        fail_silently=False
    )


def generate_receipt(order):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50

    p.setFont("Helvetica-Bold", 16)
    p.drawString(200, y, "Rental Order Receipt")
    y -= 40

    p.setFont("Helvetica", 12)
    p.drawString(50, y, f"Order ID: {order.order_id}"); y -= 25
    p.drawString(50, y, f"User: {order.user.username}"); y -= 25
    p.drawString(50, y, f"Email: {order.user.email}"); y -= 25
    p.drawString(50, y, f"Item: {order.rental_item.title}"); y -= 25
    p.drawString(50, y, f"Start Date: {order.start_date}"); y -= 25
    p.drawString(50, y, f"End Date: {order.end_date}"); y -= 25
    p.drawString(50, y, f"Rental Days: {order.rental_days}"); y -= 25
    p.drawString(50, y, f"Per Day Rent: ₹{order.rental_item.price_per_day}"); y -= 25
    p.drawString(50, y, f"Total Amount: {order.total_amount}"); y -= 25
    p.drawString(50, y, f"Payment Method: {order.payment_method}")

    p.showPage()
    p.save()
    buffer.seek(0)

    # Return as file content
    return ContentFile(buffer.getvalue(), f"receipt_{order.order_id}.pdf")


from .models import UserDetail   # ✅ import user detail


def generate_receipt(order):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50

    # Title
    p.setFont("Helvetica-Bold", 16)
    p.drawString(200, y, "Rental Order Receipt")
    y -= 40

    # Basic Order Info
    p.setFont("Helvetica", 12)
    p.drawString(50, y, f"Order ID: {order.order_id}"); y -= 25
    p.drawString(50, y, f"User: {order.user.username}"); y -= 25
    p.drawString(50, y, f"Email: {order.user.email}"); y -= 25
    p.drawString(50, y, f"Item: {order.rental_item.title}"); y -= 25
    p.drawString(50, y, f"Start Date: {order.start_date}"); y -= 25
    p.drawString(50, y, f"End Date: {order.end_date}"); y -= 25
    p.drawString(50, y, f"Rental Days: {order.rental_days}"); y -= 25
    p.drawString(50, y, f"Per Day Rent: ₹{order.rental_item.rent_per_day}"); y -= 25
    p.drawString(50, y, f"Total Amount: ₹{order.total_amount}"); y -= 25
    p.drawString(50, y, f"Payment Method: {order.payment_method}"); y -= 40

    # ✅ User Detail Section
    try:
        details = UserDetail.objects.get(user=order.user)
        p.setFont("Helvetica-Bold", 14)
        p.drawString(50, y, "User Details")
        y -= 30
        p.setFont("Helvetica", 12)
        p.drawString(50, y, f"Phone: {details.phone or '—'}"); y -= 25
        p.drawString(50, y, f"Address: {details.address_line1 or ''}, {details.city or ''}"); y -= 25
        p.drawString(50, y, f"State: {details.state or '—'}, Pincode: {details.pincode or '—'}"); y -= 25
        p.drawString(50, y, f"Aadhar: {details.aadhar or '—'}"); y -= 25
    except UserDetail.DoesNotExist:
        p.setFont("Helvetica-Bold", 14)
        p.drawString(50, y, "User Details Not Found")
        y -= 30

    p.showPage()
    p.save()
    buffer.seek(0)

    return ContentFile(buffer.getvalue(), f"receipt_{order.order_id}.pdf")


import datetime
from django.db.models import Max
from .models import Payment  

def generate_order_id():
    today = datetime.date.today().strftime("%Y%m")
    
    last_order = Payment.objects.filter(order_id__startswith=f"ORD{today}") \
                                .aggregate(max_id=Max("order_id"))["max_id"]

    if last_order:
        last_number = int(last_order[-3:])
        new_number = str(last_number + 1).zfill(3)
    else:
        new_number = "001"

    return f"ORD{today}{new_number}"
