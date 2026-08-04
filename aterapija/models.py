from datetime import datetime, timedelta
from django.views.generic import TemplateView
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.translation import get_language, gettext, gettext_lazy as _
from django.utils import timezone
from django.utils.text import slugify


DEFAULT_WORK_START_TIME = datetime.strptime("09:00", "%H:%M").time()
DEFAULT_WORK_END_TIME = datetime.strptime("17:00", "%H:%M").time()
DEFAULT_TRANSITION_MINUTES = 30


def current_language_code():
    return (get_language() or "lt").split("-")[0]


def localized_value(lt_value, en_value="", fallback_value=""):
    language = current_language_code()
    if language == "en" and en_value:
        return en_value
    return lt_value or fallback_value or en_value


def make_unique_slug(instance, source_field, slug_field="slug"):
    """Create a unique slug for models that use human-readable URLs."""
    base_slug = slugify(getattr(instance, source_field)) or "item"
    slug = base_slug
    counter = 2
    model_class = instance.__class__

    queryset = model_class.objects.filter(**{slug_field: slug})
    if instance.pk:
        queryset = queryset.exclude(pk=instance.pk)

    while queryset.exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
        queryset = model_class.objects.filter(**{slug_field: slug})
        if instance.pk:
            queryset = queryset.exclude(pk=instance.pk)

    return slug


