from app.models import History, Notification

def rental_receipt_visibility(request):
    if request.user.is_authenticated:
        last_rental_id = History.objects.filter(
            user_id=request.user.id,
            status="approved"
        ).order_by('-id').values_list('id', flat=True).first()

        if last_rental_id:
            return {
                "show_receipt": True,
                "receipt_rental_id": last_rental_id
            }

    return {
        "show_receipt": False,
        "receipt_rental_id": None
    }


def notification_context(request):
    if not request.user.is_authenticated or not (request.user.is_staff or request.user.is_superuser):
        return {}

    latest_notifications = list(Notification.objects.all().order_by('-created_at')[:5])
    unread_notification_count = Notification.objects.filter(is_read=False).count()

    return {
        "latest_notifications": latest_notifications,
        "unread_notification_count": unread_notification_count,
    }
