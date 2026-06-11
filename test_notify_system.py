"""
Verification script to test the Notify Me email system
Run this from Django shell: exec(open('test_notify_system.py').read())
"""

from app.models import Inventory, NotifyRequest
from django.conf import settings

print("\n" + "="*60)
print("  NOTIFY SYSTEM VERIFICATION")
print("="*60)

# 1. Check Email Backend
print("\nEMAIL CONFIGURATION:")
print(f"   Email Backend: {settings.EMAIL_BACKEND}")
print(f"   Default From Email: {settings.DEFAULT_FROM_EMAIL}")
print(f"   Site URL: {getattr(settings, 'SITE_URL', 'NOT SET')}")

if "dummy" in settings.EMAIL_BACKEND:
    print("   WARNING: Using DUMMY backend - emails won't actually send!")
    print("       To enable real emails, update EMAIL_BACKEND in settings.py")

# 2. Check if NotifyRequest records exist
print("\nNOTIFY REQUESTS IN DATABASE:")
all_notifications = NotifyRequest.objects.all()
print(f"   Total notifications: {all_notifications.count()}")

pending = NotifyRequest.objects.filter(is_notified=False)
print(f"   Pending (not notified): {pending.count()}")

notified = NotifyRequest.objects.filter(is_notified=True)
print(f"   Already notified: {notified.count()}")

if pending.count() > 0:
    print("\n   Pending Notifications:")
    for req in pending[:5]:
        print(f"      - Email: {req.email}")
        print(f"        Mobile: {req.mobile}")
        print(f"        Item: {req.item.title}")
        print(f"        Item Qty: {req.item.available_quantity}")
        print()

# 3. Check signals are imported
print("\nSIGNAL CHECK:")
try:
    import app.signals
    print("   [OK] Signals module imported successfully")
    
    from app.signals import capture_old_quantity, send_availability_notification
    print("   [OK] Signal handlers found")
except ImportError as e:
    print(f"   [ERROR] Error importing signals: {e}")

# 4. Items with 0 quantity
print("\nITEMS WITH 0 QUANTITY:")
zero_qty_items = Inventory.objects.filter(available_quantity=0)
print(f"   Total: {zero_qty_items.count()}")

if zero_qty_items.count() > 0:
    for item in zero_qty_items[:5]:
        notify_count = NotifyRequest.objects.filter(item=item, is_notified=False).count()
        print(f"      - {item.title} (ID: {item.id}) - {notify_count} pending notifications")

print("\n" + "="*60)
print("TEST INSTRUCTIONS:")
print("="*60)
print("""
1. If pending notifications > 0:
   - Go to Django Admin -> RentalItems
   - Find an item with 0 quantity
   - Change 'available_quantity' from 0 to 1
   - Click Save
   - Check console for debug messages

2. Look for these console messages:
   Item: X | Old Qty: 0 -> New Qty: 1
   Sending notifications for X...
   Found X pending notifications
   Notification sent to user@email.com

3. Then check AdminPanel:
   - NotifyRequests -> Find the record
   - Check if 'is_notified' changed to True
""")
print("="*60 + "\n")