class ServiceCategory(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = _("service categories")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = make_unique_slug(self, "name")
        super().save(*args, **kwargs)


class Service(models.Model):
    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.PROTECT,
        related_name="services",
    )
    name = models.CharField(max_length=120)
    title_lt = models.CharField(max_length=120, blank=True)
    title_en = models.CharField(max_length=120, blank=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    short_description = models.CharField(max_length=255)
    full_description = models.TextField()
    description_lt = models.TextField(blank=True)
    description_en = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=8, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["category__name", "name"]

    def __str__(self):
        return self.title_lt or self.name

    @property
    def display_title(self):
        return localized_value(self.title_lt, self.title_en, self.name)

    @property
    def display_short_description(self):
        return localized_value(self.description_lt, self.description_en, self.short_description)

    @property
    def display_description(self):
        return localized_value(self.description_lt, self.description_en, self.full_description)

    def save(self, *args, **kwargs):
        if not self.title_lt:
            self.title_lt = self.name
        if not self.name:
            self.name = self.title_lt
        if not self.description_lt:
            self.description_lt = self.full_description or self.short_description
        if not self.full_description:
            self.full_description = self.description_lt
        if not self.short_description:
            self.short_description = self.description_lt[:255]
        if not self.slug:
            self.slug = make_unique_slug(self, "name")
        super().save(*args, **kwargs)


class AboutPage(models.Model):
    hero_eyebrow = models.CharField(max_length=80, default=_("About A Terapija"))
    hero_eyebrow_lt = models.CharField(max_length=80, blank=True)
    hero_eyebrow_en = models.CharField(max_length=80, blank=True)
    hero_title = models.CharField(max_length=200, default=_("Therapy that helps you return to yourself"))
    hero_title_lt = models.CharField(max_length=200, blank=True)
    hero_title_en = models.CharField(max_length=200, blank=True)
    hero_subtitle = models.TextField(default=_("A gentle space where therapeutic care, body awareness and mindful presence meet"))
    hero_subtitle_lt = models.TextField(blank=True)
    hero_subtitle_en = models.TextField(blank=True)

    story_eyebrow = models.CharField(max_length=80, default=_("Our story"))
    story_eyebrow_lt = models.CharField(max_length=80, blank=True)
    story_eyebrow_en = models.CharField(max_length=80, blank=True)
    story_title = models.CharField(max_length=250, default=_("Healing begins when we feel safe enough to understand ourselves"))
    story_title_lt = models.CharField(max_length=250, blank=True)
    story_title_en = models.CharField(max_length=250, blank=True)
    story_text_1 = models.TextField(blank=True)
    story_text_1_lt = models.TextField(blank=True)
    story_text_1_en = models.TextField(blank=True)
    story_text_2 = models.TextField(blank=True)
    story_text_2_lt = models.TextField(blank=True)
    story_text_2_en = models.TextField(blank=True)

    therapist_eyebrow = models.CharField(max_length=80, default=_("Therapist"))
    therapist_eyebrow_lt = models.CharField(max_length=80, blank=True)
    therapist_eyebrow_en = models.CharField(max_length=80, blank=True)
    therapist_title = models.CharField(max_length=160, default=_("Meet your therapist"))
    therapist_title_lt = models.CharField(max_length=160, blank=True)
    therapist_title_en = models.CharField(max_length=160, blank=True)
    therapist_intro = models.TextField(blank=True)
    therapist_intro_lt = models.TextField(blank=True)
    therapist_intro_en = models.TextField(blank=True)

    mission = models.TextField(blank=True)
    mission_lt = models.TextField(blank=True)
    mission_en = models.TextField(blank=True)
    vision = models.TextField(blank=True)
    vision_lt = models.TextField(blank=True)
    vision_en = models.TextField(blank=True)
    values = models.TextField(blank=True)
    values_lt = models.TextField(blank=True)
    values_en = models.TextField(blank=True)

    process_title = models.CharField(max_length=160, default=_("How therapy works"))
    process_title_lt = models.CharField(max_length=160, blank=True)
    process_title_en = models.CharField(max_length=160, blank=True)

    process_1_title = models.CharField(max_length=80, default=_("Book"))
    process_1_title_lt = models.CharField(max_length=80, blank=True)
    process_1_title_en = models.CharField(max_length=80, blank=True)
    process_1_text = models.TextField(blank=True)
    process_1_text_lt = models.TextField(blank=True)
    process_1_text_en = models.TextField(blank=True)

    process_2_title = models.CharField(max_length=80, default=_("Assess"))
    process_2_title_lt = models.CharField(max_length=80, blank=True)
    process_2_title_en = models.CharField(max_length=80, blank=True)
    process_2_text = models.TextField(blank=True)
    process_2_text_lt = models.TextField(blank=True)
    process_2_text_en = models.TextField(blank=True)

    process_3_title = models.CharField(max_length=80, default=_("Therapy"))
    process_3_title_lt = models.CharField(max_length=80, blank=True)
    process_3_title_en = models.CharField(max_length=80, blank=True)
    process_3_text = models.TextField(blank=True)
    process_3_text_lt = models.TextField(blank=True)
    process_3_text_en = models.TextField(blank=True)

    process_4_title = models.CharField(max_length=80, default=_("Integrate"))
    process_4_title_lt = models.CharField(max_length=80, blank=True)
    process_4_title_en = models.CharField(max_length=80, blank=True)
    process_4_text = models.TextField(blank=True)
    process_4_text_lt = models.TextField(blank=True)
    process_4_text_en = models.TextField(blank=True)

    cta_eyebrow = models.CharField(max_length=80, default=_("Begin gently"))
    cta_eyebrow_lt = models.CharField(max_length=80, blank=True)
    cta_eyebrow_en = models.CharField(max_length=80, blank=True)
    cta_title = models.CharField(max_length=160, default=_("Ready to take care of yourself?"))
    cta_title_lt = models.CharField(max_length=160, blank=True)
    cta_title_en = models.CharField(max_length=160, blank=True)
    cta_text = models.TextField(blank=True)
    cta_text_lt = models.TextField(blank=True)
    cta_text_en = models.TextField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "About page"

    def localized_field(self, field_name):
        return localized_value(
            getattr(self, f"{field_name}_lt", ""),
            getattr(self, f"{field_name}_en", ""),
            getattr(self, field_name, ""),
        )

    @property
    def display_hero_title(self):
        return self.localized_field("hero_title")

    @property
    def display_hero_eyebrow(self):
        return self.localized_field("hero_eyebrow")

    @property
    def display_hero_subtitle(self):
        return self.localized_field("hero_subtitle")

    @property
    def display_story_eyebrow(self):
        return self.localized_field("story_eyebrow")

    @property
    def display_story_title(self):
        return self.localized_field("story_title")

    @property
    def display_story_text_1(self):
        return self.localized_field("story_text_1")

    @property
    def display_story_text_2(self):
        return self.localized_field("story_text_2")

    @property
    def display_therapist_eyebrow(self):
        return self.localized_field("therapist_eyebrow")

    @property
    def display_therapist_title(self):
        return self.localized_field("therapist_title")

    @property
    def display_therapist_intro(self):
        return self.localized_field("therapist_intro")

    @property
    def display_mission(self):
        return self.localized_field("mission")

    @property
    def display_vision(self):
        return self.localized_field("vision")

    @property
    def display_values(self):
        return self.localized_field("values")

    @property
    def display_process_title(self):
        return self.localized_field("process_title")

    @property
    def display_process_1_title(self):
        return self.localized_field("process_1_title")

    @property
    def display_process_1_text(self):
        return self.localized_field("process_1_text")

    @property
    def display_process_2_title(self):
        return self.localized_field("process_2_title")

    @property
    def display_process_2_text(self):
        return self.localized_field("process_2_text")

    @property
    def display_process_3_title(self):
        return self.localized_field("process_3_title")

    @property
    def display_process_3_text(self):
        return self.localized_field("process_3_text")

    @property
    def display_process_4_title(self):
        return self.localized_field("process_4_title")

    @property
    def display_process_4_text(self):
        return self.localized_field("process_4_text")

    @property
    def display_cta_eyebrow(self):
        return self.localized_field("cta_eyebrow")

    @property
    def display_cta_title(self):
        return self.localized_field("cta_title")

    @property
    def display_cta_text(self):
        return self.localized_field("cta_text")

    @property
    def title(self):
        return self.hero_title

    @title.setter
    def title(self, value):
        self.hero_title = value

    @property
    def main_text(self):
        return self.story_text_1

    @main_text.setter
    def main_text(self, value):
        self.story_text_1 = value


class Therapist(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="therapist_profile",
    )
    full_name = models.CharField(max_length=160)
    phone = models.CharField(max_length=40, blank=True)
    profile_photo = models.FileField(upload_to="therapist_profiles/", blank=True)
    bio = models.TextField(blank=True)
    bio_lt = models.TextField(blank=True)
    bio_en = models.TextField(blank=True)
    languages = models.CharField(max_length=200, blank=True)
    experience = models.CharField(max_length=200, blank=True)
    quote = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Short personal quote shown on the therapist detail page."),
    )
    specializations = models.TextField(
        blank=True,
        help_text=_("Comma-separated specializations or a short readable list."),
    )
    services = models.ManyToManyField(Service, related_name="therapists", blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name

    @property
    def display_bio(self):
        return localized_value(self.bio_lt, self.bio_en, self.bio)

    def save(self, *args, **kwargs):
        if not self.bio_lt:
            self.bio_lt = self.bio
        if not self.bio:
            self.bio = self.bio_lt
        super().save(*args, **kwargs)

class AboutView(TemplateView):
    template_name = "aterapija/about.html"
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["about"] = AboutPage.objects.first()
        context["therapist"] = (
            Therapist.objects
            .filter(is_active=True)
            .prefetch_related("services")
            .first()
        )
        return context

class TherapistAvailability(models.Model):
    therapist = models.ForeignKey(
        Therapist,
        on_delete=models.CASCADE,
        related_name="availability_slots",
    )
    date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    reason = models.CharField(max_length=200, blank=True)
    is_full_day = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "start_time"]
        verbose_name = _("therapist unavailable time")
        verbose_name_plural = _("therapist unavailable times")

    def __str__(self):
        end_date = self.end_date or self.date
        if self.is_full_day:
            label = "Full day"
        else:
            label = f"{self.start_time:%H:%M}-{self.end_time:%H:%M}"
        date_label = self.date if self.date == end_date else f"{self.date} to {end_date}"
        return f"{self.therapist.full_name} unavailable - {date_label} {label}"

    @staticmethod
    def is_30_minute_step(value):
        return value.minute in (0, 30) and value.second == 0 and value.microsecond == 0

    def clean(self):
        errors = {}

        if self.start_time and not self.is_30_minute_step(self.start_time):
            errors["start_time"] = gettext("Start time must use 30-minute steps.")
        if self.end_time and not self.is_30_minute_step(self.end_time):
            errors["end_time"] = gettext("End time must use 30-minute steps.")
        end_date = self.end_date or self.date
        if self.date and end_date and end_date < self.date:
            errors["end_date"] = gettext("End date must be the same as or after start date.")
        if self.date == end_date and self.start_time and self.end_time and self.start_time >= self.end_time:
            errors["end_time"] = gettext("End time must be after start time.")

        if self.therapist_id and self.date and self.start_time and self.end_time:
            own_end_date = self.end_date or self.date
            overlaps = TherapistAvailability.objects.filter(
                therapist=self.therapist,
                date__lte=own_end_date,
                end_date__gte=self.date,
                start_time__lt=self.end_time,
                end_time__gt=self.start_time,
            )
            if self.pk:
                overlaps = overlaps.exclude(pk=self.pk)
            if overlaps.exists():
                errors["start_time"] = gettext("This unavailable time overlaps another unavailable block.")

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if not self.end_date:
            self.end_date = self.date
        super().save(*args, **kwargs)


