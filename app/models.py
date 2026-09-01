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
    class Meta:
        verbose_name = "Booking"
        verbose_name_plural = "Bookings"

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
    rent = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Rent (per day)")
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
        from decimal import Decimal
        rent_rate = self.rent if self.rent is not None else (self.rental_item.price_per_day if self.rental_item else Decimal('0'))
        return Decimal(str(self.rental_days)) * Decimal(str(rent_rate)) * Decimal(str(self.quantity))

    @property
    def refund_amount(self):
        """
        Refund = Amount Paid - Total Charges (capped at Deposit)
        If deposit was donated or net_balance <= 0, refund is 0
        """
        from decimal import Decimal
        if self.deposit_donated:
            return Decimal("0")
        rent_dec = Decimal(str(self.total_rent or '0'))
        deposit_dec = Decimal(str(self.deposit or '0')) * self.quantity
        delivery_dec = Decimal(str(self.delivery_charge or '0'))
        pickup_dec = Decimal(str(self.return_pickup_charge or '0'))
        donation_dec = Decimal(str(self.donation_amount or '0'))
        
        total_charges = rent_dec + delivery_dec + pickup_dec + donation_dec
        paid_dec = Decimal(str(self.amount_paid or '0'))
        
        net_balance = paid_dec - total_charges
        if net_balance > 0:
            return min(net_balance, deposit_dec)
        return Decimal("0")

    def save(self, *args, **kwargs):
        from decimal import Decimal
        if self.rent is None and self.rental_item_id:
            try:
                self.rent = self.rental_item.price_per_day
            except Exception:
                pass
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
    recipient = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications'
    )
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

class Role(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    can_access_inventory = models.BooleanField(default=False)
    can_manage_blood_requests = models.BooleanField(default=False)
    can_manage_camps = models.BooleanField(default=False)
    can_manage_donors = models.BooleanField(default=False)
    can_manage_volunteers = models.BooleanField(default=False)
    can_manage_services = models.BooleanField(default=False)
    can_manage_users = models.BooleanField(default=False)
    can_manage_roles = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def permission_list(self):
        permissions = []
        if self.can_access_inventory:
            permissions.append('Inventory Access')
        if self.can_manage_blood_requests:
            permissions.append('Blood Requests')
        if self.can_manage_camps:
            permissions.append('Camps')
        if self.can_manage_donors:
            permissions.append('Donors')
        if self.can_manage_volunteers:
            permissions.append('Volunteers')
        if self.can_manage_services:
            permissions.append('Services')
        if self.can_manage_users:
            permissions.append('Users')
        if self.can_manage_roles:
            permissions.append('Roles')
        return permissions

    def has_permission(self, permission_name):
        return getattr(self, permission_name, False)

class UserRole(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='role_assignments')
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name='user_assignments')
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'role')
        ordering = ['user__username', 'role__name']

    def __str__(self):
        return f"{self.user.username} → {self.role.name}"


def user_has_permission(user, permission_name):
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser or user.is_staff:
        return True

    return any(
        getattr(assignment.role, permission_name, False)
        for assignment in user.role_assignments.select_related('role').all()
    )


def user_has_assigned_role(user):
    """Return True if the given user has any Role assigned.

    - Returns False for anonymous or unauthenticated users.
    - Superusers/staff are not considered 'assigned' here unless they actually
      have role assignments; caller should check `is_superuser` / `is_staff`
      separately when deciding access.
    """
    if not user or not user.is_authenticated:
        return False
    try:
        from django.apps import apps
        UserRole = apps.get_model('app', 'UserRole')
        return UserRole.objects.filter(user_id=user.id).exists()
    except Exception:
        # Fallback to reverse relation if model resolution fails
        try:
            return user.role_assignments.exists()
        except Exception:
            return False

