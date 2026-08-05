from django import template
from django.db import ProgrammingError
from django.db.models import Q
from app.models import Notification, user_has_any_permission

register = template.Library()

@register.simple_tag(takes_context=True)
def unread_notification_count(context):
    request = context.get('request')
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return 0
    try:
        return Notification.objects.filter(
            Q(is_read=False),
            Q(recipient=user) | Q(recipient__isnull=True)
        ).count()
    except ProgrammingError:
        return 0

@register.simple_tag(takes_context=True)
def latest_notifications(context, limit=5):
    request = context.get('request')
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return []
    try:
        return Notification.objects.filter(
            Q(recipient=user) | Q(recipient__isnull=True)
        ).order_by('-created_at')[:limit]
    except ProgrammingError:
        return []
