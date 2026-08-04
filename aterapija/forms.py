from datetime import time
import secrets
import string

from django import forms
from django.contrib.auth.forms import SetPasswordForm, UserCreationForm
from django.contrib.auth.models import Group, User
from django.utils.translation import gettext, gettext_lazy as _
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from crispy_forms.layout import Layout, Field
from .auth_helpers import THERAPIST_GROUP
from .models import (
    AdviceForToday,
    AdminProfile,
    AboutPage,
    Article,
    BookingRequest,
    ClientProfile,
    ContactMessage,
    Service,
    ServiceCategory,
    Therapist,
    TherapistAvailability,
    WellbeingAnswerOption,
    WellbeingQuestion, ArticleCategory,
)


def localized_service_label(service):
    return service.display_title


class ContactForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ["name", "email", "subject", "message"]
        widgets = {
            "message": forms.Textarea(attrs={"rows": 5}),
        }
        labels = {
            "name": _("Name"),
            "email": _("Email"),
            "subject": _("Subject"),
            "message": _("Message"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.form_tag = False

        for field in ("name", "email", "subject"):
            self.fields[field].widget.attrs.update({
                "class": "at-input",
            })

        self.fields["message"].widget.attrs.update({
            "class": "at-textarea",
        })

        self.fields["name"].widget.attrs["placeholder"] = _("Enter your name")
        self.fields["email"].widget.attrs["placeholder"] = _("Enter your email")
        self.fields["subject"].widget.attrs["placeholder"] = _("Subject")
        self.fields["message"].widget.attrs["placeholder"] = _("How can we help?")

        self.helper.layout = Layout(
            "name",
            "email",
            "subject",
            "message",
        )


class TherapistServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = [
            "category",
            "name",
            "title_lt",
            "title_en",
            "short_description",
            "full_description",
            "description_lt",
            "description_en",
            "duration_minutes",
            "price",
            "is_active",
        ]
        widgets = {
            "full_description": forms.Textarea(attrs={"rows": 5}),
            "description_lt": forms.Textarea(attrs={"rows": 5}),
            "description_en": forms.Textarea(attrs={"rows": 5}),
        }
        labels = {
            "category": _("Category"),
            "name": _("Internal/fallback service name"),
            "title_lt": _("Lithuanian title"),
            "title_en": _("English title"),
            "short_description": _("Fallback short description"),
            "full_description": _("Fallback full description"),
            "description_lt": _("Lithuanian description"),
            "description_en": _("English description"),
            "duration_minutes": _("Duration minutes"),
            "price": _("Price"),
            "is_active": _("Is active"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = ServiceCategory.objects.all()
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", _("Save service"), css_class="btn btn-primary"))


class TherapistServiceCategoryForm(forms.ModelForm):
    class Meta:
        model = ServiceCategory
        fields = ["name", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", _("Save category"), css_class="btn btn-primary"))


class TherapistServiceLinkForm(forms.Form):
    services = forms.ModelMultipleChoiceField(
        queryset=Service.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label=_("Services to add"),
    )

    def __init__(self, *args, therapist=None, **kwargs):
        super().__init__(*args, **kwargs)
        linked_ids = therapist.services.values_list("pk", flat=True) if therapist else []
        self.fields["services"].queryset = Service.objects.filter(is_active=True).exclude(pk__in=linked_ids)
        self.fields["services"].label_from_instance = localized_service_label
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", _("Link services"), css_class="btn btn-primary"))


class AdminServiceForm(forms.ModelForm):
    therapists = forms.ModelMultipleChoiceField(
        queryset=Therapist.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label=_("Therapists"),
    )

    class Meta:
        model = Service
        fields = [
            "category",
            "name",
            "title_lt",
            "title_en",
            "short_description",
            "full_description",
            "description_lt",
            "description_en",
            "duration_minutes",
            "price",
            "is_active",
            "therapists",
        ]
        widgets = {
            "full_description": forms.Textarea(attrs={"rows": 5}),
            "description_lt": forms.Textarea(attrs={"rows": 5}),
            "description_en": forms.Textarea(attrs={"rows": 5}),
        }
        labels = {
            "category": _("Category"),
            "name": _("Internal/fallback service name"),
            "title_lt": _("Lithuanian title"),
            "title_en": _("English title"),
            "short_description": _("Fallback short description"),
            "full_description": _("Fallback full description"),
            "description_lt": _("Lithuanian description"),
            "description_en": _("English description"),
            "duration_minutes": _("Duration minutes"),
            "price": _("Price"),
            "is_active": _("Is active"),
            "therapists": _("Therapists"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = ServiceCategory.objects.all()
        self.fields["therapists"].queryset = Therapist.objects.filter(is_active=True)
        if self.instance.pk:
            self.fields["therapists"].initial = self.instance.therapists.all()
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", _("Save service"), css_class="btn btn-primary"))

    def save(self, commit=True):
        service = super().save(commit=commit)
        if commit:
            service.therapists.set(self.cleaned_data["therapists"])
        return service


class BookingRequestForm(forms.ModelForm):
    class Meta:
        model = BookingRequest
        fields = [
            "client_name",
            "client_email",
            "client_phone",
            "service",
            "therapist",
            "preferred_date",
            "preferred_time",
            "message",
        ]
        widgets = {
            "preferred_date": forms.DateInput(attrs={"type": "date"}),
            "preferred_time": forms.TimeInput(attrs={"type": "time"}),
            "message": forms.Textarea(attrs={"rows": 4}),
        }
        labels = {
            "client_name": _("Name"),
            "client_email": _("Email"),
            "client_phone": _("Phone"),
            "service": _("Service"),
            "therapist": _("Therapist"),
            "preferred_date": _("Preferred date"),
            "preferred_time": _("Preferred time"),
            "message": _("Message"),
        }

    def __init__(self, *args, service=None, therapist=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.selected_service = service
        self.selected_therapist = therapist
        self.fields["service"].queryset = Service.objects.filter(is_active=True)
        self.fields["service"].label_from_instance = localized_service_label
        self.fields["therapist"].queryset = Therapist.objects.filter(is_active=True)
        self.fields["therapist"].required = False

        if service:
            self.fields["service"].initial = service
            self.fields["service"].widget = forms.HiddenInput()
            self.fields["therapist"].queryset = service.therapists.filter(is_active=True)

        if therapist:
            self.fields["therapist"].initial = therapist
            self.fields["therapist"].widget = forms.HiddenInput()

        self.fields["preferred_date"].widget = forms.HiddenInput()
        self.fields["preferred_time"].widget = forms.HiddenInput()

        if user and user.is_authenticated:
            for field_name in ["client_name", "client_email", "client_phone"]:
                self.fields.pop(field_name)

        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", _("Book appointment"), css_class="btn btn-primary"))

    def clean(self):
        cleaned_data = super().clean()
        service = cleaned_data.get("service") or self.selected_service
        therapist = cleaned_data.get("therapist") or self.selected_therapist
        preferred_date = cleaned_data.get("preferred_date")
        preferred_time = cleaned_data.get("preferred_time")

        if service:
            cleaned_data["service"] = service
            self.instance.service = service
            if "service" in self.errors:
                del self.errors["service"]
        if not therapist and service:
            active_therapists = list(service.therapists.filter(is_active=True)[:2])
            if len(active_therapists) == 1:
                therapist = active_therapists[0]
        if therapist:
            cleaned_data["therapist"] = therapist
            self.instance.therapist = therapist

        if service and therapist and not therapist.services.filter(pk=service.pk).exists():
            self.add_error("therapist", gettext("This therapist does not provide the selected service."))

        if service and therapist and preferred_date and preferred_time:
            if not BookingRequest.is_time_available(
                therapist,
                service,
                preferred_date,
                preferred_time,
                exclude_pk=self.instance.pk,
            ):
                self.add_error("preferred_time", gettext("Choose one of the available free times."))

        return cleaned_data

    def save(self, commit=True):
        booking = super().save(commit=False)
        booking.status = BookingRequest.STATUS_APPROVED
        if commit:
            booking.full_clean()
            booking.save()
            self.save_m2m()
        return booking


class TherapistAvailabilityForm(forms.ModelForm):
    BLOCK_SINGLE = "single"
    BLOCK_FULL_DAY = "full_day"
    BLOCK_MULTI_DAY = "multi_day"

    block_type = forms.ChoiceField(
        choices=[
            (BLOCK_SINGLE, _("Single time period")),
            (BLOCK_FULL_DAY, _("Full day unavailable")),
            (BLOCK_MULTI_DAY, _("Multi-day unavailable period")),
        ],
        initial=BLOCK_SINGLE,
    )

    class Meta:
        model = TherapistAvailability
        fields = ["block_type", "date", "end_date", "start_time", "end_time", "reason"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time", "step": 1800}),
            "end_time": forms.TimeInput(attrs={"type": "time", "step": 1800}),
        }

    def __init__(self, *args, therapist=None, **kwargs):
        self.therapist = therapist
        super().__init__(*args, **kwargs)
        self.fields["end_date"].required = False
        self.fields["start_time"].required = False
        self.fields["end_time"].required = False
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", gettext("Save unavailable time"), css_class="btn btn-primary"))

    def clean(self):
        cleaned_data = super().clean()
        block_type = cleaned_data.get("block_type")
        start_date = cleaned_data.get("date")
        end_date = cleaned_data.get("end_date")
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")

        if block_type == self.BLOCK_SINGLE:
            cleaned_data["end_date"] = start_date
            if not start_time:
                self.add_error("start_time", gettext("Start time is required."))
            if not end_time:
                self.add_error("end_time", gettext("End time is required."))
        elif block_type == self.BLOCK_FULL_DAY:
            cleaned_data["end_date"] = start_date
            cleaned_data["start_time"] = time(0, 0)
            cleaned_data["end_time"] = time(23, 30)
        elif block_type == self.BLOCK_MULTI_DAY:
            if not end_date:
                self.add_error("end_date", gettext("End date is required for a multi-day period."))
            cleaned_data["start_time"] = time(0, 0)
            cleaned_data["end_time"] = time(23, 30)

        return cleaned_data

    def save(self, commit=True):
        availability = super().save(commit=False)
        if self.therapist:
            availability.therapist = self.therapist
        block_type = self.cleaned_data.get("block_type")
        if block_type in {self.BLOCK_FULL_DAY, self.BLOCK_MULTI_DAY}:
            availability.start_time = time(0, 0)
            availability.end_time = time(23, 30)
            availability.is_full_day = True
            if block_type == self.BLOCK_FULL_DAY:
                availability.end_date = availability.date
        else:
            availability.end_date = availability.date
            availability.is_full_day = False
        if commit:
            availability.full_clean()
            availability.save()
        return availability


class BookingPostponeForm(forms.ModelForm):
    class Meta:
        model = BookingRequest
        fields = ["preferred_date", "preferred_time"]
        widgets = {
            "preferred_date": forms.DateInput(attrs={"type": "date"}),
            "preferred_time": forms.TimeInput(attrs={"type": "time", "step": 1800}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", gettext("Postpone booking"), css_class="btn btn-primary"))

    def clean(self):
        cleaned_data = super().clean()
        preferred_date = cleaned_data.get("preferred_date")
        preferred_time = cleaned_data.get("preferred_time")

        if preferred_date and preferred_time:
            if not BookingRequest.is_time_available(
                self.instance.therapist,
                self.instance.service,
                preferred_date,
                preferred_time,
                exclude_pk=self.instance.pk,
            ):
                self.add_error("preferred_time", gettext("Choose one of the available free times."))

        return cleaned_data

    def save(self, commit=True):
        booking = super().save(commit=False)
        booking.status = BookingRequest.STATUS_APPROVED
        if commit:
            booking.full_clean()
            booking.save()
        return booking


class AdminBookingForm(forms.ModelForm):
    class Meta:
        model = BookingRequest
        fields = [
            "client",
            "service",
            "therapist",
            "preferred_date",
            "preferred_time",
            "message",
            "status",
            "payment_received",
        ]
        widgets = {
            "service": forms.HiddenInput,
            "therapist": forms.HiddenInput,
            "preferred_date": forms.HiddenInput,
            "preferred_time": forms.HiddenInput,
            "message": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "client": _("Client"),
            "service": _("Service"),
            "therapist": _("Therapist"),
            "preferred_date": _("Preferred date"),
            "preferred_time": _("Preferred time"),
            "message": _("Message"),
            "status": _("Status"),
            "payment_received": _("Payment received"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["service"].queryset = Service.objects.filter(is_active=True)
        self.fields["service"].label_from_instance = localized_service_label
        self.fields["therapist"].queryset = Therapist.objects.filter(is_active=True)
        self.fields["status"].choices = BookingRequest.STATUS_CHOICES
        self.fields["client"].queryset = User.objects.filter(groups__name="Client").order_by("username")
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", _("Save booking"), css_class="btn btn-primary"))

    def clean(self):
        cleaned_data = super().clean()
        client = cleaned_data.get("client")
        service = cleaned_data.get("service")
        therapist = cleaned_data.get("therapist")
        preferred_date = cleaned_data.get("preferred_date")
        preferred_time = cleaned_data.get("preferred_time")
        status = cleaned_data.get("status")

        if not client:
            self.add_error("client", gettext("Choose an existing client, or add a new client first."))
        if not service:
            self.add_error("service", gettext("Select an available slot before saving."))
        if not therapist:
            self.add_error("therapist", gettext("Select an available slot before saving."))
        if not preferred_date:
            self.add_error("preferred_date", gettext("Select an available slot before saving."))
        if not preferred_time:
            self.add_error("preferred_time", gettext("Select an available slot before saving."))

        if status == BookingRequest.STATUS_APPROVED and service and therapist and preferred_date and preferred_time:
            if not therapist.services.filter(pk=service.pk).exists():
                self.add_error("therapist", gettext("This therapist does not provide the selected service."))
            if not BookingRequest.is_time_available(
                therapist,
                service,
                preferred_date,
                preferred_time,
                exclude_pk=self.instance.pk,
            ):
                self.add_error("preferred_time", gettext("This time is not available."))

        return cleaned_data

    def save(self, commit=True):
        booking = super().save(commit=False)

        if booking.client:
            try:
                profile = booking.client.client_profile
            except ClientProfile.DoesNotExist:
                profile = None
            booking.client_name = booking.client.get_full_name() or getattr(profile, "full_name", "") or booking.client.username
            booking.client_email = booking.client.email or booking.client_email
            booking.client_phone = getattr(profile, "phone", "") or booking.client_phone

        if commit:
            booking.full_clean()
            booking.save()
            self.save_m2m()
        return booking


class AdminClientCreateForm(forms.ModelForm):
    username = forms.CharField(max_length=150)
    email = forms.EmailField(required=False)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)

    class Meta:
        model = ClientProfile
        fields = ["username", "email", "first_name", "last_name", "phone"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", gettext("Create client"), css_class="btn btn-primary"))

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError(gettext("This username is already taken."))
        return username

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if email and User.objects.filter(email=email).exists():
            raise forms.ValidationError(gettext("A user with this email already exists."))
        return email

    def save(self, commit=True):
        alphabet = string.ascii_letters + string.digits
        self.temporary_password = "".join(secrets.choice(alphabet) for _ in range(12))
        user = User.objects.create_user(
            username=self.cleaned_data["username"],
            email=self.cleaned_data.get("email") or "",
            first_name=self.cleaned_data.get("first_name") or "",
            last_name=self.cleaned_data.get("last_name") or "",
            password=self.temporary_password,
        )
        client_group, _created = Group.objects.get_or_create(name="Client")
        user.groups.add(client_group)
        profile = super().save(commit=False)
        profile.user = user
        profile.full_name = user.get_full_name()
        if commit:
            profile.save()
        return profile


class AdminTherapistCreateForm(forms.ModelForm):
    username = forms.CharField(label=_("Username"), max_length=150)
    email = forms.EmailField(label=_("Email"), required=False)
    first_name = forms.CharField(label=_("First name"), max_length=150, required=False)
    last_name = forms.CharField(label=_("Last name"), max_length=150, required=False)

    class Meta:
        model = Therapist
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "profile_photo",
            "specializations",
            "languages",
            "experience",
            "bio",
            "bio_lt",
            "bio_en",
            "services",
            "is_active",
        ]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 5}),
            "bio_lt": forms.Textarea(attrs={"rows": 5}),
            "bio_en": forms.Textarea(attrs={"rows": 5}),
            "specializations": forms.Textarea(attrs={"rows": 3}),
            "services": forms.CheckboxSelectMultiple,
        }
        labels = {
            "full_name": _("Full name"),
            "phone": _("Phone"),
            "profile_photo": _("Profile photo"),
            "specializations": _("Specializations"),
            "languages": _("Languages"),
            "experience": _("Experience"),
            "bio": _("Fallback biography"),
            "bio_lt": _("Lithuanian biography"),
            "bio_en": _("English biography"),
            "services": _("Services"),
            "is_active": _("Is active"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["services"].queryset = Service.objects.filter(is_active=True)
        self.fields["services"].label_from_instance = localized_service_label
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.form_enctype = "multipart/form-data"
        self.helper.add_input(Submit("submit", gettext("Create therapist"), css_class="btn btn-primary"))

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError(gettext("This username is already taken."))
        return username

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if email and User.objects.filter(email=email).exists():
            raise forms.ValidationError(gettext("A user with this email already exists."))
        return email

    def save(self, commit=True):
        alphabet = string.ascii_letters + string.digits
        self.temporary_password = "".join(secrets.choice(alphabet) for _ in range(12))
        user = User.objects.create_user(
            username=self.cleaned_data["username"],
            email=self.cleaned_data.get("email") or "",
            first_name=self.cleaned_data.get("first_name") or "",
            last_name=self.cleaned_data.get("last_name") or "",
            password=self.temporary_password,
        )
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        user.groups.add(therapist_group)
        therapist = super().save(commit=False)
        therapist.user = user
        if commit:
            therapist.save()
            self.save_m2m()
        return therapist


class ClientRegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ["username", "email", "password1", "password2"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", gettext("Create account"), css_class="btn btn-primary"))


class LocalPasswordResetForm(forms.Form):
    username = forms.CharField(label=_("Username"), max_length=150)
    password1 = forms.CharField(
        label=_("New password"),
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label=_("Confirm new password"),
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_username(self):
        username = self.cleaned_data["username"]
        try:
            return User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise forms.ValidationError(gettext("No user was found with this username.")) from exc

    def clean(self):
        cleaned_data = super().clean()
        user = cleaned_data.get("username")
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if user and password1 and password2:
            password_form = SetPasswordForm(user, {"new_password1": password1, "new_password2": password2})
            if not password_form.is_valid():
                for field, errors in password_form.errors.items():
                    target = "password1" if field == "new_password1" else "password2"
                    for error in errors:
                        self.add_error(target, error)

        return cleaned_data

    def save(self):
        user = self.cleaned_data["username"]
        user.set_password(self.cleaned_data["password1"])
        user.save()
        return user


class ClientProfileForm(forms.ModelForm):
    username = forms.CharField(label=_("Username"), max_length=150)
    email = forms.EmailField(label=_("Email"), required=False)
    first_name = forms.CharField(label=_("First name"), max_length=150, required=False)
    last_name = forms.CharField(label=_("Last name"), max_length=150, required=False)

    class Meta:
        model = ClientProfile
        fields = ["username", "email", "first_name", "last_name", "phone", "profile_picture"]
        labels = {
            "username": _("Username"),
            "email": _("Email"),
            "first_name": _("First name"),
            "last_name": _("Last name"),
            "phone": _("Phone"),
            "profile_picture": _("Profile picture"),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user:
            self.fields["username"].initial = user.username
            self.fields["email"].initial = user.email
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name

        for field_name in ["username", "email", "first_name", "last_name", "phone"]:
            self.fields[field_name].widget.attrs["class"] = "form-control"

        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.form_enctype = "multipart/form-data"
        self.helper.add_input(Submit("submit", gettext("Save profile"), css_class="btn btn-primary"))

    def clean_username(self):
        username = self.cleaned_data["username"]
        queryset = User.objects.filter(username=username)
        if self.user:
            queryset = queryset.exclude(pk=self.user.pk)
        if queryset.exists():
            raise forms.ValidationError(gettext("This username is already taken."))
        return username

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self.user:
            self.user.username = self.cleaned_data["username"]
            self.user.email = self.cleaned_data["email"]
            self.user.first_name = self.cleaned_data["first_name"]
            self.user.last_name = self.cleaned_data["last_name"]
            profile.full_name = " ".join(
                name for name in [self.user.first_name, self.user.last_name] if name
            )
            if commit:
                self.user.save()
            profile.user = self.user

        if commit:
            profile.save()
        return profile


class AdminProfileForm(forms.ModelForm):
    username = forms.CharField(label=_("Username"), max_length=150)
    email = forms.EmailField(label=_("Email"), required=False)
    first_name = forms.CharField(label=_("First name"), max_length=150, required=False)
    last_name = forms.CharField(label=_("Last name"), max_length=150, required=False)

    class Meta:
        model = AdminProfile
        fields = ["username", "email", "first_name", "last_name", "phone", "profile_picture"]
        labels = {
            "phone": _("Phone"),
            "profile_picture": _("Profile picture"),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user:
            self.fields["username"].initial = user.username
            self.fields["email"].initial = user.email
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name

        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.form_enctype = "multipart/form-data"
        self.helper.add_input(Submit("submit", gettext("Save profile"), css_class="btn btn-primary"))

    def clean_username(self):
        username = self.cleaned_data["username"]
        queryset = User.objects.filter(username=username)
        if self.user:
            queryset = queryset.exclude(pk=self.user.pk)
        if queryset.exists():
            raise forms.ValidationError(gettext("This username is already taken."))
        return username

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self.user:
            self.user.username = self.cleaned_data["username"]
            self.user.email = self.cleaned_data["email"]
            self.user.first_name = self.cleaned_data["first_name"]
            self.user.last_name = self.cleaned_data["last_name"]
            profile.user = self.user
            if commit:
                self.user.save()

        if commit:
            profile.save()
        return profile


class TherapistProfileForm(forms.ModelForm):
    username = forms.CharField(label=_("Username"), max_length=150)
    email = forms.EmailField(label=_("Email"), required=False)
    first_name = forms.CharField(label=_("First name"), max_length=150, required=False)
    last_name = forms.CharField(label=_("Last name"), max_length=150, required=False)

    class Meta:
        model = Therapist
        fields = [
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "phone",
            "profile_photo",
            "specializations",
            "languages",
            "experience",
            "quote",
            "bio",
            "bio_lt",
            "bio_en",
        ]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 5}),
            "bio_lt": forms.Textarea(attrs={"rows": 5}),
            "bio_en": forms.Textarea(attrs={"rows": 5}),
            "specializations": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "full_name": _("Full name"),
            "phone": _("Phone"),
            "profile_photo": _("Profile photo"),
            "specializations": _("Specializations"),
            "languages": _("Languages"),
            "experience": _("Experience"),
            "quote": _("Personal quote"),
            "bio": _("Fallback biography"),
            "bio_lt": _("Lithuanian biography"),
            "bio_en": _("English biography"),
        }

    def __init__(self, *args, user=None, show_full_name=True, **kwargs):
        self.user = user
        self.show_full_name = show_full_name
        super().__init__(*args, **kwargs)
        if not show_full_name:
            self.fields.pop("full_name")
        if user:
            self.fields["username"].initial = user.username
            self.fields["email"].initial = user.email
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name

        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.form_enctype = "multipart/form-data"
        self.helper.add_input(Submit("submit", _("Save profile"), css_class="btn btn-primary"))

    def clean_username(self):
        username = self.cleaned_data["username"]
        queryset = User.objects.filter(username=username)
        if self.user:
            queryset = queryset.exclude(pk=self.user.pk)
        if queryset.exists():
            raise forms.ValidationError(gettext("This username is already taken."))
        return username

    def save(self, commit=True):
        profile = super().save(commit=False)
        if self.user:
            self.user.username = self.cleaned_data["username"]
            self.user.email = self.cleaned_data["email"]
            self.user.first_name = self.cleaned_data["first_name"]
            self.user.last_name = self.cleaned_data["last_name"]
            profile.user = self.user
            if not self.show_full_name:
                profile.full_name = self.user.get_full_name() or self.user.username
            if commit:
                self.user.save()

        if commit:
            profile.save()
        return profile


class ArticleForm(forms.ModelForm):
    remove_image = forms.BooleanField(required=False, label=_("Remove current image"))

    class Meta:
        model = Article
        fields = [
            "category",
            "title",
            "title_lt",
            "title_en",
            "summary",
            "image",
            "remove_image",
            "body",
            "content_lt",
            "content_en",
            "is_translated_to_en",
            "related_services",
            "is_published",
        ]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 12}),
            "content_lt": forms.Textarea(attrs={"rows": 12}),
            "content_en": forms.Textarea(attrs={"rows": 12}),
            "related_services": forms.CheckboxSelectMultiple,
        }
        labels = {
            "category": _("Category"),
            "title": _("Fallback title"),
            "title_lt": _("Lithuanian title"),
            "title_en": _("English title"),
            "summary": _("Summary"),
            "image": _("Image"),
            "body": _("Fallback content"),
            "content_lt": _("Lithuanian content"),
            "content_en": _("English content"),
            "is_translated_to_en": _("Translated to English"),
            "related_services": _("Related services"),
            "is_published": _("Published"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["related_services"].queryset = Service.objects.filter(is_active=True)
        self.fields["related_services"].label_from_instance = localized_service_label
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.form_enctype = "multipart/form-data"
        self.helper.add_input(Submit("submit", _("Save article"), css_class="btn btn-primary"))

    def save(self, commit=True):
        article = super().save(commit=False)
        if self.cleaned_data.get("remove_image"):
            article.image = ""
        if commit:
            article.save()
            self.save_m2m()
        return article


ABOUT_PAGE_TEXT_FIELDS = [
    "hero_eyebrow",
    "hero_title",
    "hero_subtitle",
    "story_eyebrow",
    "story_title",
    "story_text_1",
    "story_text_2",
    "therapist_eyebrow",
    "therapist_title",
    "therapist_intro",
    "mission",
    "vision",
    "values",
    "process_title",
    "process_1_title",
    "process_1_text",
    "process_2_title",
    "process_2_text",
    "process_3_title",
    "process_3_text",
    "process_4_title",
    "process_4_text",
    "cta_eyebrow",
    "cta_title",
    "cta_text",
]


def localized_about_fields():
    fields = []
    for field_name in ABOUT_PAGE_TEXT_FIELDS:
        fields.extend([f"{field_name}_lt", f"{field_name}_en"])
    return fields


class AboutPageForm(forms.ModelForm):
    title = forms.CharField(required=False, widget=forms.HiddenInput)
    main_text = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = AboutPage
        fields = localized_about_fields()
        widgets = {
            "hero_subtitle_lt": forms.Textarea(attrs={"rows": 3}),
            "hero_subtitle_en": forms.Textarea(attrs={"rows": 3}),
            "story_text_1_lt": forms.Textarea(attrs={"rows": 4}),
            "story_text_1_en": forms.Textarea(attrs={"rows": 4}),
            "story_text_2_lt": forms.Textarea(attrs={"rows": 4}),
            "story_text_2_en": forms.Textarea(attrs={"rows": 4}),
            "therapist_intro_lt": forms.Textarea(attrs={"rows": 3}),
            "therapist_intro_en": forms.Textarea(attrs={"rows": 3}),
            "mission_lt": forms.Textarea(attrs={"rows": 4}),
            "mission_en": forms.Textarea(attrs={"rows": 4}),
            "vision_lt": forms.Textarea(attrs={"rows": 4}),
            "vision_en": forms.Textarea(attrs={"rows": 4}),
            "values_lt": forms.Textarea(attrs={"rows": 4}),
            "values_en": forms.Textarea(attrs={"rows": 4}),
            "process_1_text_lt": forms.Textarea(attrs={"rows": 2}),
            "process_1_text_en": forms.Textarea(attrs={"rows": 2}),
            "process_2_text_lt": forms.Textarea(attrs={"rows": 2}),
            "process_2_text_en": forms.Textarea(attrs={"rows": 2}),
            "process_3_text_lt": forms.Textarea(attrs={"rows": 2}),
            "process_3_text_en": forms.Textarea(attrs={"rows": 2}),
            "process_4_text_lt": forms.Textarea(attrs={"rows": 2}),
            "process_4_text_en": forms.Textarea(attrs={"rows": 2}),
            "cta_text_lt": forms.Textarea(attrs={"rows": 3}),
            "cta_text_en": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "hero_title_lt": _("Lithuanian hero title"),
            "hero_title_en": _("English hero title"),
            "hero_eyebrow_lt": _("Lithuanian hero eyebrow"),
            "hero_eyebrow_en": _("English hero eyebrow"),
            "hero_subtitle_lt": _("Lithuanian hero subtitle"),
            "hero_subtitle_en": _("English hero subtitle"),
            "story_eyebrow_lt": _("Lithuanian story eyebrow"),
            "story_eyebrow_en": _("English story eyebrow"),
            "story_title_lt": _("Lithuanian story title"),
            "story_title_en": _("English story title"),
            "story_text_1_lt": _("Lithuanian story text 1"),
            "story_text_1_en": _("English story text 1"),
            "story_text_2_lt": _("Lithuanian story text 2"),
            "story_text_2_en": _("English story text 2"),
            "therapist_eyebrow_lt": _("Lithuanian therapist eyebrow"),
            "therapist_eyebrow_en": _("English therapist eyebrow"),
            "therapist_title_lt": _("Lithuanian therapist title"),
            "therapist_title_en": _("English therapist title"),
            "therapist_intro_lt": _("Lithuanian therapist intro"),
            "therapist_intro_en": _("English therapist intro"),
            "mission_lt": _("Lithuanian mission"),
            "mission_en": _("English mission"),
            "vision_lt": _("Lithuanian vision"),
            "vision_en": _("English vision"),
            "values_lt": _("Lithuanian values"),
            "values_en": _("English values"),
            "process_title_lt": _("Lithuanian process title"),
            "process_title_en": _("English process title"),
            "process_1_title_lt": _("Lithuanian process step 1 title"),
            "process_1_title_en": _("English process step 1 title"),
            "process_1_text_lt": _("Lithuanian process step 1 text"),
            "process_1_text_en": _("English process step 1 text"),
            "process_2_title_lt": _("Lithuanian process step 2 title"),
            "process_2_title_en": _("English process step 2 title"),
            "process_2_text_lt": _("Lithuanian process step 2 text"),
            "process_2_text_en": _("English process step 2 text"),
            "process_3_title_lt": _("Lithuanian process step 3 title"),
            "process_3_title_en": _("English process step 3 title"),
            "process_3_text_lt": _("Lithuanian process step 3 text"),
            "process_3_text_en": _("English process step 3 text"),
            "process_4_title_lt": _("Lithuanian process step 4 title"),
            "process_4_title_en": _("English process step 4 title"),
            "process_4_text_lt": _("Lithuanian process step 4 text"),
            "process_4_text_en": _("English process step 4 text"),
            "cta_eyebrow_lt": _("Lithuanian CTA eyebrow"),
            "cta_eyebrow_en": _("English CTA eyebrow"),
            "cta_title_lt": _("Lithuanian CTA title"),
            "cta_title_en": _("English CTA title"),
            "cta_text_lt": _("Lithuanian CTA text"),
            "cta_text_en": _("English CTA text"),
        }

    def __init__(self, *args, **kwargs):
        data = args[0] if args else kwargs.get("data")
        instance = kwargs.get("instance")
        if data is not None and instance is not None:
            data = data.copy()
            legacy_title = data.get("title")
            legacy_main_text = data.get("main_text")

            for field_name in ABOUT_PAGE_TEXT_FIELDS:
                if field_name not in data:
                    data[field_name] = getattr(instance, field_name, "")

            if legacy_title:
                data["hero_title_en"] = legacy_title
            if legacy_main_text:
                data["story_text_1_en"] = legacy_main_text

            if args:
                args = (data, *args[1:])
            else:
                kwargs["data"] = data

        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if field.label:
                field.label = gettext(str(field.label))
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.form_enctype = "multipart/form-data"
        self.helper.add_input(Submit("submit", gettext("Save about page"), css_class="btn btn-primary"))

    def save(self, commit=True):
        about_page = super().save(commit=False)
        if self.cleaned_data.get("title"):
            about_page.hero_title = self.cleaned_data["title"]
            about_page.hero_title_en = self.cleaned_data["title"]
        if self.cleaned_data.get("main_text"):
            about_page.story_text_1 = self.cleaned_data["main_text"]
            about_page.story_text_1_en = self.cleaned_data["main_text"]
        if commit:
            about_page.save()
            self.save_m2m()
        return about_page

class WellbeingQuestionForm(forms.ModelForm):
    class Meta:
        model = WellbeingQuestion
        fields = ["question_text", "question_type", "order", "is_active"]
        labels = {
            "question_text": _("Question text"),
            "question_type": _("Question type"),
            "order": _("Order"),
            "is_active": _("Is active"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", gettext("Save question"), css_class="btn btn-primary"))


class WellbeingAnswerOptionForm(forms.ModelForm):
    class Meta:
        model = WellbeingAnswerOption
        fields = ["answer_text", "related_services", "order"]
        widgets = {
            "related_services": forms.CheckboxSelectMultiple,
        }
        labels = {
            "answer_text": _("Answer text"),
            "related_services": _("Related services"),
            "order": _("Order"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["related_services"].queryset = Service.objects.filter(is_active=True)
        self.fields["related_services"].label_from_instance = localized_service_label


class AdviceForTodayForm(forms.ModelForm):
    class Meta:
        model = AdviceForToday
        fields = ["title", "published_date", "quote", "body", "is_active"]
        widgets = {
            "published_date": forms.DateInput(attrs={"type": "date"}),
            "quote": forms.TextInput(attrs={
                "placeholder": _("Small, consistent steps create lasting change."),
            }),
            "body": forms.Textarea(attrs={"rows": 12}),
        }
        labels = {
            "title": _("Title"),
            "published_date": _("Published date"),
            "quote": _("Quote"),
            "body": _("Body"),
            "is_active": _("Is active"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(
            Submit("submit", gettext("Save insight"), css_class="btn btn-primary")
        )

class ArticleCategoryForm(forms.ModelForm):
    class Meta:
        model = ArticleCategory
        fields = ["name", "description"]
        labels = {
            "name": _("Name"),
            "description": _("Description"),
        }
