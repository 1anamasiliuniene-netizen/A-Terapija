from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.shortcuts import redirect

from .auth_helpers import get_user_dashboard_url, is_admin_user, is_client_user, is_therapist_user


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    role_check = None

    def test_func(self):
        return self.role_check(self.request.user)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        return redirect(get_user_dashboard_url(self.request.user))


class AdminRequiredMixin(RoleRequiredMixin):
    role_check = staticmethod(is_admin_user)


class TherapistRequiredMixin(RoleRequiredMixin):
    role_check = staticmethod(is_therapist_user)


class ClientRequiredMixin(RoleRequiredMixin):
    role_check = staticmethod(is_client_user)
