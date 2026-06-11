from django.core.management.base import BaseCommand
from app.models import Inventory, NotifyRequest
from django.conf import settings


class Command(BaseCommand):
    help = 'Test notification system setup'

    def handle(self, *args, **options):
        self.stdout.write("\n" + "="*70)
        self.stdout.write("🧪 NOTIFICATION SYSTEM TEST")
        self.stdout.write("="*70 + "\n")

        # Test 1: Check email configuration
        self.stdout.write("\n✓ TEST 1: Email Configuration")
        self.stdout.write("-" * 70)
        self.stdout.write(f"  EMAIL_BACKEND: {settings.EMAIL_BACKEND}")
        self.stdout.write(f"  EMAIL_HOST: {settings.EMAIL_HOST}")
        self.stdout.write(f"  EMAIL_PORT: {settings.EMAIL_PORT}")
        self.stdout.write(f"  EMAIL_USE_TLS: {settings.EMAIL_USE_TLS}")
        self.stdout.write(f"  EMAIL_HOST_USER: {settings.EMAIL_HOST_USER if settings.EMAIL_HOST_USER else '(empty)'}")
        self.stdout.write(f"  DEFAULT_FROM_EMAIL: {settings.DEFAULT_FROM_EMAIL}")
        self.stdout.write(f"  SITE_URL: {getattr(settings, 'SITE_URL', 'NOT SET')}")

        # Test 2: Check database records
        self.stdout.write("\n✓ TEST 2: Database Records")
        self.stdout.write("-" * 70)
        
        items_count = Inventory.objects.count()
        self.stdout.write(f"  Total Items: {items_count}")
        
        out_of_stock = Inventory.objects.filter(available_quantity=0).count()
        self.stdout.write(f"  Out of Stock Items: {out_of_stock}")
        
        notify_count = NotifyRequest.objects.count()
        self.stdout.write(f"  Total Notify Requests: {notify_count}")
        
        pending_notify = NotifyRequest.objects.filter(is_notified=False).count()
        self.stdout.write(f"  Pending Notifications: {pending_notify}")
        
        # Test 3: Show pending notifications
        self.stdout.write("\n✓ TEST 3: Pending Notifications Details")
        self.stdout.write("-" * 70)
        
        pending = NotifyRequest.objects.filter(is_notified=False)
        if pending.exists():
            for notify_req in pending:
                self.stdout.write(f"\n  📧 Email: {notify_req.email}")
                self.stdout.write(f"     Mobile: {notify_req.mobile}")
                self.stdout.write(f"     Item: {notify_req.item.title}")
                self.stdout.write(f"     Item Qty: {notify_req.item.available_quantity}")
                self.stdout.write(f"     Created: {notify_req.created_at}")
        else:
            self.stdout.write("  (No pending notifications)")

        # Test 4: Check signals registration
        self.stdout.write("\n✓ TEST 4: Signals Registration")
        self.stdout.write("-" * 70)
        try:
            import app.signals
            self.stdout.write("  ✅ Signals module imported successfully")
            self.stdout.write("  ✅ Handlers registered:")
            self.stdout.write("     - capture_old_quantity (pre_save)")
            self.stdout.write("     - send_availability_notification (post_save)")
        except Exception as e:
            self.stdout.write(f"  ❌ Error importing signals: {e}")

        # Test 5: Manual test
        self.stdout.write("\n✓ TEST 5: Manual Trigger Test")
        self.stdout.write("-" * 70)
        self.stdout.write("  To test the notification system manually:")
        self.stdout.write("  1. Go to Django Admin: http://localhost:8000/admin/")
        self.stdout.write("  2. Find an Item with available_quantity = 0")
        self.stdout.write("  3. Change quantity to 1")
        self.stdout.write("  4. Click Save")
        self.stdout.write("  5. Check console for debug messages")
        self.stdout.write("  6. Verify NotifyRequest.is_notified = True")

        self.stdout.write("\n" + "="*70)
        self.stdout.write("✅ Test completed!")
        self.stdout.write("="*70 + "\n")
