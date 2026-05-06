from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
import datetime
from django.db.models import Max, Sum, Q
from django.db.models.signals import post_save
from django.dispatch import receiver
import re
from django.db import models
import uuid

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
    available_quantity = models.PositiveIntegerField(default=0)
    booked_quantity = models.PositiveIntegerField(default=0)
    available = models.BooleanField(default=True)
    next_available_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.title

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
                self.next_available_date = (timezone.now().date() + timedelta(days=7))
        except Exception:
            pass
        try:
            self.save(update_fields=[
                'booked_quantity',
                'available_quantity',
                'available',
                'next_available_date'
            ])
        except Exception:
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
    phone = models.CharField(max_length=15, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    rental_item = models.ForeignKey("Inventory", on_delete=models.CASCADE, related_name='rentalrequest_set')
    start_date = models.DateField()
    end_date = models.DateField()
    extended_end_date = models.DateField(null=True, blank=True)
    actual_return_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    quantity = models.PositiveIntegerField(default=1)
    is_returned = models.BooleanField(default=False)
    is_return_requested = models.BooleanField(default=False)
    order_id = models.CharField(max_length=100, blank=True, null=True)
    is_reminder_sent = models.BooleanField(default=False)
    is_overdue_email_sent = models.BooleanField(default=False)
    patient_name = models.CharField(max_length=200, null=True, blank=True)
    delivery_option = models.CharField(max_length=20, choices=[("delivery", "Delivery"), ("pickup", "Pickup")],
        blank=True, null=True)
    delivery_charge = models.DecimalField( max_digits=10, decimal_places=2, default=0)
    return_pickup_charge = models.DecimalField( max_digits=10, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=50,choices=[('online', 'Online'), ('cod', 'Cash on Delivery')])
    deposit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    deposit_donated = models.BooleanField(default=False)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2,blank=True,null=True)

    status = models.CharField( max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('cancelled', 'Cancelled'),
        ],
        default='pending'
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
        if self.deposit_donated:
            return 0
        deposit_total = self.deposit * self.quantity
        refund = deposit_total - self.delivery_charge - self.return_pickup_charge
        return max(refund, 0)

    def save(self, *args, **kwargs):
        self.total_amount = (
            self.total_rent +
            (self.deposit * self.quantity) +
            self.delivery_charge +
            self.return_pickup_charge
        )
        super().save(*args, **kwargs)



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
    is_notified = models.BooleanField(default=False)
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
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

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
    order_id = models.CharField(max_length=10, editable=False)
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
    item_name = models.CharField(max_length=255, blank=False, null=False)  
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



@receiver(post_save, sender=Item)
def update_inventory_on_item_created(sender, instance, created, **kwargs):
    """When a new Item is created, add its quantity to Inventory (aggregate by title).
    Duplicate Item records are allowed; Inventory keeps a single aggregated entry.
    """
    if not created:
        return

    name = instance.item_name.strip()
    if not name:
        return

    inv = Inventory.objects.filter(title__iexact=name).first()
    if inv:
        inv.total_quantity = (inv.total_quantity or 0) + instance.item_qty
        inv.available_quantity = (inv.available_quantity or 0) + instance.item_qty
        try:
            inv.update_availability()
        except Exception:
            inv.available = inv.total_quantity > 0
            inv.save()
    else:
        Inventory.objects.create(
            title=name,
            description='',
            price_per_day=instance.price or 0,
            total_quantity=instance.item_qty,
            available=True,
            available_quantity=instance.item_qty,
        )





