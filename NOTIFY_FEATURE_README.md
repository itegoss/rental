# Auto-Notification Feature Documentation

## Overview
When an item's quantity increases from 0 to > 0 (becomes available again), the system automatically sends notification emails to all users who previously requested notifications for that item.

## How It Works

### 1. User Requests Notification
- When an item is out of stock, users can click **"Notify Me"** button
- They enter their email and mobile number
- A `NotifyRequest` record is created with `is_notified=False`

### 2. Admin Updates Quantity
- Admin goes to Django Admin → Items
- Selects an item and updates `available_quantity` from 0 to any positive number
- Saves the changes

### 3. Automatic Email Trigger
- A Django signal (`post_save`) detects the quantity change
- If quantity changed from 0 to > 0:
  - Finds all pending notifications for that item
  - Sends HTML emails to all users
  - Marks notifications as `is_notified=True`

### 4. Email Content
- Beautiful HTML email with item details
- Price per day, deposit amount, available quantity
- Direct link to browse items page
- Professional design matching the QuickNest brand

## Signal Details

**File:** `app/signals.py`

**Signal Handler:** `send_availability_notification()`
- Triggers on `RentalItem` post_save
- Tracks previous quantities using a dictionary
- Only sends emails when quantity goes from 0 → > 0

**Email Function:** `send_notification_emails()`
- Queries all pending notifications for the item
- Sends HTML-formatted emails
- Updates `is_notified` flag to prevent duplicate emails

## Configuration

### Required Settings (in `settings.py`)
```python
# Email backend (default is dummy - emails won't send)
EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"

# For production, use:
# EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
# EMAIL_HOST = 'smtp.gmail.com'
# EMAIL_PORT = 587
# EMAIL_USE_TLS = True
# EMAIL_HOST_USER = 'your-email@gmail.com'
# EMAIL_HOST_PASSWORD = 'your-app-password'

# Default sender email
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "webmaster@localhost")

# Site URL for email links
SITE_URL = os.environ.get("SITE_URL", "http://localhost:8000")
```

### Environment Variables
Add to `.env` file:
```
SITE_URL=https://yourdomain.com
DEFAULT_FROM_EMAIL=noreply@quicknest.com
```

## Admin Panel Integration

### View Notify Requests
1. Go to Django Admin → NotifyRequests
2. See all user notification requests
3. Filter by:
   - Notification status (notified/pending)
   - Item
   - Creation date
4. Search by email or mobile number

### Manage Items
1. Go to Django Admin → Rental Items
2. Select an item with 0 quantity
3. Update `available_quantity` to any number > 0
4. Click Save
5. **Automatic emails sent to all pending users!**

## Testing Locally

Since EMAIL_BACKEND is set to 'dummy' by default:

1. **Check Console Logs**
   - Emails won't actually send
   - But ✅/❌ messages will print in console
   - Look for: `✅ Notification sent to user@email.com for Item Name`

2. **To Enable Real Emails**
   - Update settings.py to use SMTP backend
   - Configure email credentials (Gmail recommended)
   - Generate app-specific password (not main password)

3. **Test Scenario**
   ```
   1. Create an item with quantity = 0
   2. Submit "Notify Me" form with test email
   3. Go to admin and change quantity to 1
   4. Check if email was sent (or check logs)
   5. Verify NotifyRequest.is_notified = True
   ```

## Key Features

✅ **Automatic** - No manual intervention needed
✅ **Efficient** - Only sends when quantity increases from 0
✅ **Duplicate Prevention** - Tracks `is_notified` flag
✅ **Beautiful Emails** - Professional HTML formatting
✅ **Admin Friendly** - Simple one-click update
✅ **Mobile Ready** - Responsive email design
✅ **Error Handling** - Graceful handling of email failures
✅ **Logging** - Console output for debugging

## Troubleshooting

### Emails not sending?
- Check EMAIL_BACKEND in settings.py
- If using SMTP, verify credentials
- Check console for error messages

### Notifications not triggering?
- Ensure apps.py has the `ready()` method that imports signals
- Check that quantity goes from 0 → > 0 (not increasing from existing quantity)
- Verify NotifyRequest records exist with `is_notified=False`

### Duplicate notifications?
- Check if `is_notified` was properly updated
- Run: `NotifyRequest.objects.filter(item_id=X, is_notified=False).count()`
- Should be 0 after first notification

## Files Modified

1. **app/signals.py** (NEW)
   - Django signal handler for auto-notifications

2. **app/apps.py** (UPDATED)
   - Registers signals in `ready()` method

3. **settings.py** (UPDATED)
   - Added SITE_URL configuration

## Database Migration (if needed)

The `NotifyRequest` model already exists, so no new migration needed!

But if you're adding this for the first time:
```bash
python manage.py makemigrations
python manage.py migrate
```

## Future Enhancements

- [ ] SMS notifications using Twilio
- [ ] In-app notifications (bell icon)
- [ ] Notification history dashboard
- [ ] Bulk email to multiple items
- [ ] Scheduled digest emails
- [ ] Unsubscribe link in emails