class BookingRequest(models.Model):
    STATUS_APPROVED = "approved"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_APPROVED, _("Approved")),
        (STATUS_CANCELLED, _("Cancelled")),
    ]

    client_name = models.CharField(max_length=160)
    client_email = models.EmailField()
    client_phone = models.CharField(max_length=40, blank=True)
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="booking_requests",
        blank=True,
        null=True,
    )
    service = models.ForeignKey(
        Service,
        on_delete=models.PROTECT,
        related_name="booking_requests",
    )
    therapist = models.ForeignKey(
        Therapist,
        on_delete=models.PROTECT,
        related_name="booking_requests",
        blank=True,
        null=True,
    )
    preferred_date = models.DateField()
    preferred_time = models.TimeField()
    message = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_APPROVED,
    )
    payment_received = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.client_name} - {self.service.name} ({self.get_status_display()})"

    @property
    def start_datetime(self):
        naive = datetime.combine(self.preferred_date, self.preferred_time)
        return timezone.make_aware(naive, timezone.get_current_timezone())

    @property
    def end_datetime(self):
        return self.start_datetime + timedelta(minutes=self.service.duration_minutes)

    @property
    def end_time(self):
        return self.end_datetime.timetz().replace(tzinfo=None)

    @property
    def blocked_end_datetime(self):
        return self.end_datetime + timedelta(minutes=DEFAULT_TRANSITION_MINUTES)

    @property
    def blocked_end_time(self):
        return self.blocked_end_datetime.timetz().replace(tzinfo=None)

    def can_client_change_online(self):
        return self.start_datetime > timezone.now() + timedelta(hours=24)

    @classmethod
    def approved(cls):
        return cls.objects.filter(status=cls.STATUS_APPROVED)

    @classmethod
    def is_time_available(cls, therapist, service, preferred_date, preferred_time, exclude_pk=None):
        if not therapist or not service or not preferred_date or not preferred_time:
            return False
        if not therapist.services.filter(pk=service.pk).exists():
            return False

        start_dt = timezone.make_aware(
            datetime.combine(preferred_date, preferred_time),
            timezone.get_current_timezone(),
        )
        end_dt = start_dt + timedelta(minutes=service.duration_minutes + DEFAULT_TRANSITION_MINUTES)
        end_time = end_dt.timetz().replace(tzinfo=None)

        if preferred_time < DEFAULT_WORK_START_TIME or end_time > DEFAULT_WORK_END_TIME:
            return False

        unavailable_blocks = TherapistAvailability.objects.filter(
            therapist=therapist,
            date__lte=preferred_date,
            end_date__gte=preferred_date,
            start_time__lt=end_time,
            end_time__gt=preferred_time,
        )
        if unavailable_blocks.exists():
            return False

        approved_bookings = cls.approved().filter(
            therapist=therapist,
            preferred_date=preferred_date,
        ).select_related("service")
        if exclude_pk:
            approved_bookings = approved_bookings.exclude(pk=exclude_pk)

        for booking in approved_bookings:
            if booking.preferred_time < end_time and booking.blocked_end_time > preferred_time:
                return False

        return True

    def clean(self):
        errors = {}

        if self.status not in {self.STATUS_APPROVED, self.STATUS_CANCELLED}:
            errors["status"] = gettext("Bookings can only be approved or cancelled.")

        if self.status == self.STATUS_APPROVED:
            if not self.therapist_id:
                errors["therapist"] = gettext("Choose a therapist for an approved booking.")
            elif self.service_id and not self.therapist.services.filter(pk=self.service_id).exists():
                errors["service"] = gettext("This therapist does not provide the selected service.")

            if self.therapist_id and self.service_id and self.preferred_date and self.preferred_time:
                if not self.is_time_available(
                    self.therapist,
                    self.service,
                    self.preferred_date,
                    self.preferred_time,
                    exclude_pk=self.pk,
                ):
                    errors["preferred_time"] = gettext("This time is not available.")

        if errors:
            raise ValidationError(errors)


