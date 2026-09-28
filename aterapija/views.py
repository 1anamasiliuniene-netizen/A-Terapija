from collections import Counter
from datetime import datetime, timedelta
import secrets
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import Group, User
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.db.models import Count, Prefetch, Q, Sum
from django.db.models.deletion import ProtectedError
from django.forms import inlineformset_factory
from django.core.mail import send_mail
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, FormView, ListView, RedirectView, TemplateView, UpdateView
from django.core.paginator import Paginator
from .auth_helpers import CLIENT_GROUP, get_user_dashboard_url, is_admin_user, is_client_user, is_therapist_user
from .forms import (
    AdminBookingForm,
    AdminClientCreateForm,
    AdminProfileForm,
    AdminServiceForm,
    AdminTherapistCreateForm,
    AdviceForTodayForm,
    AboutPageForm,
    ArticleForm,
    BookingPostponeForm,
    BookingRequestForm,
    ClientProfileForm,
    ClientRegistrationForm,
    ContactForm,
    LocalPasswordResetForm,
    TherapistAvailabilityForm,
    TherapistProfileForm,
    TherapistServiceCategoryForm,
    TherapistServiceForm,
    TherapistServiceLinkForm,
    WellbeingAnswerOptionForm,
    WellbeingQuestionForm, ArticleCategoryForm,
)
from .mixins import AdminRequiredMixin, ClientRequiredMixin, TherapistRequiredMixin
from .models import (
    AdviceForToday,
    AdminProfile,
    AboutPage,
    Article,
    BookingRequest,
    ClientProfile,
    ContactMessage,
    DEFAULT_TRANSITION_MINUTES,
    DEFAULT_WORK_END_TIME,
    DEFAULT_WORK_START_TIME,
    Service,
    ServiceCategory,
    Therapist,
    TherapistAvailability,
    Notification,
    WellbeingAnswerOption,
    WellbeingAssessment,
    WellbeingQuestion,
    WellbeingTextAnswer, ArticleCategory,
)


PENDING_BOOKING_DATA_SESSION_KEY = "pending_booking_data"
PENDING_BOOKING_PATH_SESSION_KEY = "pending_booking_path"
PENDING_ASSESSMENT_SESSION_KEY = "pending_assessment_data"
PENDING_ASSESSMENT_TOKEN_SESSION_KEY = "pending_assessment_token"
ASSESSMENT_ANSWER_OPTION_IDS_SESSION_KEY = "assessment_answer_option_ids"
LATEST_ASSESSMENT_ID_SESSION_KEY = "latest_assessment_id"
PENDING_ASSESSMENT_INVALID = "invalid"
BOOKING_LOOKAHEAD_DAYS = 14


def get_admin_users():
    return User.objects.filter(Q(is_staff=True) | Q(is_superuser=True) | Q(groups__name="Admin")).distinct()


def notification_link_for(user, notification):
    related_object = notification.related_object
    if isinstance(related_object, BookingRequest):
        if is_admin_user(user):
            return reverse("aterapija:admin_booking_request_detail", kwargs={"pk": related_object.pk})
        if is_client_user(user):
            return reverse("aterapija:client_dashboard")
        if is_therapist_user(user):
            return reverse("aterapija:therapist_dashboard")
    if isinstance(related_object, ContactMessage):
        if is_admin_user(user):
            return reverse("aterapija:admin_contact_message_detail", kwargs={"pk": related_object.pk})
        return reverse("aterapija:contact")
    return reverse("aterapija:notifications")


def create_notification(recipient, notification_type, title, message="", related_object=None):
    if not recipient:
        return None
    notification = Notification(
        recipient=recipient,
        notification_type=notification_type,
        title=title,
        message=message,
    )
    if related_object:
        notification.content_type = ContentType.objects.get_for_model(related_object)
        notification.object_id = related_object.pk
    notification.save()
    return notification


def create_notifications(recipients, notification_type, title, message="", related_object=None):
    seen = set()
    for recipient in recipients:
        if recipient and recipient.pk not in seen:
            create_notification(recipient, notification_type, title, message, related_object)
            seen.add(recipient.pk)


def booking_notification_recipients(booking):
    recipients = list(get_admin_users())
    if booking.therapist_id:
        recipients.append(booking.therapist.user)
    return recipients


def notify_booking_created(booking):
    create_notifications(
        booking_notification_recipients(booking),
        Notification.TYPE_BOOKING_CREATED,
        _("New booking"),
        _("%(client_name)s booked %(service)s on %(date)s at %(time)s.") % {
            "client_name": booking.client_name,
            "service": booking.service.display_title,
            "date": booking.preferred_date,
            "time": f"{booking.preferred_time:%H:%M}",
        },
        booking,
    )


def build_assessment_data_from_post(post_data):
    text_answers = {}
    for question in WellbeingQuestion.objects.filter(is_active=True).exclude(
        question_type__in=[WellbeingQuestion.TYPE_SINGLE, WellbeingQuestion.TYPE_MULTIPLE]
    ):
        answer_text = post_data.get(f"question_{question.pk}", "").strip()
        if answer_text:
            text_answers[str(question.pk)] = answer_text

    return {
        "selected_option_ids": post_data.getlist("answers"),
        "text_answers": text_answers,
    }


def clear_assessment_session_data(request):
    request.session.pop(ASSESSMENT_ANSWER_OPTION_IDS_SESSION_KEY, None)
    request.session.pop(LATEST_ASSESSMENT_ID_SESSION_KEY, None)


def save_assessment_for_user(user, assessment_data, request=None):
    selected_option_ids = assessment_data.get("selected_option_ids", [])
    text_answers = assessment_data.get("text_answers", {})

    with transaction.atomic():
        assessment = WellbeingAssessment.objects.create(user=user)
        assessment.answer_options.set(selected_option_ids)
        questions_by_id = WellbeingQuestion.objects.filter(
            pk__in=text_answers.keys(),
            is_active=True,
        ).in_bulk(field_name="id")
        for question_id, answer_text in text_answers.items():
            question = questions_by_id.get(int(question_id))
            if question and answer_text:
                WellbeingTextAnswer.objects.create(
                    assessment=assessment,
                    question=question,
                    answer_text=answer_text,
                )

    if request is not None:
        request.session[ASSESSMENT_ANSWER_OPTION_IDS_SESSION_KEY] = selected_option_ids
        request.session[LATEST_ASSESSMENT_ID_SESSION_KEY] = assessment.id
    return assessment


def store_pending_assessment_for_request(request, assessment_data):
    clear_assessment_session_data(request)
    token = secrets.token_urlsafe(32)
    request.session[PENDING_ASSESSMENT_TOKEN_SESSION_KEY] = token
    request.session[PENDING_ASSESSMENT_SESSION_KEY] = {
        "token": token,
        "answers": assessment_data,
    }


def clear_pending_assessment_for_request(request):
    request.session.pop(PENDING_ASSESSMENT_SESSION_KEY, None)
    request.session.pop(PENDING_ASSESSMENT_TOKEN_SESSION_KEY, None)


def save_pending_assessment_for_request(request):
    pending_assessment = request.session.get(PENDING_ASSESSMENT_SESSION_KEY)
    if not pending_assessment:
        return None
    if not (is_client_user(request.user) or is_therapist_user(request.user)):
        clear_pending_assessment_for_request(request)
        clear_assessment_session_data(request)
        messages.warning(request, _("We could not match your questionnaire answers to this session. Please complete the questionnaire again."))
        return PENDING_ASSESSMENT_INVALID
    if (
        not isinstance(pending_assessment, dict)
        or pending_assessment.get("token") != request.session.get(PENDING_ASSESSMENT_TOKEN_SESSION_KEY)
        or not isinstance(pending_assessment.get("answers"), dict)
    ):
        clear_pending_assessment_for_request(request)
        clear_assessment_session_data(request)
        messages.warning(request, _("We could not match your questionnaire answers to this session. Please complete the questionnaire again."))
        return PENDING_ASSESSMENT_INVALID

    assessment = save_assessment_for_user(request.user, pending_assessment["answers"], request=request)
    clear_pending_assessment_for_request(request)
    messages.success(request, _("Your questionnaire answers were saved."))
    return assessment


def notify_booking_cancelled(booking):
    create_notifications(
        booking_notification_recipients(booking),
        Notification.TYPE_BOOKING_CANCELLED,
        _("Booking cancelled"),
        _("%(client_name)s's booking for %(service)s was cancelled.") % {
            "client_name": booking.client_name,
            "service": booking.service.display_title,
        },
        booking,
    )