def user_has_any_permission(user):
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser or user.is_staff:
        return True

    permission_fields = [
        'can_access_inventory',
        'can_manage_blood_requests',
        'can_manage_camps',
        'can_manage_donors',
        'can_manage_volunteers',
        'can_manage_services',
        'can_manage_users',
        'can_manage_roles',
    ]
    return any(
        getattr(assignment.role, field, False)
        for assignment in user.role_assignments.select_related('role').all()
        for field in permission_fields
    )

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
    class Meta:
        verbose_name = "Medical Service"
        verbose_name_plural = "Medical Services"

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


class BloodRequest(models.Model):
    BLOOD_GROUP_CHOICES = [
        ('A+', 'A+'),
        ('A-', 'A-'),
        ('B+', 'B+'),
        ('B-', 'B-'),
        ('AB+', 'AB+'),
        ('AB-', 'AB-'),
        ('O+', 'O+'),
        ('O-', 'O-'),
        ('BB', 'BB'),
        ("Don't Know", "Don't Know"),
    ]
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Accepted', 'Accepted'),
        ('Assigned', 'Assigned'),
        ('Searching', 'Searching'),
        ('Blood Available', 'Blood Available'),
        ('Ready for Pickup', 'Ready for Pickup'),
        ('Received', 'Received'),
        ('Fulfilled', 'Fulfilled'),
        ('Completed', 'Completed'),
        ('Cancelled', 'Cancelled'),
        ('Rejected', 'Rejected'),
    ]
    BLOOD_COMPONENT_CHOICES = [
        ('PLASMA (C.C.P)', 'PLASMA (C.C.P)'),
        ('PLASMA (F.F.P)', 'PLASMA (F.F.P)'),
        ('PCV/PRBC', 'PCV/PRBC'),
        ('Whole Blood (W.B.)', 'Whole Blood (W.B.)'),
        ('Platelets (PLT.)', 'Platelets (PLT.)'),
        ('SDP', 'SDP'),
        ('RDP', 'RDP'),
        ('Cryoprecipitate (CYRO.)', 'Cryoprecipitate (CYRO.)'),
    ]
    blood_component = models.CharField(max_length=50, choices=BLOOD_COMPONENT_CHOICES, blank=True, null=True)
    patient_name = models.CharField(max_length=255)
    hospital_name = models.CharField(max_length=255)
    hospital_area = models.CharField(max_length=255)
    blood_group = models.CharField(max_length=20, choices=BLOOD_GROUP_CHOICES, blank=True, null=True)
    units_required = models.PositiveIntegerField(default=1, blank=True, null=True)
    coordinator_name = models.CharField(max_length=255)
    coordinator_contact = models.CharField(max_length=15)
    reference_name = models.CharField(max_length=255, blank=True, null=True)
    reference_contact = models.CharField(max_length=15, blank=True, null=True)
    prescription = models.FileField(
        upload_to='prescriptions/',
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'pdf', 'img'])]
    )
    consent = models.BooleanField(default=False)
    
    blood_type = models.CharField(max_length=100, blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0, blank=True, null=True)
    blood_bank = models.CharField(max_length=255, blank=True, null=True)

    request_id = models.CharField(max_length=30, blank=True, null=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='blood_requests_created')
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='blood_requests_updated')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='Pending')
    cancellation_reason = models.TextField(blank=True, null=True, help_text='Reason for cancellation')
    remarks = models.TextField(blank=True, null=True)
    assigned_employee = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_blood_requests'
    )
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='blood_requests_assigned_by'
    )
    assigned_at = models.DateTimeField(blank=True, null=True)
    status_history = models.TextField(blank=True, null=True, help_text='JSON-like status history timeline')
    last_status_changed_at = models.DateTimeField(blank=True, null=True)
    last_status_changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='blood_requests_status_changed')

    def generate_request_id(self):
        dt = self.created_at or timezone.now()
        prefix = f"BR{dt.strftime('%Y%m')}"
        last_req = (
            BloodRequest.objects
            .filter(request_id__startswith=prefix)
            .exclude(id=self.id if self.id else None)
            .order_by("-request_id")
            .first()
        )
        if last_req and last_req.request_id and len(last_req.request_id) >= len(prefix) + 3:
            try:
                last_number = int(last_req.request_id[-3:])
                new_number = str(last_number + 1).zfill(3)
            except (ValueError, IndexError):
                new_number = "001"
        else:
            new_number = "001"
        
        gen_id = f"{prefix}{new_number}"
        while BloodRequest.objects.filter(request_id=gen_id).exclude(id=self.id if self.id else None).exists():
            last_number = int(gen_id[-3:]) + 1
            new_number = str(last_number).zfill(3)
            gen_id = f"{prefix}{new_number}"
        return gen_id

    def save(self, *args, **kwargs):
        if not self.request_id:
            self.request_id = self.generate_request_id()
        super().save(*args, **kwargs)

    @property
    def formatted_request_id(self):
        if self.request_id:
            return self.request_id
        dt = self.created_at or timezone.now()
        return f"BR{dt.strftime('%Y%m')}{str(self.id or 1).zfill(3)}"

    def __str__(self):
        req_id = self.request_id or self.formatted_request_id
        return f"{req_id} - {self.patient_name} - {self.blood_group} ({self.status})"

    @property
    def is_terminal(self):
        return self.status in {'Completed', 'Cancelled', 'Rejected'}

    @property
    def badge_color(self):
        colors = {
            'Pending': '#f59e0b',
            'Accepted': '#2563eb',
            'Assigned': '#4f46e5',
            'Searching': '#7c3aed',
            'Blood Available': '#16a34a',
            'Ready for Pickup': '#0891b2',
            'Received': '#166534',
            'Fulfilled': '#16a34a',
            'Completed': '#6b7280',
            'Cancelled': '#ef4444',
            'Rejected': '#dc2626',
        }
        return colors.get(self.status, '#64748b')


    def get_next_statuses(self):
        flow = {
            'Pending': ['Accepted', 'Rejected'],
            'Accepted': ['Assigned', 'Rejected'],
            'Assigned': ['Searching', 'Rejected'],
            'Searching': ['Blood Available', 'Rejected'],
            'Blood Available': ['Ready for Pickup', 'Rejected'],
            'Ready for Pickup': ['Received', 'Rejected'],
            'Received': ['Completed', 'Rejected'],
            'Completed': [],
            'Rejected': [],
        }
        return flow.get(self.status, [])

    def can_transition_to(self, target_status):
        return target_status in self.get_next_statuses()

    def get_status_history(self):
        if not self.status_history:
            return []
        import json
        try:
            data = json.loads(self.status_history)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return []

    def append_status_history(self, status, changed_by=None, note=None):
        import json
        from django.utils import timezone

        history = self.get_status_history()
        entry = {
            'status': status,
            'changed_at': timezone.now().isoformat(),
            'changed_by': changed_by.username if changed_by else None,
            'note': note or '',
        }
        history.append(entry)
        self.status_history = json.dumps(history)
        self.last_status_changed_at = timezone.now()
        self.last_status_changed_by = changed_by
        self.save()


