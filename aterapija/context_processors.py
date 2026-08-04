from .auth_helpers import is_admin_user, is_therapist_user
from .models import Notification


def user_roles(request):
    return {
        "is_admin_user": is_admin_user(request.user),
    }


def notification_counts(request):
    if not request.user.is_authenticated or not (is_admin_user(request.user) or is_therapist_user(request.user)):
        return {"unread_notification_count": 0}
    return {
        "unread_notification_count": Notification.objects.filter(
            recipient=request.user,
            is_read=False,
        ).count()
    }