def notify_booking_postponed(booking, old_date, old_time):
    create_notifications(
        booking_notification_recipients(booking),
        Notification.TYPE_BOOKING_POSTPONED,
        _("Booking postponed"),
        _("%(client_name)s's booking moved from %(old_date)s %(old_time)s to %(new_date)s %(new_time)s.") % {
            "client_name": booking.client_name,
            "old_date": old_date,
            "old_time": f"{old_time:%H:%M}",
            "new_date": booking.preferred_date,
            "new_time": f"{booking.preferred_time:%H:%M}",
        },
        booking,
    )


def notify_contact_message(contact_message):
    recipients = list(get_admin_users())
    create_notifications(
        recipients,
        Notification.TYPE_MESSAGE,
        _("New message"),
        _("%(name)s sent a message: %(subject)s.") % {
            "name": contact_message.name,
            "subject": contact_message.subject,
        },
        contact_message,
    )


def add_minutes(slot_time, minutes):
    slot_datetime = datetime.combine(timezone.localdate(), slot_time)
    return (slot_datetime + timedelta(minutes=minutes)).time()


def iter_30_minute_times(start_time, end_time, service_duration_minutes):
    current = start_time
    while add_minutes(current, service_duration_minutes) <= end_time:
        yield current
        current = add_minutes(current, 30)


def date_range(start_date, end_date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def get_requested_service_and_therapist(request, service_slug=None, therapist_pk=None):
    service = None
    therapist = None
    service_id = request.GET.get("service") or request.POST.get("service")
    therapist_id = request.GET.get("therapist") or request.POST.get("therapist")

    if service_slug:
        service = get_object_or_404(Service, slug=service_slug, is_active=True)
    elif service_id:
        service = Service.objects.filter(pk=service_id, is_active=True).first()

    if therapist_pk:
        therapist = get_object_or_404(Therapist, pk=therapist_pk, is_active=True)
    elif therapist_id:
        therapist = Therapist.objects.filter(pk=therapist_id, is_active=True).first()

    return service, therapist


def get_slot_therapists(service, therapist=None):
    if not service:
        return Therapist.objects.none()
    if therapist:
        return Therapist.objects.filter(pk=therapist.pk, is_active=True, services=service)
    return service.therapists.filter(is_active=True)


def get_only_active_service_therapist(service):
    if not service:
        return None
    therapists = list(service.therapists.filter(is_active=True)[:2])
    if len(therapists) == 1:
        return therapists[0]
    return None


def build_slot_days(service, therapists, start_date=None, end_date=None, exclude_booking=None):
    if not service:
        return []

    start_date = start_date or timezone.localdate()
    end_date = end_date or start_date + timedelta(days=BOOKING_LOOKAHEAD_DAYS - 1)
    current_date = timezone.localdate()
    current_time = timezone.localtime().time()
    therapists = list(therapists.prefetch_related("services") if hasattr(therapists, "prefetch_related") else therapists)

    days = []
    for slot_date in date_range(start_date, end_date):
        day_slots = []
        for therapist in therapists:
            latest_start = add_minutes(DEFAULT_WORK_END_TIME, -(service.duration_minutes + DEFAULT_TRANSITION_MINUTES))
            slot_time = DEFAULT_WORK_START_TIME
            while slot_time <= latest_start:
                if slot_date > current_date or slot_time > current_time:
                    if BookingRequest.is_time_available(
                        therapist,
                        service,
                        slot_date,
                        slot_time,
                        exclude_pk=exclude_booking.pk if exclude_booking else None,
                    ):
                        day_slots.append(
                            {
                                "therapist": therapist,
                                "time": slot_time,
                                "service_end_time": add_minutes(slot_time, service.duration_minutes),
                                "blocked_end_time": add_minutes(
                                    slot_time,
                                    service.duration_minutes + DEFAULT_TRANSITION_MINUTES,
                                ),
                            }
                        )
                slot_time = add_minutes(slot_time, 30)
        if day_slots:
            days.append(
                {
                    "date": slot_date,
                    "is_today": slot_date == current_date,
                    "slots": sorted(
                        day_slots,
                        key=lambda item: (
                            item["time"],
                            item["therapist"].full_name,
                        ),
                    ),
                }
            )
    return days


def build_busy_periods(therapists, start_date=None, end_date=None):
    start_date = start_date or timezone.localdate()
    end_date = end_date or start_date + timedelta(days=30)
    therapists = list(therapists)

    unavailable = TherapistAvailability.objects.filter(
        therapist__in=therapists,
        date__lte=end_date,
        end_date__gte=start_date,
    ).select_related("therapist")
    bookings = BookingRequest.approved().filter(
        therapist__in=therapists,
        preferred_date__range=(start_date, end_date),
    ).select_related("therapist", "service")

    periods = []
    for block in unavailable:
        periods.append(
            {
                "kind": "unavailable",
                "therapist": block.therapist,
                "date": block.date,
                "end_date": block.end_date,
                "start_time": block.start_time,
                "end_time": block.end_time,
                "title": block.reason or _("Unavailable"),
                "detail": _("Full day") if block.is_full_day else _("Unavailable"),
            }
        )
    for booking in bookings:
        periods.append(
            {
                "kind": "booking",
                "therapist": booking.therapist,
                "date": booking.preferred_date,
                "end_date": booking.preferred_date,
                "start_time": booking.preferred_time,
                "end_time": booking.blocked_end_time,
                "service_end_time": booking.end_time,
                "title": f"{booking.service.display_title} - {booking.client_name}",
                "detail": (
                    _("Service until %(service_end_time)s, Transition until %(blocked_end_time)s") % {
                        "service_end_time": f"{booking.end_time:%H:%M}",
                        "blocked_end_time": f"{booking.blocked_end_time:%H:%M}",
                    }
                ),
            }
        )
    return sorted(periods, key=lambda item: (item["date"], item["start_time"], item["therapist"].full_name))


def build_therapist_week_schedule(therapist, start_date=None):
    start_date = start_date or timezone.localdate()
    end_date = start_date + timedelta(days=6)
    days = list(date_range(start_date, end_date))
    time_slots = []
    current = DEFAULT_WORK_START_TIME
    while current < DEFAULT_WORK_END_TIME:
        time_slots.append(current)
        current = add_minutes(current, 30)

    bookings = list(
        BookingRequest.approved()
        .filter(therapist=therapist, preferred_date__range=(start_date, end_date))
        .select_related("service", "client")
    )
    unavailable_blocks = list(
        TherapistAvailability.objects.filter(
            therapist=therapist,
            date__lte=end_date,
            end_date__gte=start_date,
        )
    )

    week_days = []
    for day in days:
        cells = []
        for slot_time in time_slots:
            slot_end = add_minutes(slot_time, 30)
            booking_match = next(
                (
                    booking
                    for booking in bookings
                    if booking.preferred_date == day
                    and slot_overlaps(slot_time, slot_end, booking.preferred_time, booking.blocked_end_time)
                ),
                None,
            )
            unavailable_match = next(
                (
                    block
                    for block in unavailable_blocks
                    if block.date <= day <= block.end_date
                    and slot_overlaps(slot_time, slot_end, block.start_time, block.end_time)
                ),
                None,
            )

            if booking_match:
                if slot_time < booking_match.end_time:
                    status = "booking"
                    label = booking_match.client_name
                else:
                    status = "buffer"
                    label = _("Transition")
                detail = _("%(service)s: %(start_time)s-%(end_time)s, transition until %(blocked_end_time)s") % {
                    "service": booking_match.service.display_title,
                    "start_time": f"{booking_match.preferred_time:%H:%M}",
                    "end_time": f"{booking_match.end_time:%H:%M}",
                    "blocked_end_time": f"{booking_match.blocked_end_time:%H:%M}",
                }
            elif unavailable_match:
                status = "unavailable"
                label = unavailable_match.reason or _("Unavailable")
                detail = label
            else:
                status = "free"
                label = ""
                detail = ""

            cells.append(
                {
                    "time": slot_time,
                    "status": status,
                    "label": label,
                    "detail": detail,
                }
            )
        week_days.append({"date": day, "cells": cells})

    return {"start_date": start_date, "end_date": end_date, "time_slots": time_slots, "days": week_days}


def get_payment_stats_for_bookings(bookings, today=None):
    today = today or timezone.localdate()
    month_start = today.replace(day=1)
    if month_start.month == 12:
        next_month_start = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month_start = month_start.replace(month=month_start.month + 1)
    paid_bookings = bookings.filter(payment_received=True)

    def aggregate(queryset):
        result = queryset.aggregate(
            total_received=Sum("service__price"),
            paid_booking_count=Count("pk"),
        )
        return {
            "total_received": result["total_received"] or 0,
            "paid_booking_count": result["paid_booking_count"],
        }

    return {
        "today": aggregate(paid_bookings.filter(preferred_date=today)),
        "month": aggregate(paid_bookings.filter(preferred_date__gte=month_start, preferred_date__lt=next_month_start)),
        "all_time": aggregate(paid_bookings),
    }


def get_selected_slot_from_form(form):
    def get_object_or_none(model, value):
        if not value:
            return None
        return model.objects.filter(pk=value).first()

    if form.is_bound:
        return {
            "service": get_object_or_none(Service, form.data.get("service")),
            "therapist": get_object_or_none(Therapist, form.data.get("therapist")),
            "date": form.data.get("preferred_date"),
            "time": form.data.get("preferred_time"),
        }
    initial = form.initial
    return {
        "service": get_object_or_none(Service, initial.get("service")),
        "therapist": get_object_or_none(Therapist, initial.get("therapist")),
        "date": initial.get("preferred_date"),
        "time": initial.get("preferred_time"),
    }


def mark_selected_slot(slot_days, selected_slot):
    selected_therapist = selected_slot.get("therapist")
    selected_date = selected_slot.get("date")
    selected_time = selected_slot.get("time")
    selected_date_value = selected_date.isoformat() if hasattr(selected_date, "isoformat") else selected_date
    selected_time_value = selected_time.strftime("%H:%M") if hasattr(selected_time, "strftime") else selected_time

    for day in slot_days:
        day_value = day["date"].isoformat()
        for slot in day["slots"]:
            slot["is_selected"] = (
                selected_therapist
                and selected_therapist.pk == slot["therapist"].pk
                and selected_date_value == day_value
                and selected_time_value == slot["time"].strftime("%H:%M")
            )
    return slot_days


def build_availability_rows(therapists, service=None, lookahead_days=BOOKING_LOOKAHEAD_DAYS, exclude_booking=None, start_date=None):
    start_date = start_date or timezone.localdate()
    slot_days = build_slot_days(
        service,
        therapists,
        start_date=start_date,
        end_date=start_date + timedelta(days=lookahead_days - 1),
        exclude_booking=exclude_booking,
    )
    therapists = list(therapists)
    rows = []
    for day in slot_days:
        therapist_slots = []
        for therapist in therapists:
            therapist_slots.append(
                {
                    "therapist": therapist,
                    "slots": [slot["time"] for slot in day["slots"] if slot["therapist"].pk == therapist.pk],
                }
            )
        rows.append({"date": day["date"], "therapist_slots": therapist_slots})
    return rows


def slot_overlaps(start_time, end_time, other_start_time, other_end_time):
    return start_time < other_end_time and end_time > other_start_time


def build_assessment_result(assessment):
    selected_options = list(assessment.answer_options.all())
    text_answers = list(assessment.text_answers.all())
    service_scores = Counter()
    for option in selected_options:
        for service in option.related_services.all():
            if service.is_active:
                service_scores[service.pk] += 1

    ordered_service_ids = [service_id for service_id, _score in service_scores.most_common()]
    services_by_id = Service.objects.filter(id__in=ordered_service_ids, is_active=True).in_bulk()
    suggested_services = [
        services_by_id[service_id]
        for service_id in ordered_service_ids
        if service_id in services_by_id
    ]
    try:
        client_profile = assessment.user.client_profile
        client_name = client_profile.full_name
        client_phone = client_profile.phone
    except ClientProfile.DoesNotExist:
        client_name = ""
        client_phone = ""

    return {
        "assessment": assessment,
        "client_name": client_name or assessment.user.get_full_name() or assessment.user.username,
        "client_phone": client_phone,
        "selected_options": selected_options,
        "text_answers": text_answers,
        "suggested_services": suggested_services,
    }


class HomeView(TemplateView):
    template_name = "aterapija/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        advice = AdviceForToday.objects.filter(
            is_active=True,
            published_date=timezone.localdate(),
        ).first()
        context["advice_for_today"] = advice
        if advice:
            context["advice_share_url"] = self.request.build_absolute_uri(advice.get_absolute_url())
        return context