class BloodBank(models.Model):
    name = models.CharField(max_length=255, verbose_name="Blood Bank Name")
    address = models.TextField(blank=True, null=True, verbose_name="Address")
    person_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Contact Person Name")
    contact = models.CharField(max_length=20, blank=True, null=True, verbose_name="Contact Number")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = "Blood Bank"
        verbose_name_plural = "Blood Banks"

    def __str__(self):
        return f"{self.name} ({self.person_name or 'N/A'})"


class CampOrganizer(models.Model):
    STATUS_CHOICES = [
        ('Completed', 'Completed'),
        ('Pending', 'Pending'),
        ('Cancelled', 'Cancelled'),
    ]
    organizer_name = models.CharField(max_length=255)
    organization_name = models.CharField(max_length=255)
    contact_number = models.CharField(max_length=15)
    email = models.EmailField()
    proposed_date = models.DateField()
    proposed_venue = models.CharField(max_length=255)
    expected_donors = models.PositiveIntegerField()
    mobile_van_required = models.BooleanField(default=False)
    volunteers_available = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='camps_created')
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='camps_updated')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    remarks = models.TextField(blank=True, null=True)

    @property
    def display_status(self):
        return self.status or 'Pending'

    def __str__(self):
        return f"{self.organization_name} - {self.proposed_date} ({self.status})"


