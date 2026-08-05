from django.db import ProgrammingError
from django.db.models import Q
from app.models import History, Notification, user_has_permission, user_has_any_permission, user_has_assigned_role

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


def rbac_context(request):
    # Admins always see everything
    if request.user.is_authenticated and (request.user.is_superuser or request.user.is_staff):
        return {
            "rbac_can_access_inventory": True,
            "rbac_show_equipment_rental": True,
            "rbac_show_request_blood": True,
            "rbac_show_organize_camp": True,
            "rbac_show_be_donor": True,
            "rbac_show_volunteer": True,
            "rbac_show_medical_services": True,
            "rbac_show_about": True,
            "rbac_show_cart": request.user.is_authenticated,
            "rbac_manage_users": True,
            "rbac_manage_roles": True,
            "rbac_any_permission": True,
        }

    # If the user has no role assigned, show all normal user modules by default.
    if not user_has_assigned_role(request.user):
        return {
            "rbac_can_access_inventory": user_has_permission(request.user, 'can_access_inventory'),
            "rbac_show_equipment_rental": True,
            "rbac_show_request_blood": True,
            "rbac_show_organize_camp": True,
            "rbac_show_be_donor": True,
            "rbac_show_volunteer": True,
            "rbac_show_medical_services": True,
            "rbac_show_about": True,
            "rbac_show_cart": request.user.is_authenticated,
            "rbac_manage_users": user_has_permission(request.user, 'can_manage_users'),
            "rbac_manage_roles": user_has_permission(request.user, 'can_manage_roles'),
            "rbac_any_permission": user_has_any_permission(request.user),
        }

    # User has one or more roles assigned — show only modules granted by role permissions.
    return {
        "rbac_can_access_inventory": user_has_permission(request.user, 'can_access_inventory'),
        "rbac_show_equipment_rental": user_has_permission(request.user, 'can_access_inventory'),
        "rbac_show_request_blood": user_has_permission(request.user, 'can_manage_blood_requests'),
        "rbac_show_organize_camp": user_has_permission(request.user, 'can_manage_camps'),
        "rbac_show_be_donor": user_has_permission(request.user, 'can_manage_donors'),
        "rbac_show_volunteer": user_has_permission(request.user, 'can_manage_volunteers'),
        "rbac_show_medical_services": user_has_permission(request.user, 'can_manage_services'),
        "rbac_show_about": False,
        "rbac_show_cart": request.user.is_authenticated and user_has_permission(request.user, 'can_access_inventory'),
        "rbac_manage_users": user_has_permission(request.user, 'can_manage_users'),
        "rbac_manage_roles": user_has_permission(request.user, 'can_manage_roles'),
        "rbac_any_permission": user_has_any_permission(request.user),
    }


def notification_context(request):
    if not request.user.is_authenticated:
        return {}

    try:
        latest_notifications = list(
            Notification.objects.filter(
                Q(recipient=request.user) | Q(recipient__isnull=True)
            ).order_by('-created_at')[:5]
        )
        unread_notification_count = Notification.objects.filter(
            Q(is_read=False),
            Q(recipient=request.user) | Q(recipient__isnull=True)
        ).count()
    except ProgrammingError:
        latest_notifications = []
        unread_notification_count = 0

    return {
        "latest_notifications": latest_notifications,
        "unread_notification_count": unread_notification_count,
    }