class AboutView(TemplateView):
    template_name = "aterapija/about.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["about_page"] = AboutPage.objects.first()
        context["therapists"] = (
            Therapist.objects
            .filter(is_active=True)
            .prefetch_related(
                Prefetch(
                    "services",
                    queryset=Service.objects.filter(is_active=True),
                    to_attr="active_services",
                )
            )
        )

        return context


class ServiceListView(ListView):
    model = Service
    template_name = "aterapija/services.html"
    context_object_name = "services"

    def get_queryset(self):
        return (
            Service.objects.filter(is_active=True)
            .select_related("category")
            .prefetch_related("therapists")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        featured_service = (
            self.get_queryset()
            .filter(slug__in=["initial-wellbeing-consultation", "wellbeing-consultation"])
            .first()
        )
        service_queryset = self.get_queryset()
        if featured_service:
            service_queryset = service_queryset.exclude(pk=featured_service.pk)

        context["featured_service"] = featured_service
        context["categories"] = ServiceCategory.objects.prefetch_related(
            Prefetch("services", queryset=service_queryset)
        )
        return context


class ServiceDetailView(DetailView):
    model = Service
    template_name = "aterapija/service_detail.html"
    context_object_name = "service"

    def get_queryset(self):
        return Service.objects.filter(is_active=True).select_related("category").prefetch_related("therapists")


class TherapistAnchorRedirectMixin:
    def get_redirect_url(self, *args, **kwargs):
        return f"{reverse('aterapija:about')}#therapist"


class TherapistListRedirectView(TherapistAnchorRedirectMixin, RedirectView):
    permanent = False


class TherapistDetailRedirectView(TherapistAnchorRedirectMixin, RedirectView):
    permanent = False


class TherapistListView(ListView):
    model = Therapist
    template_name = "aterapija/therapists.html"
    context_object_name = "therapists"

    def get_queryset(self):
        return Therapist.objects.filter(is_active=True).prefetch_related("services")


class TherapistDetailView(DetailView):
    model = Therapist
    template_name = "aterapija/therapist_detail.html"
    context_object_name = "therapist"

    def get_queryset(self):
        return Therapist.objects.filter(is_active=True).prefetch_related("services")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_services"] = self.object.services.filter(is_active=True)
        return context


class ArticleListView(ListView):
    model = Article
    template_name = "aterapija/articles.html"
    context_object_name = "articles"

    def get_queryset(self):
        return (
            Article.objects
            .filter(is_published=True)
            .select_related("category")
            .prefetch_related("related_services")
            .order_by("category__name", "-created_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()

        context["advice_for_today"] = AdviceForToday.objects.filter(
            is_active=True,
            published_date=today,
        ).first()

        old_advice_queryset = AdviceForToday.objects.filter(
            is_active=True,
            published_date__lt=today,
        ).order_by("-published_date")

        paginator = Paginator(old_advice_queryset, 7)
        page_number = self.request.GET.get("archive_page")
        archive_page = paginator.get_page(page_number)

        context["old_advice_items"] = archive_page
        context["archive_page"] = archive_page

        if context["advice_for_today"]:
            context["advice_share_url"] = self.request.build_absolute_uri(
                context["advice_for_today"].get_absolute_url()
            )

        return context


class ArticleDetailView(DetailView):
    model = Article
    template_name = "aterapija/article_detail.html"
    context_object_name = "article"

    def get_queryset(self):
        return Article.objects.filter(is_published=True).select_related("category").prefetch_related("related_services")


class ArticleManageRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return is_admin_user(self.request.user) or is_therapist_user(self.request.user)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        return redirect(get_user_dashboard_url(self.request.user))


class ArticleManageListView(ArticleManageRequiredMixin, ListView):
    model = Article
    template_name = "accounts/article_manage_list.html"
    context_object_name = "articles"

    def get_queryset(self):
        return Article.objects.select_related("category").order_by("-created_at")


class ArticleManageCreateView(ArticleManageRequiredMixin, CreateView):
    model = Article
    form_class = ArticleForm
    template_name = "accounts/article_manage_form.html"
    success_url = reverse_lazy("aterapija:article_manage_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.method in ("POST", "PUT"):
            kwargs["files"] = self.request.FILES
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, _("Article was created."))
        return super().form_valid(form)


class ArticleManageUpdateView(ArticleManageRequiredMixin, UpdateView):
    model = Article
    form_class = ArticleForm
    template_name = "accounts/article_manage_form.html"
    success_url = reverse_lazy("aterapija:article_manage_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.method in ("POST", "PUT"):
            kwargs["files"] = self.request.FILES
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, _("Article was updated."))
        return super().form_valid(form)


class ArticleManageDeleteView(ArticleManageRequiredMixin, DeleteView):
    model = Article
    template_name = "accounts/article_manage_confirm_delete.html"
    success_url = reverse_lazy("aterapija:article_manage_list")

    def form_valid(self, form):
        messages.success(self.request, _("Article was deleted."))
        return super().form_valid(form)


class AdviceForTodayDetailView(DetailView):
    model = AdviceForToday
    template_name = "aterapija/advice_detail.html"
    context_object_name = "advice"

    def get_queryset(self):
        return AdviceForToday.objects.filter(
            is_active=True,
            published_date__lte=timezone.localdate(),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["advice_share_url"] = self.request.build_absolute_uri(self.object.get_absolute_url())
        return context

class ArticleCategoryCreateView(ArticleManageRequiredMixin, CreateView):
    model = ArticleCategory
    form_class = ArticleCategoryForm
    template_name = "accounts/article_category_form.html"
    success_url = reverse_lazy("aterapija:article_manage_add")

    def form_valid(self, form):
        messages.success(self.request, _("Article category was created."))
        return super().form_valid(form)

class BookingRequestCreateView(CreateView):
    model = BookingRequest
    form_class = BookingRequestForm
    template_name = "aterapija/booking_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.service, self.therapist = get_requested_service_and_therapist(
            request,
            service_slug=kwargs.get("service_slug"),
            therapist_pk=kwargs.get("therapist_pk"),
        )
        if self.service and not self.therapist:
            self.therapist = get_only_active_service_therapist(self.service)
        self.selected_date = self.get_selected_date()

        if not request.user.is_authenticated:
            messages.info(request, _("Please create a profile before booking an appointment."))
            return redirect(f"{reverse('aterapija:register')}?next={request.path}")

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["service"] = self.service
        kwargs["therapist"] = self.therapist
        kwargs["user"] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        pending_path = self.request.session.get(PENDING_BOOKING_PATH_SESSION_KEY)
        pending_data = self.request.session.get(PENDING_BOOKING_DATA_SESSION_KEY, {})

        if pending_path == self.request.path:
            # Restore values after login/register. The client confirms by submitting again.
            for field_name in self.form_class.Meta.fields:
                if field_name in pending_data:
                    initial[field_name] = pending_data[field_name]

        if self.service:
            initial["service"] = self.service
        if self.therapist:
            initial["therapist"] = self.therapist
        if self.selected_date:
            initial["preferred_date"] = self.selected_date

        return initial

    def get_selected_date(self):
        date_value = self.request.POST.get("preferred_date") or self.request.GET.get("preferred_date")
        if not date_value:
            return None
        try:
            return datetime.strptime(date_value, "%Y-%m-%d").date()
        except ValueError:
            return None

    def post(self, request, *args, **kwargs):
        self.object = None
        form = self.get_form()

        if form.is_valid():
            return self.form_valid(form)
        return self.form_invalid(form)

    def get_client_contact_details(self):
        user = self.request.user
        full_name = " ".join(name for name in [user.first_name, user.last_name] if name).strip()
        phone = ""
        try:
            profile = user.client_profile
            full_name = profile.full_name or full_name
            phone = profile.phone
        except ClientProfile.DoesNotExist:
            pass

        return {
            "client_name": full_name or user.username,
            "client_email": user.email,
            "client_phone": phone,
        }

    def form_valid(self, form):
        contact_details = self.get_client_contact_details()
        form.instance.client = self.request.user
        form.instance.client_name = contact_details["client_name"]
        form.instance.client_email = contact_details["client_email"]
        form.instance.client_phone = contact_details["client_phone"]
        messages.success(self.request, _("Your booking has been approved."))
        self.request.session.pop(PENDING_BOOKING_DATA_SESSION_KEY, None)
        self.request.session.pop(PENDING_BOOKING_PATH_SESSION_KEY, None)
        with transaction.atomic():
            response = super().form_valid(form)
            notify_booking_created(self.object)
            return response

    def get_success_url(self):
        return reverse("aterapija:booking_thanks")

    def get_availability_therapists(self):
        return get_slot_therapists(self.service, self.therapist)

    def get_availability_rows(self):
        therapists = self.get_availability_therapists().prefetch_related("services")
        if not self.selected_date:
            return []
        return build_availability_rows(
            therapists,
            service=self.service,
            lookahead_days=1,
            start_date=self.selected_date,
        )

    def get_slot_days(self):
        if not self.service or not self.selected_date:
            return []
        return build_slot_days(
            self.service,
            self.get_availability_therapists(),
            start_date=self.selected_date,
            end_date=self.selected_date,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["service"] = self.service
        context["therapist"] = self.therapist
        context["selected_date"] = self.selected_date
        context["availability_rows"] = self.get_availability_rows()
        context["services"] = Service.objects.filter(is_active=True)
        active_therapists = self.service.therapists.filter(is_active=True) if self.service else Therapist.objects.filter(is_active=True)
        context["therapists"] = active_therapists
        context["show_therapist_choice"] = active_therapists.count() > 1
        context["slot_days"] = self.get_slot_days()
        return context


class BookingThanksView(TemplateView):
    template_name = "aterapija/booking_thanks.html"


class AssessmentParticipantRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return is_client_user(self.request.user) or is_therapist_user(self.request.user)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        return redirect(get_user_dashboard_url(self.request.user))


class AssessmentParticipantMixin(UserPassesTestMixin):
    def test_func(self):
        user = self.request.user
        return not user.is_authenticated or is_client_user(user) or is_therapist_user(user)

    def handle_no_permission(self):
        return redirect(get_user_dashboard_url(self.request.user))


class AssessmentView(AssessmentParticipantMixin, TemplateView):
    template_name = "aterapija/assessment.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["questions"] = WellbeingQuestion.objects.filter(is_active=True).prefetch_related(
            "answer_options",
            "answer_options__related_services",
        )
        return context

    def post(self, request, *args, **kwargs):
        assessment_data = build_assessment_data_from_post(request.POST)
        if not request.user.is_authenticated:
            store_pending_assessment_for_request(request, assessment_data)
            messages.info(
                request,
                _("Please log in or create an account to save your questionnaire answers and continue."),
            )
            return redirect(f"{reverse('aterapija:login')}?next={reverse('aterapija:assessment_results')}")

        clear_pending_assessment_for_request(request)
        save_assessment_for_user(request.user, assessment_data, request=request)
        return redirect("aterapija:assessment_results")


class AssessmentResultsView(AssessmentParticipantRequiredMixin, TemplateView):
    template_name = "aterapija/assessment_results.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_option_ids = self.request.session.get(ASSESSMENT_ANSWER_OPTION_IDS_SESSION_KEY, [])
        if not selected_option_ids:
            latest_assessment = (
                WellbeingAssessment.objects.filter(user=self.request.user)
                .prefetch_related("answer_options")
                .first()
            )
            if latest_assessment:
                selected_option_ids = list(latest_assessment.answer_options.values_list("id", flat=True))

        selected_options = WellbeingAnswerOption.objects.filter(
            id__in=selected_option_ids
        ).prefetch_related("related_services")
        latest_assessment = None
        latest_assessment_id = self.request.session.get(LATEST_ASSESSMENT_ID_SESSION_KEY)
        if latest_assessment_id:
            latest_assessment = WellbeingAssessment.objects.filter(
                pk=latest_assessment_id,
                user=self.request.user,
            ).prefetch_related("text_answers", "text_answers__question").first()

        service_scores = Counter()
        for option in selected_options:
            for service in option.related_services.filter(is_active=True):
                service_scores[service.pk] += 1

        ordered_service_ids = [service_id for service_id, _score in service_scores.most_common()]
        services_by_id = Service.objects.filter(id__in=ordered_service_ids, is_active=True).in_bulk()
        context["suggested_services"] = [
            services_by_id[service_id]
            for service_id in ordered_service_ids
            if service_id in services_by_id
        ]
        context["selected_options"] = selected_options
        context["text_answers"] = latest_assessment.text_answers.all() if latest_assessment else []
        return context


class ContactView(FormView):
    template_name = "aterapija/contact.html"
    form_class = ContactForm
    success_url = reverse_lazy("aterapija:contact")

    def form_valid(self, form):
        contact_message = form.save(commit=False)
        if self.request.user.is_authenticated:
            contact_message.user = self.request.user
        contact_message.save()
        notify_contact_message(contact_message)
        messages.success(self.request, _("Thank you for your message. We will get back to you soon."),
    extra_tags="contact",
)
        return super().form_valid(form)


class ClientRegistrationView(FormView):
    template_name = "registration/register.html"
    form_class = ClientRegistrationForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(get_user_dashboard_url(request.user))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
        user.groups.add(client_group)
        login(self.request, user)
        messages.success(self.request, _("Your account has been created."))
        pending_assessment = save_pending_assessment_for_request(self.request)
        if pending_assessment == PENDING_ASSESSMENT_INVALID:
            return redirect("aterapija:assessment")
        if pending_assessment:
            return redirect("aterapija:assessment_results")
        clear_assessment_session_data(self.request)
        return redirect(self.get_success_url())

    def get_success_url(self):
        next_url = self.request.GET.get("next") or self.request.POST.get("next")
        if next_url and next_url.startswith("/admin/") and not is_admin_user(self.request.user):
            return get_user_dashboard_url(self.request.user)
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={self.request.get_host()}):
            return next_url
        return reverse("aterapija:client_dashboard")


class RoleAwareLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        pending_assessment = save_pending_assessment_for_request(self.request)
        if pending_assessment == PENDING_ASSESSMENT_INVALID:
            return redirect("aterapija:assessment")
        if pending_assessment:
            return redirect("aterapija:assessment_results")
        clear_assessment_session_data(self.request)
        return response

    def get_success_url(self):
        next_url = self.get_redirect_url()

        # Clients and therapists should never be sent into Django admin after login.
        if next_url and next_url.startswith("/admin/") and not is_admin_user(self.request.user):
            return get_user_dashboard_url(self.request.user)

        return next_url or get_user_dashboard_url(self.request.user)


class LocalPasswordResetView(FormView):
    template_name = "registration/local_password_reset_form.html"
    form_class = LocalPasswordResetForm
    success_url = reverse_lazy("aterapija:password_reset_complete")

    def form_valid(self, form):
        form.save()
        messages.success(self.request, _("Password updated. You can now log in with the new password."))
        return super().form_valid(form)


class LocalPasswordResetCompleteView(TemplateView):
    template_name = "registration/local_password_reset_complete.html"


class DashboardRedirectView(LoginRequiredMixin, TemplateView):
    def get(self, request, *args, **kwargs):
        return redirect(get_user_dashboard_url(request.user))


class NotificationRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return is_admin_user(self.request.user) or is_therapist_user(self.request.user)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        return redirect(get_user_dashboard_url(self.request.user))


class NotificationListView(NotificationRequiredMixin, ListView):
    model = Notification
    template_name = "accounts/notification_list.html"
    context_object_name = "notifications"
    paginate_by = 5

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user).select_related("content_type").order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for notification in context["notifications"]:
            notification.target_url = notification_link_for(self.request.user, notification)
        return context


class NotificationMarkReadView(NotificationRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        notification = get_object_or_404(Notification, pk=kwargs["pk"], recipient=request.user)
        notification.is_read = True
        notification.save(update_fields=["is_read"])
        return redirect(notification_link_for(request.user, notification))


class NotificationMarkAllReadView(NotificationRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        messages.success(request, _("Notifications were marked as read."))
        return redirect("aterapija:notifications")


class ProfileRedirectView(LoginRequiredMixin, TemplateView):
    def get(self, request, *args, **kwargs):
        if is_admin_user(request.user):
            return redirect("aterapija:admin_profile")
        if is_therapist_user(request.user):
            return redirect("aterapija:therapist_profile")
        return redirect("aterapija:client_profile")


class AdminDashboardView(AdminRequiredMixin, TemplateView):
    template_name = "accounts/admin_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["therapists"] = Therapist.objects.prefetch_related("services")
        context["clients"] = User.objects.filter(groups__name=CLIENT_GROUP).order_by("username")
        context["unavailable_blocks"] = TherapistAvailability.objects.select_related("therapist")[:20]
        context["bookings"] = BookingRequest.approved().select_related("client", "service", "therapist")[:20]
        context["earnings"] = (
            Therapist.objects.filter(booking_requests__payment_received=True)
            .annotate(total_received=Sum("booking_requests__service__price", filter=Q(booking_requests__payment_received=True)))
            .order_by("full_name")
        )
        context["busy_periods"] = build_busy_periods(Therapist.objects.filter(is_active=True), end_date=timezone.localdate() + timedelta(days=14))
        context["services"] = Service.objects.filter(is_active=True)
        return context


class AdminAdviceForTodayListView(AdminRequiredMixin, ListView):
    model = AdviceForToday
    template_name = "accounts/admin_advice_list.html"
    context_object_name = "advice_items"

    def get_queryset(self):
        return AdviceForToday.objects.order_by("-published_date", "-pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()

        context["today"] = today

        context["today_advice_items"] = AdviceForToday.objects.filter(
            published_date=today,
        ).order_by("title")

        context["future_advice_items"] = AdviceForToday.objects.filter(
            published_date__gt=today,
        ).order_by("published_date", "title")

        past_advice_queryset = AdviceForToday.objects.filter(
            published_date__lt=today,
        ).order_by("-published_date", "-pk")

        paginator = Paginator(past_advice_queryset, 10)
        page_number = self.request.GET.get("past_page")
        past_page = paginator.get_page(page_number)

        context["past_advice_items"] = past_page

        return context


class AdminAdviceForTodayCreateView(AdminRequiredMixin, CreateView):
    template_name = "accounts/admin_advice_form.html"
    form_class = AdviceForTodayForm
    success_url = reverse_lazy("aterapija:admin_advice_list")

    def get_initial(self):
        initial = super().get_initial()
        initial["title"] = _("Advice for Today")
        initial["published_date"] = timezone.localdate()
        initial["is_active"] = True
        return initial

    def form_valid(self, form):
        messages.success(self.request, _("Advice was scheduled."))
        return super().form_valid(form)


class AdminAdviceForTodayUpdateView(AdminRequiredMixin, UpdateView):
    model = AdviceForToday
    template_name = "accounts/admin_advice_form.html"
    form_class = AdviceForTodayForm
    success_url = reverse_lazy("aterapija:admin_advice_list")

    def form_valid(self, form):
        messages.success(self.request, _("Advice was updated."))
        return super().form_valid(form)


class AdminAboutPageUpdateView(AdminRequiredMixin, UpdateView):
    model = AboutPage
    template_name = "accounts/admin_about_form.html"
    form_class = AboutPageForm
    success_url = reverse_lazy("aterapija:admin_dashboard")

    def get_object(self, queryset=None):
        about_page, _created = AboutPage.objects.get_or_create(pk=1)
        return about_page

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.method in ("POST", "PUT"):
            kwargs["files"] = self.request.FILES
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, _("About page was updated."))
        return super().form_valid(form)


class AdminServiceListView(AdminRequiredMixin, ListView):
    model = Service
    template_name = "accounts/admin_service_list.html"
    context_object_name = "services"

    def get_queryset(self):
        return Service.objects.select_related("category").prefetch_related("therapists")


class AdminServiceCreateView(AdminRequiredMixin, CreateView):
    model = Service
    form_class = AdminServiceForm
    template_name = "accounts/admin_service_form.html"
    success_url = reverse_lazy("aterapija:admin_service_list")

    def form_valid(self, form):
        messages.success(self.request, _("Service was created."))
        return super().form_valid(form)


class AdminServiceCategoryCreateView(AdminRequiredMixin, CreateView):
    model = ServiceCategory
    form_class = TherapistServiceCategoryForm
    template_name = "accounts/service_category_form.html"
    success_url = reverse_lazy("aterapija:admin_service_add")

    def form_valid(self, form):
        messages.success(self.request, _("Service category was created."))
        return super().form_valid(form)


class AdminServiceUpdateView(AdminRequiredMixin, UpdateView):
    model = Service
    form_class = AdminServiceForm
    template_name = "accounts/admin_service_form.html"
    success_url = reverse_lazy("aterapija:admin_service_list")

    def form_valid(self, form):
        messages.success(self.request, _("Service was updated."))
        return super().form_valid(form)


class AdminServiceDeleteView(AdminRequiredMixin, DeleteView):
    model = Service
    template_name = "accounts/admin_service_confirm_delete.html"
    success_url = reverse_lazy("aterapija:admin_service_list")

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except ProtectedError:
            messages.error(self.request, _("This service cannot be deleted because it is used by bookings."))
            return redirect(self.success_url)
        messages.success(self.request, _("Service was deleted."))
        return response


QuestionOptionFormSet = inlineformset_factory(
    WellbeingQuestion,
    WellbeingAnswerOption,
    form=WellbeingAnswerOptionForm,
    extra=4,
    can_delete=True,
)


class AdminQuestionListView(AdminRequiredMixin, ListView):
    model = WellbeingQuestion
    template_name = "accounts/admin_question_list.html"
    context_object_name = "questions"

    def get_queryset(self):
        return WellbeingQuestion.objects.prefetch_related("answer_options")


class AdminQuestionMixin(AdminRequiredMixin):
    model = WellbeingQuestion
    form_class = WellbeingQuestionForm
    template_name = "accounts/admin_question_form.html"
    success_url = reverse_lazy("aterapija:admin_question_list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context["option_formset"] = QuestionOptionFormSet(self.request.POST, instance=self.object)
        else:
            context["option_formset"] = QuestionOptionFormSet(instance=self.object)
        return context

    def form_valid(self, form):
        context = self.get_context_data(form=form)
        option_formset = context["option_formset"]
        with transaction.atomic():
            self.object = form.save()
            option_formset.instance = self.object
            if self.object.question_type in {WellbeingQuestion.TYPE_SINGLE, WellbeingQuestion.TYPE_MULTIPLE}:
                if not option_formset.is_valid():
                    return self.form_invalid(form)
                option_formset.save()
            else:
                self.object.answer_options.all().delete()
        messages.success(self.request, _("Question was saved."))
        return redirect(self.success_url)


class AdminQuestionCreateView(AdminQuestionMixin, CreateView):
    def get_context_data(self, **kwargs):
        self.object = None
        return super().get_context_data(**kwargs)


class AdminQuestionUpdateView(AdminQuestionMixin, UpdateView):
    pass


class AdminQuestionDeleteView(AdminRequiredMixin, DeleteView):
    model = WellbeingQuestion
    template_name = "accounts/admin_question_confirm_delete.html"
    success_url = reverse_lazy("aterapija:admin_question_list")

    def form_valid(self, form):
        messages.success(self.request, _("Question was deleted."))
        return super().form_valid(form)


class TherapistDashboardView(TherapistRequiredMixin, TemplateView):
    template_name = "accounts/therapist_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        therapist = get_object_or_404(Therapist, user=self.request.user)
        context["therapist"] = therapist
        context["unavailable_blocks"] = therapist.availability_slots.all()[:20]
        approved_bookings = BookingRequest.approved().filter(therapist=therapist)
        context["approved_bookings"] = approved_bookings.select_related(
            "client",
            "service",
        )[:20]
        context["payment_stats"] = get_payment_stats_for_bookings(approved_bookings)
        context["busy_periods"] = build_busy_periods([therapist], end_date=timezone.localdate() + timedelta(days=14))
        context["week_schedule"] = build_therapist_week_schedule(therapist)
        return context


class TherapistAvailabilityListView(TherapistRequiredMixin, ListView):
    model = TherapistAvailability
    template_name = "accounts/therapist_availability_list.html"
    context_object_name = "availability_slots"

    def get_queryset(self):
        self.therapist = get_object_or_404(Therapist, user=self.request.user)
        return self.therapist.availability_slots.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["busy_periods"] = build_busy_periods([self.therapist], end_date=timezone.localdate() + timedelta(days=60))
        return context


class TherapistAvailabilityCreateView(TherapistRequiredMixin, CreateView):
    model = TherapistAvailability
    form_class = TherapistAvailabilityForm
    template_name = "accounts/therapist_availability_form.html"
    success_url = reverse_lazy("aterapija:therapist_availability_list")

    def dispatch(self, request, *args, **kwargs):
        self.therapist = get_object_or_404(Therapist, user=request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["therapist"] = self.therapist
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, _("Availability was added."))
        return super().form_valid(form)


class TherapistAvailabilityUpdateView(TherapistRequiredMixin, UpdateView):
    model = TherapistAvailability
    form_class = TherapistAvailabilityForm
    template_name = "accounts/therapist_availability_form.html"
    success_url = reverse_lazy("aterapija:therapist_availability_list")

    def get_queryset(self):
        therapist = get_object_or_404(Therapist, user=self.request.user)
        return therapist.availability_slots.all()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["therapist"] = self.object.therapist
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, _("Availability was updated."))
        return super().form_valid(form)


class TherapistAvailabilityDeleteView(TherapistRequiredMixin, DeleteView):
    model = TherapistAvailability
    template_name = "accounts/therapist_availability_confirm_delete.html"
    success_url = reverse_lazy("aterapija:therapist_availability_list")

    def get_queryset(self):
        therapist = get_object_or_404(Therapist, user=self.request.user)
        return therapist.availability_slots.all()

    def form_valid(self, form):
        messages.success(self.request, _("Availability was deleted."))
        return super().form_valid(form)


class ClientDashboardView(ClientRequiredMixin, TemplateView):
    template_name = "accounts/client_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        now = timezone.localtime()

        bookings = (
            BookingRequest.approved()
            .filter(client=self.request.user)
            .select_related("service", "therapist")
            .order_by("preferred_date", "preferred_time")
        )

        upcoming_bookings = []
        past_bookings = []

        for booking in bookings:
            appointment = timezone.make_aware(
                datetime.combine(
                    booking.preferred_date,
                    booking.preferred_time,
                )
            )

            if appointment >= now:
                upcoming_bookings.append(booking)
            else:
                past_bookings.append(booking)

        context["upcoming_bookings"] = upcoming_bookings
        context["past_bookings"] = list(reversed(past_bookings))

        return context


class ClientBookingCancelView(ClientRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        booking = get_object_or_404(
            BookingRequest,
            pk=kwargs["pk"],
            client=request.user,
            status=BookingRequest.STATUS_APPROVED,
        )
        if not booking.can_client_change_online():
            messages.error(request, _("Cancellation is no longer available online because less than 24 hours remain."))
            return redirect("aterapija:client_dashboard")

        booking.status = BookingRequest.STATUS_CANCELLED
        booking.save(update_fields=["status"])
        notify_booking_cancelled(booking)
        messages.success(request, _("Booking was cancelled."))
        return redirect("aterapija:client_dashboard")


class ClientBookingPostponeView(ClientRequiredMixin, UpdateView):
    model = BookingRequest
    form_class = BookingPostponeForm
    template_name = "accounts/client_booking_postpone.html"
    success_url = reverse_lazy("aterapija:client_dashboard")
    context_object_name = "booking"

    def get_queryset(self):
        return BookingRequest.approved().filter(client=self.request.user).select_related("service", "therapist")

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not self.object.can_client_change_online():
            messages.error(
                request,
                _("Postponement is no longer available online because less than 24 hours remain."),
            )
            return redirect("aterapija:client_dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_selected_date(self):
        date_value = (
                self.request.POST.get("preferred_date")
                or self.request.GET.get("preferred_date")
        )

        if not date_value:
            return self.object.preferred_date

        try:
            return datetime.strptime(date_value, "%Y-%m-%d").date()
        except ValueError:
            return self.object.preferred_date

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        selected_date = self.get_selected_date()

        context["selected_date"] = selected_date

        context["slot_days"] = build_slot_days(
            self.object.service,
            [self.object.therapist],
            start_date=selected_date,
            end_date=selected_date,
            exclude_booking=self.object,
        )

        return context

    def form_valid(self, form):
        old_date = self.object.preferred_date
        old_time = self.object.preferred_time
        messages.success(self.request, _("Booking was postponed."))
        with transaction.atomic():
            response = super().form_valid(form)
            notify_booking_postponed(self.object, old_date, old_time)
            return response


class AdminBookingRequestListView(AdminRequiredMixin, ListView):
    model = BookingRequest
    template_name = "accounts/admin_booking_request_list.html"
    context_object_name = "booking_requests"

    def get_queryset(self):
        return BookingRequest.approved().select_related("client", "service", "therapist")


class AdminBookingRequestCreateView(AdminRequiredMixin, CreateView):
    model = BookingRequest
    form_class = AdminBookingForm
    template_name = "accounts/admin_booking_request_form.html"
    success_url = reverse_lazy("aterapija:admin_booking_request_list")

    def get_initial(self):
        initial = super().get_initial()
        for field_name in ["service", "therapist", "preferred_date", "preferred_time"]:
            value = self.request.GET.get(field_name)
            if value:
                initial[field_name] = value
        initial["status"] = BookingRequest.STATUS_APPROVED
        return initial

    def get_selected_booking_context(self):
        service_id = self.request.POST.get("service") or self.request.GET.get("service")
        therapist_id = self.request.POST.get("therapist") or self.request.GET.get("therapist")
        service = Service.objects.filter(pk=service_id, is_active=True).first() if service_id else None
        if therapist_id:
            therapists = Therapist.objects.filter(pk=therapist_id, is_active=True)
        elif service:
            therapists = service.therapists.filter(is_active=True)
        else:
            therapists = Therapist.objects.none()
        return service, therapists

    def get_date_range(self):
        start_date = timezone.localdate()
        end_date = start_date + timedelta(days=6)
        if self.request.GET.get("date_from"):
            start_date = datetime.strptime(self.request.GET["date_from"], "%Y-%m-%d").date()
        if self.request.GET.get("date_to"):
            end_date = datetime.strptime(self.request.GET["date_to"], "%Y-%m-%d").date()
        return start_date, end_date

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service, therapists = self.get_selected_booking_context()
        start_date, end_date = self.get_date_range()
        context["availability_rows"] = build_availability_rows(therapists, service=service) if service else []
        context["busy_periods"] = build_busy_periods(therapists, start_date=start_date, end_date=end_date) if service else []
        context["services"] = Service.objects.filter(is_active=True)
        context["therapists"] = service.therapists.filter(is_active=True) if service else Therapist.objects.filter(is_active=True)
        context["selected_service"] = service
        context["selected_therapist"] = therapists.first() if therapists.count() == 1 else None
        context["date_from"] = start_date
        context["date_to"] = end_date
        context["selected_slot"] = get_selected_slot_from_form(context["form"])
        context["slot_days"] = (
            mark_selected_slot(
                build_slot_days(service, therapists, start_date=start_date, end_date=end_date),
                context["selected_slot"],
            )
            if service
            else []
        )
        return context

    def form_valid(self, form):
        messages.success(self.request, _("Booking was saved."))
        with transaction.atomic():
            response = super().form_valid(form)
            if self.object.client:
                client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
                self.object.client.groups.add(client_group)
            notify_booking_created(self.object)
            return response


class AdminBookingRequestUpdateView(AdminRequiredMixin, UpdateView):
    model = BookingRequest
    form_class = AdminBookingForm
    template_name = "accounts/admin_booking_request_form.html"
    success_url = reverse_lazy("aterapija:admin_booking_request_list")

    def get_queryset(self):
        return BookingRequest.objects.select_related("client", "service", "therapist")

    def get_selected_booking_context(self):
        service_id = self.request.POST.get("service")
        therapist_id = self.request.POST.get("therapist")
        service = Service.objects.filter(pk=service_id, is_active=True).first() if service_id else self.object.service
        if therapist_id:
            therapists = Therapist.objects.filter(pk=therapist_id, is_active=True)
        else:
            therapists = Therapist.objects.filter(pk=self.object.therapist_id)
        return service, therapists

    def get_date_range(self):
        start_date = self.object.preferred_date
        end_date = start_date + timedelta(days=6)
        if self.request.GET.get("date_from"):
            start_date = datetime.strptime(self.request.GET["date_from"], "%Y-%m-%d").date()
        if self.request.GET.get("date_to"):
            end_date = datetime.strptime(self.request.GET["date_to"], "%Y-%m-%d").date()
        return start_date, end_date

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service, therapists = self.get_selected_booking_context()
        start_date, end_date = self.get_date_range()
        context["availability_rows"] = build_availability_rows(
            therapists,
            service=service,
            exclude_booking=self.object,
        )
        context["busy_periods"] = build_busy_periods(therapists, start_date=start_date, end_date=end_date)
        context["services"] = Service.objects.filter(is_active=True)
        context["therapists"] = service.therapists.filter(is_active=True) if service else Therapist.objects.filter(is_active=True)
        context["selected_service"] = service
        context["selected_therapist"] = therapists.first() if therapists.count() == 1 else None
        context["date_from"] = start_date
        context["date_to"] = end_date
        context["selected_slot"] = {
            "service": service,
            "therapist": therapists.first() if therapists.count() == 1 else self.object.therapist,
            "date": self.request.POST.get("preferred_date") or self.object.preferred_date,
            "time": self.request.POST.get("preferred_time") or self.object.preferred_time,
        }
        context["slot_days"] = mark_selected_slot(
            build_slot_days(
                service,
                therapists,
                start_date=start_date,
                end_date=end_date,
                exclude_booking=self.object,
            ),
            context["selected_slot"],
        )
        return context

    def form_valid(self, form):
        old_date = self.object.preferred_date
        old_time = self.object.preferred_time
        old_status = self.object.status
        messages.success(self.request, _("Booking was updated."))
        with transaction.atomic():
            response = super().form_valid(form)
            if self.object.client:
                client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
                self.object.client.groups.add(client_group)
            if old_status != BookingRequest.STATUS_CANCELLED and self.object.status == BookingRequest.STATUS_CANCELLED:
                notify_booking_cancelled(self.object)
            elif old_date != self.object.preferred_date or old_time != self.object.preferred_time:
                notify_booking_postponed(self.object, old_date, old_time)
            return response


class AdminBookingRequestCancelView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        booking = get_object_or_404(BookingRequest, pk=kwargs["pk"])
        booking.status = BookingRequest.STATUS_CANCELLED
        booking.save(update_fields=["status"])
        notify_booking_cancelled(booking)
        messages.success(request, _("Booking was cancelled."))
        return redirect("aterapija:admin_booking_request_detail", pk=booking.pk)


class BookingPaymentToggleView(LoginRequiredMixin, View):
    def get_booking(self, request, pk):
        queryset = BookingRequest.objects.all()
        if is_admin_user(request.user):
            return get_object_or_404(queryset, pk=pk)
        if is_therapist_user(request.user):
            return get_object_or_404(queryset, pk=pk, therapist__user=request.user)
        return None

    def get_default_redirect_url(self, request):
        if is_admin_user(request.user):
            return reverse("aterapija:admin_booking_request_list")
        return reverse("aterapija:therapist_dashboard")

    def post(self, request, *args, **kwargs):
        booking = self.get_booking(request, kwargs["pk"])
        if booking is None:
            return redirect(get_user_dashboard_url(request.user))
        booking.payment_received = request.POST.get("payment_received") == "on"
        booking.save(update_fields=["payment_received"])
        next_url = request.POST.get("next") or self.get_default_redirect_url(request)
        messages.success(request, _("Payment status was updated."))
        return redirect(next_url)


class AdminBookingPaymentToggleView(BookingPaymentToggleView):
    pass


class TherapistBookingPaymentToggleView(BookingPaymentToggleView):
    pass


class AdminClientCreateView(AdminRequiredMixin, CreateView):
    form_class = AdminClientCreateForm
    template_name = "accounts/admin_client_form.html"
    success_url = reverse_lazy("aterapija:admin_booking_request_add")

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.object.user
        if user.email:
            send_mail(
                _("Your A Terapija account"),
                (
                    _("Hello,\n\nAn A Terapija account has been created for you.\n\nUsername: %(username)s\nTemporary password: %(password)s\n\nPlease log in and change your password.")
                    % {
                        "username": user.username,
                        "password": form.temporary_password,
                    }
                ),
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
            messages.success(self.request, _("Client profile was created and login details were emailed."))
        else:
            messages.success(self.request, _("Client profile was created. No email was sent because the client has no email address."))
        return response


class AdminBookingRequestDetailView(AdminRequiredMixin, DetailView):
    model = BookingRequest
    template_name = "accounts/admin_booking_request_detail.html"
    context_object_name = "booking_request"

    def get_queryset(self):
        return BookingRequest.objects.select_related("client", "service", "therapist")


class AdminTherapistListView(AdminRequiredMixin, ListView):
    model = Therapist
    template_name = "accounts/admin_therapist_list.html"
    context_object_name = "therapists"

    def get_queryset(self):
        return Therapist.objects.select_related("user").prefetch_related("services")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for therapist in context["therapists"]:
            therapist.service_category_names = sorted({service.category.display_title for service in therapist.services.all()})
        return context


class AdminTherapistCreateView(AdminRequiredMixin, FormView):
    template_name = "accounts/admin_therapist_form.html"
    form_class = AdminTherapistCreateForm
    success_url = reverse_lazy("aterapija:admin_therapist_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.method in ("POST", "PUT"):
            kwargs["files"] = self.request.FILES
        return kwargs

    def form_valid(self, form):
        form.save()
        messages.success(self.request, _("Therapist profile was created."))
        return super().form_valid(form)


class AdminTherapistUpdateView(AdminRequiredMixin, FormView):
    template_name = "accounts/admin_therapist_form.html"
    form_class = TherapistProfileForm
    success_url = reverse_lazy("aterapija:admin_therapist_list")

    def dispatch(self, request, *args, **kwargs):
        self.profile = get_object_or_404(Therapist.objects.select_related("user"), pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.profile
        kwargs["user"] = self.profile.user
        if self.request.method in ("POST", "PUT"):
            kwargs["files"] = self.request.FILES
        return kwargs

    def form_valid(self, form):
        form.save()
        messages.success(self.request, _("Therapist profile updated."))
        return super().form_valid(form)


class AdminProfileView(AdminRequiredMixin, FormView):
    template_name = "accounts/admin_profile.html"
    form_class = AdminProfileForm
    success_url = reverse_lazy("aterapija:admin_dashboard")

    def dispatch(self, request, *args, **kwargs):
        self.profile, _created = AdminProfile.objects.get_or_create(user=request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.profile
        kwargs["user"] = self.request.user
        if self.request.method in ("POST", "PUT"):
            kwargs["files"] = self.request.FILES
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["profile"] = self.profile
        return context

    def form_valid(self, form):
        form.save()
        messages.success(self.request, _("Profile updated."))
        return super().form_valid(form)


class TherapistServiceMixin(TherapistRequiredMixin):
    success_url = reverse_lazy("aterapija:therapist_service_list")

    def dispatch(self, request, *args, **kwargs):
        self.therapist = get_object_or_404(Therapist, user=request.user)
        return super().dispatch(request, *args, **kwargs)


class TherapistServiceListView(TherapistServiceMixin, ListView):
    model = Service
    template_name = "accounts/therapist_service_list.html"
    context_object_name = "services"

    def get_queryset(self):
        return self.therapist.services.select_related("category").prefetch_related("therapists")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["available_services_count"] = Service.objects.filter(is_active=True).exclude(
            therapists=self.therapist
        ).count()
        return context


class TherapistServiceCreateView(TherapistServiceMixin, CreateView):
    model = Service
    form_class = TherapistServiceForm
    template_name = "accounts/therapist_service_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        self.object.therapists.add(self.therapist)
        messages.success(self.request, _("Service was created and linked to your profile."))
        return response


class TherapistServiceCategoryCreateView(TherapistServiceMixin, CreateView):
    model = ServiceCategory
    form_class = TherapistServiceCategoryForm
    template_name = "accounts/therapist_service_category_form.html"
    success_url = reverse_lazy("aterapija:therapist_service_add")

    def form_valid(self, form):
        messages.success(self.request, _("Service category was created."))
        return super().form_valid(form)


class TherapistServiceUpdateView(TherapistServiceMixin, UpdateView):
    model = Service
    form_class = TherapistServiceForm
    template_name = "accounts/therapist_service_form.html"

    def get_queryset(self):
        return self.therapist.services.select_related("category")

    def form_valid(self, form):
        messages.success(self.request, _("Service was updated."))
        return super().form_valid(form)


class TherapistServiceDeleteView(TherapistServiceMixin, DeleteView):
    model = Service
    template_name = "accounts/therapist_service_confirm_delete.html"

    def get_queryset(self):
        return self.therapist.services.prefetch_related("therapists")

    def form_valid(self, form):
        service = self.object
        has_other_therapists = service.therapists.exclude(pk=self.therapist.pk).exists()
        if has_other_therapists or service.booking_requests.exists():
            service.therapists.remove(self.therapist)
            messages.success(self.request, _("Service was removed from your profile."))
            return redirect(self.success_url)

        try:
            response = super().form_valid(form)
        except ProtectedError:
            service.therapists.remove(self.therapist)
            messages.success(self.request, _("Service was removed from your profile because it is used elsewhere."))
            return redirect(self.success_url)

        messages.success(self.request, _("Service was deleted."))
        return response


class TherapistServiceLinkView(TherapistServiceMixin, FormView):
    form_class = TherapistServiceLinkForm
    template_name = "accounts/therapist_service_link.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["therapist"] = self.therapist
        return kwargs

    def form_valid(self, form):
        services = form.cleaned_data["services"]
        self.therapist.services.add(*services)
        messages.success(self.request, _("Selected services were linked to your profile."))
        return super().form_valid(form)


class AdminAssessmentListView(AdminRequiredMixin, ListView):
    model = WellbeingAssessment
    template_name = "accounts/admin_assessment_list.html"
    context_object_name = "assessment_results"

    def get_queryset(self):
        return WellbeingAssessment.objects.select_related("user", "user__client_profile").prefetch_related(
            "answer_options",
            "answer_options__question",
            "answer_options__related_services",
            "text_answers",
            "text_answers__question",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["assessment_results"] = [
            build_assessment_result(assessment)
            for assessment in context["assessment_results"]
        ]
        return context


class AdminAssessmentDetailView(AdminRequiredMixin, DetailView):
    model = WellbeingAssessment
    template_name = "accounts/admin_assessment_detail.html"
    context_object_name = "assessment"

    def get_queryset(self):
        return WellbeingAssessment.objects.select_related("user", "user__client_profile").prefetch_related(
            "answer_options",
            "answer_options__question",
            "answer_options__related_services",
            "text_answers",
            "text_answers__question",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["result"] = build_assessment_result(self.object)
        return context


class AdminContactMessageListView(AdminRequiredMixin, ListView):
    model = ContactMessage
    template_name = "accounts/admin_contact_message_list.html"
    context_object_name = "contact_messages"

    def get_queryset(self):
        return ContactMessage.objects.select_related("user")


class AdminContactMessageDetailView(AdminRequiredMixin, DetailView):
    model = ContactMessage
    template_name = "accounts/admin_contact_message_detail.html"
    context_object_name = "contact_message"

    def get_queryset(self):
        return ContactMessage.objects.select_related("user")


class ClientProfileView(ClientRequiredMixin, FormView):
    template_name = "accounts/client_profile.html"
    form_class = ClientProfileForm
    success_url = reverse_lazy("aterapija:client_dashboard")

    def dispatch(self, request, *args, **kwargs):
        self.profile, _created = ClientProfile.objects.get_or_create(user=request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.profile
        kwargs["user"] = self.request.user
        if self.request.method in ("POST", "PUT"):
            kwargs["files"] = self.request.FILES
        return kwargs

    def form_valid(self, form):
        form.save()
        messages.success(self.request, _("Profile updated."))
        return super().form_valid(form)


class TherapistProfileView(TherapistRequiredMixin, FormView):
    template_name = "accounts/therapist_profile.html"
    form_class = TherapistProfileForm
    success_url = reverse_lazy("aterapija:therapist_dashboard")

    def dispatch(self, request, *args, **kwargs):
        self.profile, _created = Therapist.objects.get_or_create(
            user=request.user,
            defaults={"full_name": request.user.get_full_name() or request.user.username},
        )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.profile
        kwargs["user"] = self.request.user
        kwargs["show_full_name"] = False
        if self.request.method in ("POST", "PUT"):
            kwargs["files"] = self.request.FILES
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["profile"] = self.profile
        return context


    def form_valid(self, form):
        form.save()
        messages.success(self.request, _("Profile updated."))
        return super().form_valid(form)


class PrivacyView(TemplateView):
    template_name = "aterapija/legal/privacy.html"


class CookiesView(TemplateView):
    template_name = "aterapija/legal/cookies.html"


class TermsView(TemplateView):
    template_name = "aterapija/legal/terms.html"