class BloodDonor(models.Model):
    GENDER_CHOICES = [
        ('Male', 'Male'),
        ('Female', 'Female'),
        ('Other', 'Other'),
    ]
    BLOOD_GROUP_CHOICES = [
        ('A+', 'A+'),
        ('A-', 'A-'),
        ('B+', 'B+'),
        ('B-', 'B-'),
        ('AB+', 'AB+'),
        ('AB-', 'AB-'),
        ('O+', 'O+'),
        ('O-', 'O-'),
        ('BB', 'BB'),
        ("Don't Know", "Don't Know"),
    ]
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Cancelled', 'Cancelled'),
        ('Fulfilled', 'Fulfilled'),
    ]
    full_name = models.CharField(max_length=255, blank=True, null=True)
    contact_number = models.CharField(max_length=15)
    date_of_birth = models.DateField()
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    blood_group = models.CharField(max_length=20, choices=BLOOD_GROUP_CHOICES)
    area_of_residence = models.CharField(max_length=255)
    reference_name = models.CharField(max_length=255, blank=True, null=True)
    reference_contact = models.CharField(max_length=15, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='donors_created')
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='donors_updated')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    remarks = models.TextField(blank=True, null=True)

    @property
    def first_name(self):
        if self.full_name and self.full_name.strip():
            return self.full_name.strip().split(None, 1)[0]
        return ""

    @property
    def last_name(self):
        if self.full_name and self.full_name.strip():
            parts = self.full_name.strip().split(None, 1)
            return parts[1] if len(parts) > 1 else ""
        return ""

    def get_full_name(self):
        return (self.full_name or "").strip()

    def save(self, *args, **kwargs):
        if self.full_name:
            self.full_name = self.full_name.strip()
        super().save(*args, **kwargs)

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = timezone.now().date()
        return today.year - self.date_of_birth.year - ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))

    def __str__(self):
        return f"{self.get_full_name()} - {self.blood_group} ({self.status})"


class EventVolunteer(models.Model):
    GENDER_CHOICES = [
        ('Male', 'Male'),
        ('Female', 'Female'),
        ('Other', 'Other'),
    ]
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Cancelled', 'Cancelled'),
        ('Fulfilled', 'Fulfilled'),
    ]
    full_name = models.CharField(max_length=255)
    contact_number = models.CharField(max_length=15)
    email = models.EmailField()
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, null=True)
    area_of_residence = models.CharField(max_length=255)
    event_interest = models.CharField(max_length=255, blank=True, null=True, help_text="e.g. Blood Camp, Equipment Distribution, Youth Drive")
    skills_remarks = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = timezone.now().date()
        return today.year - self.date_of_birth.year - ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='volunteers_created')
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='volunteers_updated')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.full_name} ({self.contact_number}) - {self.status}"

class SupportService(models.Model):
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def clean(self):
        # Ensure no more than 5 contacts are associated
        if self.pk and self.contacts.count() > 5:
            raise ValidationError('A service can have at most 5 contacts.')


class SupportServiceContact(models.Model):
    service = models.ForeignKey(SupportService, on_delete=models.CASCADE, related_name='contacts')
    service_name = models.CharField(max_length=255, blank=True, null=True)
    contact_name = models.CharField(max_length=255)
    contact_number = models.CharField(max_length=30)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['display_order']
        unique_together = (('service', 'contact_name', 'contact_number'),)

    def __str__(self):
        return f"{self.contact_name} ({self.contact_number})"