class ContactMessage(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="contact_messages",
        blank=True,
        null=True,
    )
    name = models.CharField(max_length=120)
    email = models.EmailField()
    subject = models.CharField(max_length=200)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} from {self.name}"


class Notification(models.Model):
    TYPE_BOOKING_CREATED = "booking_created"
    TYPE_BOOKING_CANCELLED = "booking_cancelled"
    TYPE_BOOKING_POSTPONED = "booking_postponed"
    TYPE_MESSAGE = "message"
    NOTIFICATION_TYPE_CHOICES = [
        (TYPE_BOOKING_CREATED, _("Booking created")),
        (TYPE_BOOKING_CANCELLED, _("Booking cancelled")),
        (TYPE_BOOKING_POSTPONED, _("Booking postponed")),
        (TYPE_MESSAGE, _("Message")),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    notification_type = models.CharField(max_length=40, choices=NOTIFICATION_TYPE_CHOICES)
    title = models.CharField(max_length=160)
    message = models.TextField(blank=True)
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, blank=True, null=True)
    object_id = models.PositiveIntegerField(blank=True, null=True)
    related_object = GenericForeignKey("content_type", "object_id")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} for {self.recipient}"


class ArticleCategory(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = _("article categories")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = make_unique_slug(self, "name")
        super().save(*args, **kwargs)


class Article(models.Model):
    category = models.ForeignKey(
        ArticleCategory,
        on_delete=models.PROTECT,
        related_name="articles",
    )
    title = models.CharField(max_length=180)
    title_lt = models.CharField(max_length=180, blank=True)
    title_en = models.CharField(max_length=180, blank=True)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    summary = models.CharField(max_length=255)
    image = models.FileField(upload_to="articles/", blank=True)
    body = models.TextField()
    content_lt = models.TextField(blank=True)
    content_en = models.TextField(blank=True)
    is_translated_to_en = models.BooleanField(default=False)
    related_services = models.ManyToManyField(Service, related_name="articles", blank=True)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title_lt or self.title

    @property
    def display_title(self):
        return localized_value(self.title_lt, self.title_en, self.title)

    @property
    def display_content(self):
        return localized_value(self.content_lt, self.content_en, self.body)

    @property
    def has_english_translation(self):
        return self.is_translated_to_en and bool(self.title_en and self.content_en)

    @property
    def show_lithuanian_only_notice(self):
        return current_language_code() == "en" and not self.has_english_translation

    def save(self, *args, **kwargs):
        if not self.title_lt:
            self.title_lt = self.title
        if not self.title:
            self.title = self.title_lt
        if not self.content_lt:
            self.content_lt = self.body
        if not self.body:
            self.body = self.content_lt
        self.is_translated_to_en = bool(self.title_en and self.content_en)
        if not self.slug:
            self.slug = make_unique_slug(self, "title")
        super().save(*args, **kwargs)


class AdviceForToday(models.Model):
    title = models.CharField(max_length=160, default=_("Today's Insight"))
    quote = models.CharField(max_length=220, blank=True)
    body = models.TextField()
    published_date = models.DateField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_date", "-created_at"]
        verbose_name_plural = _("advice for today")

    def __str__(self):
        return f"{self.title} - {self.published_date}"

    def get_absolute_url(self):
        return reverse("aterapija:advice_detail", kwargs={"pk": self.pk})


class WellbeingQuestion(models.Model):
    TYPE_TEXT = "text"
    TYPE_TEXTAREA = "textarea"
    TYPE_SINGLE = "single"
    TYPE_MULTIPLE = "multiple"
    QUESTION_TYPE_CHOICES = [
        (TYPE_TEXT, _("Text input")),
        (TYPE_TEXTAREA, _("Textarea")),
        (TYPE_SINGLE, _("Single choice")),
        (TYPE_MULTIPLE, _("Multiple choice")),
    ]

    question_text = models.CharField(max_length=255)
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPE_CHOICES, default=TYPE_MULTIPLE)
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.question_text


