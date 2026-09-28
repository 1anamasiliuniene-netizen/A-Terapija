from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import (
    AccessibilityPreference,
    AdviceForToday,
    AdminProfile,
    Article,
    ArticleCategory,
    BookingRequest,
    ClientProfile,
    ContactMessage,
    Service,
    ServiceCategory,
    Therapist,
    TherapistAvailability,
    WellbeingAnswerOption,
    WellbeingAssessment,
    WellbeingQuestion,
)


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "name_lt", "name_en", "created_at")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "name_lt", "name_en", "description", "description_lt", "description_en")
    fieldsets = (
        (_("General"), {"fields": ("name", "slug")}),
        (_("Lithuanian content"), {"fields": ("name_lt", "description_lt")}),
        (_("English content"), {"fields": ("name_en", "description_en")}),
        (_("Fallback content"), {"fields": ("description",)}),
    )


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "title_lt", "title_en", "category", "duration_minutes", "price", "is_active")
    list_filter = ("category", "is_active")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = (
        "name",
        "title_lt",
        "title_en",
        "short_description",
        "short_description_lt",
        "short_description_en",
        "full_description",
        "description_lt",
        "description_en",
    )
    fieldsets = (
        (_("General"), {"fields": ("category", "name", "slug", "duration_minutes", "price", "is_active")}),
        (_("Lithuanian content"), {"fields": ("title_lt", "short_description_lt", "description_lt")}),
        (_("English content"), {"fields": ("title_en", "short_description_en", "description_en")}),
        (_("Fallback content"), {"fields": ("short_description", "full_description")}),
    )


@admin.register(Therapist)
class TherapistAdmin(admin.ModelAdmin):
    list_display = ("full_name", "user", "phone", "languages", "experience", "is_active", "created_at")
    list_filter = ("is_active", "services")
    filter_horizontal = ("services",)
    search_fields = ("full_name", "bio", "bio_lt", "bio_en", "languages", "experience", "specializations", "user__username", "user__email")
    fieldsets = (
        (_("General"), {"fields": ("user", "full_name", "phone", "profile_photo", "languages", "experience", "specializations", "services", "is_active")}),
        (_("Lithuanian content"), {"fields": ("bio_lt",)}),
        (_("English content"), {"fields": ("bio_en",)}),
        (_("Fallback content"), {"fields": ("bio",)}),
    )


@admin.register(TherapistAvailability)
class TherapistAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("therapist", "date", "end_date", "start_time", "end_time", "is_full_day", "reason")
    list_filter = ("therapist", "date", "is_full_day")
    search_fields = ("therapist__full_name", "therapist__user__username", "reason")


@admin.register(BookingRequest)
class BookingRequestAdmin(admin.ModelAdmin):
    list_display = (
        "client_name",
        "client",
        "client_email",
        "client_phone",
        "service",
        "therapist",
        "preferred_date",
        "preferred_time",
        "status",
        "created_at",
    )
    list_filter = ("status", "service", "therapist", "preferred_date")
    search_fields = ("client_name", "client_email", "client_phone", "client__username", "message")


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ("subject", "name", "email", "user", "created_at", "is_read")
    list_filter = ("is_read", "created_at")
    search_fields = ("name", "email", "subject", "message", "user__username")


@admin.register(ArticleCategory)
class ArticleCategoryAdmin(admin.ModelAdmin):
    list_display = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "description")


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "title_lt", "title_en", "category", "is_translated_to_en", "is_published", "created_at", "updated_at")
    list_filter = ("category", "is_translated_to_en", "is_published", "related_services")
    filter_horizontal = ("related_services",)
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title", "title_lt", "title_en", "summary", "body", "content_lt", "content_en")
    fieldsets = (
        (_("General"), {"fields": ("category", "slug", "summary", "image", "related_services", "is_published")}),
        (_("Lithuanian content"), {"fields": ("title_lt", "content_lt")}),
        (_("English content"), {"fields": ("title_en", "content_en", "is_translated_to_en")}),
        (_("Fallback content"), {"fields": ("title", "body")}),
    )


@admin.register(AdviceForToday)
class AdviceForTodayAdmin(admin.ModelAdmin):
    list_display = ("title", "published_date", "is_active", "updated_at")
    list_filter = ("is_active", "published_date")
    search_fields = ("title", "body")
    fields = ("title", "published_date", "body", "image", "is_active")


class WellbeingAnswerOptionInline(admin.TabularInline):
    model = WellbeingAnswerOption
    extra = 1
    show_change_link = True


@admin.register(WellbeingQuestion)
class WellbeingQuestionAdmin(admin.ModelAdmin):
    list_display = ("question_text", "order", "is_active")
    list_editable = ("order", "is_active")
    inlines = (WellbeingAnswerOptionInline,)
    search_fields = ("question_text",)


@admin.register(WellbeingAnswerOption)
class WellbeingAnswerOptionAdmin(admin.ModelAdmin):
    list_display = ("answer_text", "question", "order")
    list_filter = ("question", "related_services")
    filter_horizontal = ("related_services",)
    search_fields = ("answer_text", "question__question_text")


@admin.register(WellbeingAssessment)
class WellbeingAssessmentAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at")
    filter_horizontal = ("answer_options",)
    search_fields = ("user__username", "user__email")


@admin.register(ClientProfile)
class ClientProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "full_name", "phone", "updated_at")
    search_fields = ("user__username", "user__email", "full_name", "phone")


@admin.register(AdminProfile)
class AdminProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "updated_at")
    search_fields = ("user__username", "user__email", "phone")


@admin.register(AccessibilityPreference)
class AccessibilityPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "prefers_reading_support",
        "prefers_reduced_visual_load",
        "prefers_simple_language",
    )
    search_fields = ("user__username", "user__email")
