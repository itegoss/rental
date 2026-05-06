from django import template
from app.models import Notification

register = template.Library()

@register.simple_tag(takes_context=True)
def unread_notification_count(context):
    request = context.get('request')
    user = getattr(request, 'user', None)
    if not user or not (user.is_staff or user.is_superuser):
        return 0
    return Notification.objects.filter(is_read=False).count()

@register.simple_tag(takes_context=True)
def latest_notifications(context, limit=5):
    request = context.get('request')
    user = getattr(request, 'user', None)
    if not user or not (user.is_staff or user.is_superuser):
        return []
    return Notification.objects.all()[:limit]