class WellbeingAnswerOption(models.Model):
    question = models.ForeignKey(
        WellbeingQuestion,
        on_delete=models.CASCADE,
        related_name="answer_options",
    )
    answer_text = models.CharField(max_length=255)
    related_services = models.ManyToManyField(Service, related_name="wellbeing_answer_options", blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["question__order", "order", "id"]

    def __str__(self):
        return f"{self.question.question_text}: {self.answer_text}"


class WellbeingAssessment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wellbeing_assessments",
    )
    answer_options = models.ManyToManyField(WellbeingAnswerOption, related_name="assessments", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        if not self.created_at:
            return f"Assessment for {self.user}"
        return f"Assessment for {self.user} on {self.created_at:%Y-%m-%d}"


class WellbeingTextAnswer(models.Model):
    assessment = models.ForeignKey(
        WellbeingAssessment,
        on_delete=models.CASCADE,
        related_name="text_answers",
    )
    question = models.ForeignKey(
        WellbeingQuestion,
        on_delete=models.CASCADE,
        related_name="text_answers",
    )
    answer_text = models.TextField(blank=True)

    class Meta:
        ordering = ["question__order", "question__id"]

    def __str__(self):
        return f"{self.question.question_text}: {self.answer_text[:40]}"


class ClientProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="client_profile",
    )
    full_name = models.CharField(max_length=160, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    profile_picture = models.FileField(upload_to="client_profiles/", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Client profile for {self.user}"


class AdminProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="admin_profile",
    )
    phone = models.CharField(max_length=40, blank=True)
    profile_picture = models.FileField(upload_to="admin_profiles/", blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Admin profile for {self.user}"


class AccessibilityPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="accessibility_preference",
    )
    prefers_reading_support = models.BooleanField(default=False)
    prefers_reduced_visual_load = models.BooleanField(default=False)
    prefers_simple_language = models.BooleanField(default=False)

    def __str__(self):
        return f"Accessibility preferences for {self.user}"
