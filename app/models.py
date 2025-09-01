from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
import datetime
from django.db.models import Max
import re
from django.db import models

import uuid

class RentalItem(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField()
    price_per_day = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to='rental_items/', blank=True, null=True)
    rent_per_day = models.IntegerField(default=0)
    deposit = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00,
        help_text="Security deposit amount set by admin"
    )
    total_quantity = models.PositiveIntegerField(default=1)
    available_quantity = models.PositiveIntegerField(default=1)
    available = models.BooleanField(default=True)
    next_available_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.title

    def is_available(self):
        return self.available_quantity > 0

    def update_availability(self):
        if self.available_quantity == 0:
            self.available = False
            if not self.next_available_date:
                self.next_available_date = timezone.now().date() + timedelta(days=7)
        else:
            self.available = True
            self.next_available_date = None
        self.save()

    # 🔹 NEW: stock status
    def stock_status(self):
        if self.available_quantity > 1:
            return f"{self.available_quantity} left"
        elif self.available_quantity == 1:
            return "Only 1 left!"
        else:
            return "Out of stock"


#  User Profile (extended from User)
class UserDetail(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone = models.CharField(max_length=15, blank=True, null=True)
    email = models.EmailField(max_length=254, blank=True, null=True)  # ← correct line added
    address_line1 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    pincode = models.CharField(max_length=10, blank=True, null=True)
    aadhar = models.CharField(max_length=12, blank=True, null=True)

    def __str__(self):
        return self.user.username


class RentalRequest(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rental_item = models.ForeignKey("RentalItem", on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
    is_reminder_sent = models.BooleanField(default=False)
    is_overdue_email_sent = models.BooleanField(default=False)
    deposit = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    order_id = models.CharField(max_length=100, blank=True, null=True)
    payment_method = models.CharField(
        max_length=50,
        choices=[('online', 'Online'), ('cod', 'Cash on Delivery')]
    )
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')],
        default='pending'
    )
    receipt = models.FileField(upload_to='receipts/', blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} - {self.rental_item.title}"

    @property
    def rental_days(self):
     if self.start_date and self.end_date:
        return (self.end_date - self.start_date).days + 1
     return 0


    @property
    def per_day_rent(self):
        if self.total_amount and self.rental_days:
            return round(self.total_amount / self.rental_days, 2)
        return None

    @property
    def total_rent(self):
     return self.rental_days * self.rental_item.price_per_day
    
def save(self, *args, **kwargs):
    is_new = self._state.adding

    if not self.order_id:
        date_str = timezone.now().strftime('%Y%m')  # YYYYMM
        prefix = f'ORD{date_str}'
        last_order = RentalRequest.objects.filter(
            order_id__startswith=prefix,
            order_id__regex=r'^ORD\d{6}\d{3}$'  # Only numeric suffix
        ).order_by('-order_id').first()

        if last_order and last_order.order_id:
            last_number = int(last_order.order_id[-3:])  # last 3 digits
            new_number = str(last_number + 1).zfill(3)
        else:
            new_number = "001"
        self.order_id = f"{prefix}{new_number}"

    # ✅ always recalc total_amount
    self.total_amount = self.total_rent

    super().save(*args, **kwargs)

    # Reduce stock only when new and approved
    if is_new and self.status == 'approved':
        item = self.rental_item
        if item.available_quantity > 0:
            item.available_quantity -= 1
            item.update_availability()

    # Auto-generate receipt when approved
    if self.status == "approved" and not self.receipt:
        from .utils import generate_receipt
        self.receipt.save(
            f"receipt_{self.order_id}.pdf",
            generate_receipt(self),
            save=True
        )


class Payment(models.Model):
    rental_request = models.ForeignKey("RentalRequest", on_delete=models.CASCADE)
    order_id = models.CharField(max_length=20, unique=True, editable=False)  # Custom ID
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    payment_id = models.CharField(max_length=100, blank=True, null=True)  # Razorpay payment ID
    payment_status = models.CharField(
        max_length=20,
        choices=[
            ("PENDING", "Pending"),
            ("SUCCESS", "Success"),
            ("FAILED", "Failed"),
        ],
        default="PENDING",
    )
    payment_date = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.order_id:
            # ✅ Format: ORDYYYYMM### (Year + Month + 3-digit counter)
            today = timezone.now().strftime("%Y%m")
            prefix = f"ORD{today}"

            # Find last order for this month
            last_order = (
                Payment.objects.filter(order_id__startswith=prefix)
                .order_by("order_id")
                .last()
            )

            if last_order:
                try:
                    last_number = int(last_order.order_id[-3:])  # last 3 digits
                    new_number = str(last_number + 1).zfill(3)
                except (ValueError, IndexError):
                    new_number = "001"
            else:
                new_number = "001"

            self.order_id = f"{prefix}{new_number}"

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order_id} - {self.payment_status}"



def generate_order_id():
    today = datetime.date.today().strftime("%Y%m")
    from .models import Payment  
    
    last_order = Payment.objects.filter(order_id__startswith=f"ORD{today}") \
                                .aggregate(max_id=Max("order_id"))["max_id"]

    if last_order:
     
        last_number = int(last_order[-3:])
        new_number = str(last_number + 1).zfill(3)
    else:
        new_number = "001"

    return f"ORD{today}{new_number}"



class Services(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    image = models.ImageField(upload_to='service_images/')
    contact_number = models.CharField(max_length=15)
    
    def __str__(self):
        return self.title
