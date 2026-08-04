from django.urls import reverse

ADMIN_GROUP = "Admin"
THERAPIST_GROUP = "Therapist"
CLIENT_GROUP = "Client"


def user_in_group(user, group_name):
    return user.is_authenticated and user.groups.filter(name=group_name).exists()


def is_admin_user(user):
    return (
        user.is_authenticated
        and (user.is_superuser or user.is_staff or user_in_group(user, ADMIN_GROUP))
    )


def is_therapist_user(user):
    return user_in_group(user, THERAPIST_GROUP)


def is_client_user(user):
    return user_in_group(user, CLIENT_GROUP)


def get_user_dashboard_url(user):
    if is_admin_user(user):
        return reverse("aterapija:admin_dashboard")
    if is_therapist_user(user):
        return reverse("aterapija:therapist_dashboard")
    if is_client_user(user):
        return reverse("aterapija:client_dashboard")
    return reverse("aterapija:dashboard")
