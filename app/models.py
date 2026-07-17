from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils import timezone
from datetime import timedelta
import datetime
from django.db.models import Max, Sum, Q
from django.db.models.signals import post_save
from django.dispatch import receiver
import re


def validate_id_proof_file_size(value):
    max_size = 5 * 1024 * 1024
    if value.size > max_size:
        raise ValidationError("ID proof file must be below 5 MB.")


class Inventory(models.Model):
    title = models.CharField(max_length=255, unique=True)
    description = models.TextField()
    price_per_day = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to='rental_items/', blank=True, null=True)

    deposit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00
    )

    total_quantity = models.PositiveIntegerField(default=1)

    # ✅ IMPORTANT FIELDS
    available_quantity = models.PositiveIntegerField(default=0)
    booked_quantity = models.PositiveIntegerField(default=0)

    available = models.BooleanField(default=True)
    next_available_date = models.DateField(null=True, blank=True)
    
    # Item tracking fields
    item_qty = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    donation = models.BooleanField(default=False)
    donor_name = models.CharField(max_length=200, blank=True, null=True)
    donor_contact = models.CharField(max_length=30, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

    # 🔥 UI STATUS
    def stock_status(self):
        if self.available_quantity == 0:
            return "Out of stock"
        elif self.available_quantity == 1:
            return "Only 1 Left"
        else:
            return f"{self.available_quantity} Available"

    def update_availability(self):
        """Recompute `available_quantity` and `booked_quantity` from approved History.

        - `booked_quantity` is the sum of quantities for approved, not-returned rentals.
        - `available_quantity` = max(total_quantity - booked_quantity, 0)
        - `available` is True when available_quantity > 0
        - `next_available_date` is cleared when items are available
        """
        from django.db.models import Sum
        from django.utils import timezone
        try:
            booked = self.rentalrequest_set.filter(status='approved', is_returned=False).aggregate(total=Sum('quantity'))['total'] or 0
            self.booked_quantity = booked
            new_available = max((self.total_quantity or 0) - booked, 0)
            self.available_quantity = new_available
            self.available = new_available > 0
            if new_available > 0:
                self.next_available_date = None
            else:
                # If nothing available, set a conservative next available date (7 days ahead)
                self.next_available_date = (timezone.now().date() + timedelta(days=7))
        except Exception:
            # If anything goes wrong, don't raise — leave values as-is
            pass
        # Persist computed availability fields so callers don't need to remember to save.
        try:
            self.save(update_fields=[
                'booked_quantity',
                'available_quantity',
                'available',
                'next_available_date'
            ])
        except Exception:
            # Best-effort save; ignore failures to avoid breaking callers.
            try:
                self.save()
            except Exception:
                pass
                       
class UserDetail(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone = models.CharField(max_length=15, blank=True, null=True)
    email = models.EmailField(max_length=254, blank=True, null=True)
    address_line1 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    pincode = models.CharField(max_length=10, blank=True, null=True)
    id_proof_type = models.CharField(max_length=20)
    id_proof_number = models.CharField(max_length=30)

    patient_name = models.CharField(max_length=200, null=True, blank=True)

    def __str__(self):
        return self.user.username

class History(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    renter_name = models.CharField(max_length=255, null=True, blank=True)
    email = models.EmailField(max_length=254, null=True, blank=True)
    phone = models.CharField(max_length=15, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    rental_item = models.ForeignKey("Inventory", on_delete=models.CASCADE, related_name='rentalrequest_set')
    start_date = models.DateField()
    end_date = models.DateField()
    extended_end_date = models.DateField(null=True, blank=True)
    actual_return_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    quantity = models.PositiveIntegerField(default=1)
    is_returned = models.BooleanField(default=False)
    is_return_requested = models.BooleanField(default=False)
    order_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    is_reminder_sent = models.BooleanField(default=False)
    is_overdue_email_sent = models.BooleanField(default=False)
    is_today_reminder_sent = models.BooleanField(default=False, null=True, blank=True)
    patient_name = models.CharField(max_length=200, null=True, blank=True)
    id_proof_type = models.CharField(max_length=20, blank=True, null=True)
    id_proof_number = models.CharField(max_length=30, blank=True, null=True)

    delivery_option = models.CharField(max_length=20, choices=[("delivery", "Delivery"), ("pickup", "Pickup")],
        blank=True, null=True)
    delivery_charge = models.DecimalField( max_digits=10, decimal_places=2, default=0)
    return_pickup_charge = models.DecimalField( max_digits=10, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=50,choices=[('online', 'Online'), ('cod', 'Cash on Delivery')])
    deposit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    deposit_donated = models.BooleanField(default=False)
    donation_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    donation_comment = models.TextField(blank=True, null=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2,blank=True,null=True)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount_remaining = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_delivery_paid = models.BooleanField(default=False)

    status = models.CharField( max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('cancelled', 'Cancelled'),
        ],
        default='pending',
        db_index=True
    )

    def __str__(self):
        return f"{self.user.username} - {self.order_id} - {self.rental_item.title}"

    @property
    def billing_end_date(self):
        return self.extended_end_date or self.end_date

    @property
    def rental_days(self):
        if self.start_date and self.billing_end_date:
            return (self.billing_end_date - self.start_date).days + 1
        return 0

    @property
    def total_rent(self):
        return self.rental_days * self.rental_item.price_per_day * self.quantity

    @property
    def refund_amount(self):
        """
        Refund = Deposit - delivery charge - return pickup charge
        If deposit was donated, refund is 0
        """
        deposit_total = self.deposit * self.quantity
        refund = deposit_total - self.donation_amount - self.delivery_charge - self.return_pickup_charge
        return max(refund, 0)

    def save(self, *args, **kwargs):
        from decimal import Decimal
        rent_dec = Decimal(str(self.total_rent or '0'))
        deposit_dec = Decimal(str(self.deposit or '0'))
        delivery_dec = Decimal(str(self.delivery_charge or '0'))
        pickup_dec = Decimal(str(self.return_pickup_charge or '0'))
        
        if not getattr(self, '_total_amount_manually_changed', False) or self.total_amount is None:
            self.total_amount = rent_dec + (deposit_dec * self.quantity) + delivery_dec + pickup_dec
        
        # Auto-update is_delivery_paid based on whether amount_paid covers rent and deposit + delivery charge (on creation only)
        if self.pk is None:
            rent_deposit_total = rent_dec + (deposit_dec * self.quantity)
            paid_dec = Decimal(str(self.amount_paid or '0'))
            if paid_dec >= (rent_deposit_total + delivery_dec):
                self.is_delivery_paid = True
            else:
                self.is_delivery_paid = False

        # Calculate remaining amount
        if not getattr(self, '_amount_remaining_manually_changed', False):
            rent_deposit_total = rent_dec + (deposit_dec * self.quantity)
            paid_dec = Decimal(str(self.amount_paid or '0'))
            mathematical_delivery_paid = max(paid_dec - rent_deposit_total, Decimal("0"))
            mathematical_delivery_paid = min(mathematical_delivery_paid, delivery_dec)

            if self.is_delivery_paid:
                unpaid_delivery = delivery_dec - mathematical_delivery_paid
                self.amount_remaining = max(self.total_amount - paid_dec - unpaid_delivery, Decimal('0'))
            else:
                self.amount_remaining = max(self.total_amount - paid_dec, Decimal('0'))
            
        super().save(*args, **kwargs)

class BookingExtension(models.Model):
    rental_request = models.ForeignKey(History, on_delete=models.CASCADE, related_name="extension_history")
    extension_no = models.PositiveIntegerField()
    extended_on = models.DateTimeField(auto_now_add=True)
    previous_return_date = models.DateField()
    new_return_date = models.DateField()
    extra_days = models.PositiveIntegerField()
    quantity = models.PositiveIntegerField(default=1)
    rent_per_day = models.DecimalField(decimal_places=2, max_digits=10)
    additional_rent = models.DecimalField(decimal_places=2, default=0, max_digits=10)
    additional_deposit = models.DecimalField(decimal_places=2, default=0, max_digits=10)
    extension_total = models.DecimalField(decimal_places=2, default=0, max_digits=10)

    class Meta:
        ordering = ["extension_no", "id"]
        unique_together = (("rental_request", "extension_no"),)

    def __str__(self):
        return f"Ext #{self.extension_no} for Order {self.rental_request.order_id}"

class Receipt(models.Model):
    RECEIPT_TYPE_CHOICES = (
        ("booking", "Booking Receipt"),
        ("return", "Return Receipt"),
    )

    rental_request = models.ForeignKey(
        'app.History',
        on_delete=models.CASCADE,
        related_name="receipts"
    )

    receipt_type = models.CharField(
        max_length=20,
        choices=RECEIPT_TYPE_CHOICES
    )

    file = models.FileField(
        upload_to="receipts/"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.receipt_type} - {self.rental_request.order_id}"

class NotifyRequest(models.Model):
    email = models.EmailField(blank=True, null=True)
    mobile = models.CharField(max_length=15, blank=True, null=True)
    item = models.ForeignKey(Inventory, on_delete=models.CASCADE, related_name='notify_requests')
    is_notified = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Notify {self.email or self.mobile} for {self.item.title}"

class Notification(models.Model):
    NOTIFICATION_TYPE_CHOICES = [
        ('booking', 'Booking'),
        ('payment', 'Payment'),
        ('return', 'Return'),
        ('late_return', 'Late Return'),
        ('cancelled', 'Cancelled'),
        ('user', 'New User'),
        ('info', 'Info'),
    ]

    type = models.CharField(max_length=30, choices=NOTIFICATION_TYPE_CHOICES, default='info')
    title = models.CharField(max_length=180)
    message = models.TextField()
    link = models.CharField(max_length=255, blank=True, null=True)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.get_type_display()})"

    @property
    def badge_class(self):
        return {
            'booking': 'primary',
            'payment': 'success',
            'return': 'info',
            'late_return': 'warning',
            'cancelled': 'danger',
            'user': 'secondary',
            'info': 'secondary',
        }.get(self.type, 'secondary')

class Payment(models.Model):
    rental_request = models.ForeignKey('app.History',on_delete=models.CASCADE,related_name="payments")
    order_id = models.CharField(max_length=20, editable=False)
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    payment_id = models.CharField(max_length=100, blank=True, null=True)
    payment_status = models.CharField(
        max_length=20,
        choices=[
            ("PENDING", "Pending"),
            ("SUCCESS", "Success"),
            ("FAILED", "Failed"),
        ],
        default="PENDING",
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_date = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.order_id and self.rental_request:
            self.order_id = self.rental_request.order_id

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order_id} - {self.payment_status}"

class Services(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    image = models.ImageField(upload_to='service_images/')
    contact_number = models.CharField(max_length=15)
    
    def __str__(self):
        return self.title

class Cart(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='carts')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Cart #{self.id} - {self.user.username}"

    @property
    def total_items(self):
        return sum(item.quantity for item in self.items.all())

    @property
    def total_price(self):
        return sum(item.quantity * item.rental_item.price_per_day for item in self.items.all())

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    rental_item = models.ForeignKey(Inventory, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Item(models.Model):
    item_name = models.ForeignKey(Inventory, on_delete=models.CASCADE, verbose_name="Item name")
    item_qty = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    donation = models.BooleanField(default=False)
    donor_name = models.CharField(max_length=200, blank=True, null=True)
    donor_contact = models.CharField(max_length=30, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.item_name} ({self.item_qty})"

class Customer(models.Model):
    """Saved customer entries created by admin for reuse in bookings.

    Admins can create multiple Customer records via Django admin and
    select them during an admin-driven booking flow.
    """
    name = models.CharField(max_length=255)
    patient_name = models.CharField(max_length=200, blank=True, null=True)
    phone = models.CharField(max_length=30, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.phone or 'no-phone'})"

@receiver(post_save, sender=History)
def create_return_notification(sender, instance, created, **kwargs):
    """Create notification when a return is approved."""
    if not created and instance.is_returned and instance.is_return_requested:
        from .utils import send_notification
        try:
            send_notification(
                title="Return Approved",
                message=f"Return approved for order {instance.order_id} by {instance.user.username}.",
                notification_type='return',
                link=f"/admin/app/history/{instance.id}/change/",
                order_id=instance.order_id,
                rental=instance
            )
        except Exception as e:
            print(f"[return notification error] {e}")

        try:
            instance.rental_item.update_availability()
        except Exception as e:
            try:
                instance.rental_item.available = (instance.rental_item.available_quantity or 0) > 0
                instance.rental_item.save(update_fields=['available'])
            except Exception:
                print(f"[inventory update error] {e}")
