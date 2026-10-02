from datetime import time, timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as DjangoTestClient, TestCase
from django.urls import reverse
from django.utils.translation import activate
from django.utils import timezone

from .models import (
    AdviceForToday,
    AboutPage,
    Article,
    ArticleCategory,
    BookingRequest,
    ClientProfile,
    ContactMessage,
    Notification,
    Service,
    ServiceCategory,
    Therapist,
    TherapistAvailability,
    WellbeingAnswerOption,
    WellbeingAssessment,
    WellbeingQuestion,
    WellbeingTextAnswer,
)
from .auth_helpers import CLIENT_GROUP, THERAPIST_GROUP
from .views import build_therapist_week_schedule


class BookingAvailabilityTests(TestCase):
    def setUp(self):
        activate("lt")
        user = get_user_model().objects.create_user(username="therapist")
        self.category = ServiceCategory.objects.create(
            name="Demo Category",
            description="Demo category.",
        )
        self.service = Service.objects.create(
            category=self.category,
            name="Demo Service",
            short_description="Short demo service.",
            full_description="Long demo service.",
            duration_minutes=60,
            price="50.00",
            is_active=True,
        )
        self.therapist = Therapist.objects.create(
            user=user,
            full_name="Demo Therapist",
            is_active=True,
        )
        self.therapist.services.add(self.service)

    def add_unavailable_block(self, slot_date=None, start=time(9, 0), end=time(12, 0)):
        return TherapistAvailability.objects.create(
            therapist=self.therapist,
            date=slot_date or timezone.localdate() + timedelta(days=1),
            end_date=slot_date or timezone.localdate() + timedelta(days=1),
            start_time=start,
            end_time=end,
        )

    def test_guest_is_redirected_to_register_before_booking(self):
        response = self.client.get(reverse("aterapija:booking_create"))

        self.assertRedirects(
            response,
            f"{reverse('aterapija:register')}?next={reverse('aterapija:booking_create')}",
        )

    def test_authenticated_booking_form_has_submit_button_and_hides_booked_slot(self):
        client_user = get_user_model().objects.create_user(
            username="client",
            email="client@example.com",
        )
        self.client.force_login(client_user)
        booked_date = timezone.localdate() + timedelta(days=1)
        BookingRequest.objects.create(
            client_name="Booked Client",
            client_email="booked@example.com",
            service=self.service,
            therapist=self.therapist,
            preferred_date=booked_date,
            preferred_time=time(9, 0),
            status=BookingRequest.STATUS_APPROVED,
        )

        response = self.client.get(
            reverse(
                "aterapija:booking_for_service_and_therapist",
                kwargs={"service_slug": self.service.slug, "therapist_pk": self.therapist.pk},
            )
        )

        self.assertContains(response, "Rezervuoti vizitą")
        self.assertContains(response, "Laisvi laikai")
        self.assertContains(response, 'id="booking-date"')
        self.assertNotContains(response, 'id="booking-therapist"')
        self.assertNotContains(response, "10:30")
        self.assertEqual(response.context["slot_days"], [])

        response = self.client.get(
            reverse(
                "aterapija:booking_for_service_and_therapist",
                kwargs={"service_slug": self.service.slug, "therapist_pk": self.therapist.pk},
            ),
            {"preferred_date": booked_date.isoformat()},
        )

        self.assertContains(response, "10:30")
        self.assertNotContains(response, 'name="client_name"')
        self.assertNotContains(response, 'name="client_email"')
        self.assertNotContains(response, 'name="client_phone"')
        self.assertEqual(len(response.context["slot_days"]), 1)
        self.assertEqual(response.context["slot_days"][0]["date"], booked_date)
        tomorrow_row = next(
            row for row in response.context["availability_rows"] if row["date"] == booked_date
        )
        tomorrow_slots = tomorrow_row["therapist_slots"][0]["slots"]
        self.assertNotIn(time(9, 0), tomorrow_slots)
        self.assertNotIn(time(10, 0), tomorrow_slots)
        self.assertIn(time(10, 30), tomorrow_slots)

    def test_booking_page_shows_no_slots_message_for_selected_unavailable_date(self):
        client_user = get_user_model().objects.create_user(username="client-no-slots")
        self.client.force_login(client_user)
        unavailable_date = timezone.localdate() + timedelta(days=1)
        self.add_unavailable_block(slot_date=unavailable_date, start=time(9, 0), end=time(17, 0))

        response = self.client.get(
            reverse("aterapija:booking_for_service", kwargs={"service_slug": self.service.slug}),
            {"preferred_date": unavailable_date.isoformat()},
        )

        self.assertContains(response, "Šią dieną nėra laisvų laikų. Pasirinkite kitą datą.")
        self.assertEqual(response.context["slot_days"], [])

    def test_authenticated_booking_uses_profile_contact_details(self):
        client_user = get_user_model().objects.create_user(
            username="client",
            email="client@example.com",
            first_name="Client",
            last_name="User",
        )
        ClientProfile.objects.create(
            user=client_user,
            full_name="Client User",
            phone="+37060000000",
        )
        self.client.force_login(client_user)

        response = self.client.post(
            reverse("aterapija:booking_create"),
            {
                "service": self.service.pk,
                "therapist": self.therapist.pk,
                "preferred_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
                "preferred_time": "10:00",
                "message": "Please book this time.",
            },
        )

        self.assertRedirects(response, reverse("aterapija:booking_thanks"))
        booking = BookingRequest.objects.get(client=client_user)
        self.assertEqual(booking.client_name, "Client User")
        self.assertEqual(booking.client_email, "client@example.com")
        self.assertEqual(booking.client_phone, "+37060000000")
        self.assertEqual(booking.status, BookingRequest.STATUS_APPROVED)

    def test_booking_post_auto_uses_only_active_therapist(self):
        client_user = get_user_model().objects.create_user(
            username="client-auto-therapist",
            email="auto@example.com",
        )
        self.client.force_login(client_user)

        response = self.client.post(
            reverse("aterapija:booking_for_service", kwargs={"service_slug": self.service.slug}),
            {
                "preferred_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
                "preferred_time": "10:00",
                "message": "",
            },
        )

        self.assertRedirects(response, reverse("aterapija:booking_thanks"))
        booking = BookingRequest.objects.get(client=client_user)
        self.assertEqual(booking.service, self.service)
        self.assertEqual(booking.therapist, self.therapist)

    def test_admin_can_see_booking_requests_compact_and_detail_with_phone(self):
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )
        booking = BookingRequest.objects.create(
            client_name="Client User",
            client_email="client@example.com",
            client_phone="+37060000000",
            service=self.service,
            therapist=self.therapist,
            preferred_date=timezone.localdate() + timedelta(days=1),
            preferred_time=time(10, 0),
            status=BookingRequest.STATUS_APPROVED,
            message="Please book this time.",
        )
        self.client.force_login(admin)

        list_response = self.client.get(reverse("aterapija:admin_booking_request_list"))

        self.assertContains(list_response, "Rezervacijos")
        self.assertContains(list_response, "Client User")
        self.assertContains(list_response, "+37060000000")
        self.assertContains(
            list_response,
            reverse("aterapija:admin_booking_request_detail", kwargs={"pk": booking.pk}),
        )

        detail_response = self.client.get(
            reverse("aterapija:admin_booking_request_detail", kwargs={"pk": booking.pk})
        )

        self.assertContains(detail_response, "+37060000000")
        self.assertContains(detail_response, "Please book this time.")

    def test_admin_booking_form_without_selected_slot_shows_error(self):
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )
        client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
        client_user = get_user_model().objects.create_user(username="client", email="client@example.com")
        client_user.groups.add(client_group)
        ClientProfile.objects.create(user=client_user, full_name="Client User")
        self.client.force_login(admin)

        response = self.client.post(
            reverse("aterapija:admin_booking_request_add"),
            {
                "client": client_user.pk,
                "service": "",
                "therapist": "",
                "preferred_date": "",
                "preferred_time": "",
                "message": "",
                "status": BookingRequest.STATUS_APPROVED,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Norėdami išsaugoti, pasirinkite laiką.")

    def test_admin_can_create_booking_for_existing_client_from_selected_slot(self):
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )
        client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
        client_user = get_user_model().objects.create_user(
            username="ana",
            email="ana@example.com",
            first_name="Ana",
            last_name="Client",
        )
        client_user.groups.add(client_group)
        ClientProfile.objects.create(user=client_user, full_name="Ana Client", phone="+37060000001")
        self.client.force_login(admin)
        booking_date = timezone.localdate() + timedelta(days=2)

        response = self.client.post(
            reverse("aterapija:admin_booking_request_add"),
            {
                "client": client_user.pk,
                "service": self.service.pk,
                "therapist": self.therapist.pk,
                "preferred_date": booking_date.isoformat(),
                "preferred_time": "10:00",
                "message": "Phone booking.",
                "status": BookingRequest.STATUS_APPROVED,
            },
        )

        self.assertRedirects(response, reverse("aterapija:admin_booking_request_list"))
        booking = BookingRequest.objects.get(client=client_user)
        self.assertEqual(booking.client_name, "Ana Client")
        self.assertEqual(booking.client_email, "ana@example.com")
        self.assertEqual(booking.client_phone, "+37060000001")
        self.assertEqual(booking.service, self.service)
        self.assertEqual(booking.therapist, self.therapist)

    def test_admin_slot_generator_excludes_therapist_who_does_not_provide_service(self):
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )
        other_user = get_user_model().objects.create_user(username="other_therapist")
        other_therapist = Therapist.objects.create(
            user=other_user,
            full_name="Other Therapist",
            is_active=True,
        )
        self.client.force_login(admin)

        response = self.client.get(
            reverse("aterapija:admin_booking_request_add"),
            {"service": self.service.pk, "therapist": other_therapist.pk},
        )

        self.assertContains(response, "Nėra šį pasirinkimą atitinkančių laisvų laikų.")
        self.assertNotContains(response, "Other Therapist</span>")

    def test_therapist_week_schedule_marks_booking_and_buffer(self):
        booking_date = timezone.localdate() + timedelta(days=1)
        BookingRequest.objects.create(
            client_name="Ana Client",
            client_email="ana@example.com",
            service=self.service,
            therapist=self.therapist,
            preferred_date=booking_date,
            preferred_time=time(10, 0),
            status=BookingRequest.STATUS_APPROVED,
        )

        schedule = build_therapist_week_schedule(self.therapist, start_date=timezone.localdate())
        day = next(day for day in schedule["days"] if day["date"] == booking_date)
        cells_by_time = {cell["time"]: cell for cell in day["cells"]}

        self.assertEqual(cells_by_time[time(10, 0)]["status"], "booking")
        self.assertEqual(cells_by_time[time(10, 30)]["status"], "booking")
        self.assertEqual(cells_by_time[time(11, 0)]["status"], "buffer")


class TherapistProfileTests(TestCase):
    def setUp(self):
        activate("lt")
        self.therapist_user = get_user_model().objects.create_user(
            username="therapist_profile_user",
            email="therapist@example.com",
        )
        self.category = ServiceCategory.objects.create(
            name="Therapist Services",
            description="Services managed by therapists.",
        )
        self.therapist = Therapist.objects.create(
            user=self.therapist_user,
            full_name="Profile Therapist",
            languages="English, Lithuanian",
            experience="8 years",
            bio="Short therapist bio.",
            specializations="Sleep, stress",
            is_active=True,
        )

    def test_about_page_shows_therapist_detail_content(self):
        response = self.client.get(reverse("aterapija:about"))

        self.assertContains(response, "Profile Therapist")
        self.assertContains(response, "Sleep, stress")
        self.assertContains(response, "English, Lithuanian")
        self.assertContains(response, "8 years")
        self.assertContains(response, 'id="therapists"')
        self.assertContains(response, "Susipažinkite su mūsų terapeutais")
        self.assertNotContains(response, f'href="{reverse("aterapija:therapists")}"')

    def test_public_therapist_urls_redirect_to_about_therapist_anchor(self):
        response = self.client.get(reverse("aterapija:therapists"))
        self.assertRedirects(response, f"{reverse('aterapija:about')}#therapists", fetch_redirect_response=False)

        response = self.client.get(reverse("aterapija:therapist_detail", kwargs={"pk": self.therapist.pk}))
        self.assertRedirects(response, f"{reverse('aterapija:about')}#therapists", fetch_redirect_response=False)

    def test_admin_can_edit_therapist_profile_fields(self):
        admin = get_user_model().objects.create_user(username="admin_profile", is_staff=True)
        self.client.force_login(admin)

        response = self.client.post(
            reverse("aterapija:admin_therapist_edit", kwargs={"pk": self.therapist.pk}),
            {
                "username": self.therapist_user.username,
                "email": "updated@example.com",
                "first_name": "",
                "last_name": "",
                "full_name": "Updated Therapist",
                "phone": "",
                "languages": "English",
                "experience": "10 years",
                "bio": "Updated bio.",
                "specializations": "Anxiety",
            },
        )

        self.assertRedirects(response, reverse("aterapija:admin_therapist_list"))
        self.therapist.refresh_from_db()
        self.assertEqual(self.therapist.full_name, "Updated Therapist")
        self.assertEqual(self.therapist.languages, "English")
        self.assertEqual(self.therapist.experience, "10 years")

    def test_admin_therapist_list_shows_contact_details(self):
        admin = get_user_model().objects.create_user(username="admin_profile", is_staff=True)
        self.therapist.phone = "+37060000001"
        self.therapist.save()
        first_service = Service.objects.create(
            category=self.category,
            name="Admin Therapist List Service",
            short_description="Short.",
            full_description="Long.",
            duration_minutes=60,
            price="70.00",
            is_active=True,
        )
        second_service = Service.objects.create(
            category=self.category,
            name="Admin Therapist List Service Two",
            short_description="Short.",
            full_description="Long.",
            duration_minutes=60,
            price="75.00",
            is_active=True,
        )
        self.therapist.services.add(first_service, second_service)
        self.client.force_login(admin)

        response = self.client.get(reverse("aterapija:admin_therapist_list"))

        self.assertContains(response, "therapist@example.com")
        self.assertContains(response, "+37060000001")
        self.assertContains(response, "Therapist Services", count=1)
        self.assertContains(response, reverse("aterapija:admin_therapist_add"))

    def test_admin_can_add_new_therapist(self):
        admin = get_user_model().objects.create_user(username="admin_profile", is_staff=True)
        service = Service.objects.create(
            category=self.category,
            name="Therapist Creation Service",
            short_description="Short.",
            full_description="Long.",
            duration_minutes=60,
            price="70.00",
            is_active=True,
        )
        self.client.force_login(admin)

        response = self.client.post(
            reverse("aterapija:admin_therapist_add"),
            {
                "username": "new-therapist",
                "email": "new-therapist@example.com",
                "first_name": "New",
                "last_name": "Therapist",
                "full_name": "New Therapist",
                "phone": "+37060000002",
                "specializations": "Stress",
                "languages": "English",
                "experience": "5 years",
                "bio": "New therapist bio.",
                "services": [service.pk],
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("aterapija:admin_therapist_list"))
        therapist = Therapist.objects.get(full_name="New Therapist")
        self.assertEqual(therapist.user.email, "new-therapist@example.com")
        self.assertEqual(therapist.phone, "+37060000002")
        self.assertTrue(therapist.user.groups.filter(name=THERAPIST_GROUP).exists())
        self.assertTrue(therapist.services.filter(pk=service.pk).exists())

    def test_navbar_uses_therapist_profile_photo(self):
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        self.therapist_user.groups.add(therapist_group)
        self.therapist.profile_photo = "therapist_profiles/avatar.jpg"
        self.therapist.save()
        self.client.force_login(self.therapist_user)

        response = self.client.get(reverse("aterapija:therapist_profile"))

        self.assertContains(response, 'src="/media/therapist_profiles/avatar.jpg"')
        self.assertNotContains(response, "rounded-circle bg-secondary")

    def test_therapist_profile_does_not_ask_for_public_name_again(self):
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        self.therapist_user.groups.add(therapist_group)
        self.client.force_login(self.therapist_user)

        response = self.client.get(reverse("aterapija:therapist_profile"))

        self.assertNotContains(response, 'name="full_name"')
        self.assertContains(response, 'name="specializations"')

    def test_therapist_profile_derives_public_name_from_user_name(self):
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        self.therapist_user.groups.add(therapist_group)
        self.client.force_login(self.therapist_user)

        response = self.client.post(
            reverse("aterapija:therapist_profile"),
            {
                "username": self.therapist_user.username,
                "email": "therapist@example.com",
                "first_name": "Updated",
                "last_name": "Therapist",
                "phone": "+37060000000",
                "languages": "English",
                "experience": "8 years",
                "bio": "Short therapist bio.",
                "specializations": "Sleep, stress",
            },
        )

        self.assertRedirects(response, reverse("aterapija:therapist_dashboard"))
        self.therapist.refresh_from_db()
        self.assertEqual(self.therapist.full_name, "Updated Therapist")

    def test_therapist_can_create_service_linked_to_profile(self):
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        self.therapist_user.groups.add(therapist_group)
        self.client.force_login(self.therapist_user)

        response = self.client.post(
            reverse("aterapija:therapist_service_add"),
            {
                "category": self.category.pk,
                "name": "Mindfulness Session",
                "short_description": "Focused support.",
                "full_description": "A focused mindfulness service.",
                "duration_minutes": 45,
                "price": "55.00",
                "is_active": "on",
            },
        )

        service = Service.objects.get(name="Mindfulness Session")
        self.assertRedirects(response, reverse("aterapija:therapist_service_list"))
        self.assertTrue(self.therapist.services.filter(pk=service.pk).exists())

    def test_therapist_can_create_service_category(self):
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        self.therapist_user.groups.add(therapist_group)
        self.client.force_login(self.therapist_user)

        response = self.client.post(
            reverse("aterapija:therapist_service_category_add"),
            {
                "name": "Body-based Therapy",
                "description": "Somatic and body-based services.",
            },
        )

        self.assertRedirects(response, reverse("aterapija:therapist_service_add"))
        category = ServiceCategory.objects.get(name="Body-based Therapy")
        self.assertEqual(category.slug, "body-based-therapy")

        response = self.client.post(
            reverse("aterapija:therapist_service_add"),
            {
                "category": category.pk,
                "name": "Somatic Session",
                "short_description": "Body-based support.",
                "full_description": "A body-based therapy session.",
                "duration_minutes": 50,
                "price": "65.00",
                "is_active": "on",
            },
        )

        service = Service.objects.get(name="Somatic Session")
        self.assertRedirects(response, reverse("aterapija:therapist_service_list"))
        self.assertEqual(service.category, category)
        self.assertTrue(self.therapist.services.filter(pk=service.pk).exists())

    def test_therapist_can_link_existing_service_to_profile(self):
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        self.therapist_user.groups.add(therapist_group)
        service = Service.objects.create(
            category=self.category,
            name="Existing Support",
            short_description="Existing service.",
            full_description="Existing service details.",
            duration_minutes=60,
            price="70.00",
            is_active=True,
        )
        self.client.force_login(self.therapist_user)

        response = self.client.post(reverse("aterapija:therapist_service_link"), {"services": [service.pk]})

        self.assertRedirects(response, reverse("aterapija:therapist_service_list"))
        self.assertTrue(self.therapist.services.filter(pk=service.pk).exists())

    def test_therapist_can_update_linked_service(self):
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        self.therapist_user.groups.add(therapist_group)
        service = Service.objects.create(
            category=self.category,
            name="Original Service",
            short_description="Original.",
            full_description="Original details.",
            duration_minutes=60,
            price="70.00",
            is_active=True,
        )
        self.therapist.services.add(service)
        self.client.force_login(self.therapist_user)

        response = self.client.post(
            reverse("aterapija:therapist_service_edit", kwargs={"pk": service.pk}),
            {
                "category": self.category.pk,
                "name": "Updated Service",
                "short_description": "Updated.",
                "full_description": "Updated details.",
                "duration_minutes": 75,
                "price": "80.00",
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("aterapija:therapist_service_list"))
        service.refresh_from_db()
        self.assertEqual(service.name, "Updated Service")
        self.assertEqual(service.duration_minutes, 75)

    def test_deleting_shared_service_removes_it_from_therapist_profile_only(self):
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        self.therapist_user.groups.add(therapist_group)
        other_user = get_user_model().objects.create_user(username="other_service_therapist")
        other_therapist = Therapist.objects.create(user=other_user, full_name="Other Therapist")
        service = Service.objects.create(
            category=self.category,
            name="Shared Service",
            short_description="Shared.",
            full_description="Shared details.",
            duration_minutes=60,
            price="70.00",
            is_active=True,
        )
        service.therapists.add(self.therapist, other_therapist)
        self.client.force_login(self.therapist_user)

        response = self.client.post(reverse("aterapija:therapist_service_delete", kwargs={"pk": service.pk}))

        self.assertRedirects(response, reverse("aterapija:therapist_service_list"))
        self.assertTrue(Service.objects.filter(pk=service.pk).exists())
        self.assertFalse(self.therapist.services.filter(pk=service.pk).exists())
        self.assertTrue(other_therapist.services.filter(pk=service.pk).exists())

    def test_about_therapist_section_shows_service_buttons(self):
        service = Service.objects.create(
            category=self.category,
            name="Button Service",
            short_description="Shown as a button.",
            full_description="Shown as a button details.",
            duration_minutes=60,
            price="70.00",
            is_active=True,
        )
        self.therapist.services.add(service)

        response = self.client.get(reverse("aterapija:about"))

        self.assertContains(response, f'href="{reverse("aterapija:service_detail", kwargs={"slug": service.slug})}"')
        self.assertNotContains(response, 'data-bs-target="#bookingServices"')
        self.assertNotContains(response, reverse(
            "aterapija:booking_for_service_and_therapist",
            kwargs={"service_slug": service.slug, "therapist_pk": self.therapist.pk},
        ))

        service_response = self.client.get(reverse("aterapija:service_detail", kwargs={"slug": service.slug}))
        self.assertContains(service_response, f'href="{reverse("aterapija:about")}#therapists"')


class AdviceForTodayTests(TestCase):
    def test_articles_page_shows_previous_advice(self):
        today = timezone.localdate()
        old_advice = AdviceForToday.objects.create(
            title="Previous advice",
            body="A previous daily note.",
            published_date=today - timedelta(days=1),
            is_active=True,
        )
        AdviceForToday.objects.create(
            title="Today's advice",
            body="Current daily note.",
            published_date=today,
            is_active=True,
        )

        response = self.client.get(reverse("aterapija:articles"))

        self.assertContains(response, "Ankstesnės įžvalgos")
        self.assertContains(response, old_advice.title)

    def test_admin_advice_form_creates_today_advice_without_overwriting_old_advice(self):
        today = timezone.localdate()
        old_advice = AdviceForToday.objects.create(
            title="Old advice",
            body="Keep this archive item.",
            published_date=today - timedelta(days=1),
            is_active=True,
        )
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )
        self.client.force_login(admin)

        response = self.client.post(
            reverse("aterapija:admin_advice_add"),
            {
                "title": "Advice for today",
                "published_date": today.isoformat(),
                "body": "New advice body.",
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("aterapija:admin_advice_list"))
        old_advice.refresh_from_db()
        self.assertEqual(old_advice.title, "Old advice")
        self.assertTrue(
            AdviceForToday.objects.filter(
                title="Advice for today",
                body="New advice body.",
                published_date=today,
                is_active=True,
            ).exists()
        )

    def test_admin_can_schedule_future_advice(self):
        future_date = timezone.localdate() + timedelta(days=3)
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )
        self.client.force_login(admin)

        response = self.client.post(
            reverse("aterapija:admin_advice_add"),
            {
                "title": "Future advice",
                "published_date": future_date.isoformat(),
                "body": "This should publish later.",
                "is_active": "on",
            },
        )

        self.assertRedirects(response, reverse("aterapija:admin_advice_list"))
        self.assertTrue(
            AdviceForToday.objects.filter(
                title="Future advice",
                published_date=future_date,
                is_active=True,
            ).exists()
        )

    def test_future_advice_is_hidden_until_publish_date(self):
        future_advice = AdviceForToday.objects.create(
            title="Future advice",
            body="This should not be public yet.",
            published_date=timezone.localdate() + timedelta(days=1),
            is_active=True,
        )

        home_response = self.client.get(reverse("aterapija:home"))
        articles_response = self.client.get(reverse("aterapija:articles"))
        detail_response = self.client.get(future_advice.get_absolute_url())

        self.assertNotContains(home_response, future_advice.title)
        self.assertNotContains(articles_response, future_advice.title)
        self.assertEqual(detail_response.status_code, 404)


class ArticleManageTests(TestCase):
    def setUp(self):
        self.category = ArticleCategory.objects.create(
            name="Demo Articles",
            description="Demo article category.",
        )

    def test_admin_and_therapist_can_access_article_management(self):
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        therapist = get_user_model().objects.create_user(
            username="therapist",
            password="password123",
        )
        therapist.groups.add(therapist_group)

        self.client.force_login(admin)
        admin_response = self.client.get(reverse("aterapija:article_manage_list"))
        self.assertContains(admin_response, "Valdyti straipsnius")

        self.client.force_login(therapist)
        therapist_response = self.client.get(reverse("aterapija:article_manage_list"))
        self.assertContains(therapist_response, "Valdyti straipsnius")

    def test_article_management_sorts_latest_first(self):
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )
        older_article = Article.objects.create(
            category=self.category,
            title="Older Article",
            summary="Older summary.",
            body="Older body.",
            is_published=True,
        )
        newer_article = Article.objects.create(
            category=self.category,
            title="Newer Article",
            summary="Newer summary.",
            body="Newer body.",
            is_published=True,
        )
        Article.objects.filter(pk=older_article.pk).update(
            created_at=timezone.now() - timedelta(days=1)
        )
        older_article.refresh_from_db()
        self.client.force_login(admin)

        response = self.client.get(reverse("aterapija:article_manage_list"))

        articles = list(response.context["articles"])
        self.assertEqual(articles, [newer_article, older_article])

    def test_article_management_create_edit_delete(self):
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )
        self.client.force_login(admin)

        create_response = self.client.post(
            reverse("aterapija:article_manage_add"),
            {
                "category": self.category.pk,
                "title": "Managed Article",
                "summary": "Managed summary.",
                "body": "Managed body.",
                "is_published": "on",
            },
        )

        self.assertRedirects(create_response, reverse("aterapija:article_manage_list"))
        article = Article.objects.get(title="Managed Article")

        edit_response = self.client.post(
            reverse("aterapija:article_manage_edit", kwargs={"pk": article.pk}),
            {
                "category": self.category.pk,
                "title": "Managed Article Updated",
                "summary": "Updated summary.",
                "body": "Updated body.",
                "is_published": "on",
            },
        )

        self.assertRedirects(edit_response, reverse("aterapija:article_manage_list"))
        article.refresh_from_db()
        self.assertEqual(article.title, "Managed Article Updated")

        delete_response = self.client.post(
            reverse("aterapija:article_manage_delete", kwargs={"pk": article.pk})
        )

        self.assertRedirects(delete_response, reverse("aterapija:article_manage_list"))
        self.assertFalse(Article.objects.filter(pk=article.pk).exists())


class BilingualI18nTests(TestCase):
    def setUp(self):
        activate("lt")
        self.service_category = ServiceCategory.objects.create(
            name="Bilingual Services",
            description="Bilingual service category.",
        )
        self.service = Service.objects.create(
            category=self.service_category,
            name="Fallback Service",
            title_lt="Lietuviška paslauga",
            title_en="English Service",
            short_description="Fallback short.",
            short_description_lt="Trumpas lietuviškas paslaugos aprašymas.",
            short_description_en="English short service description.",
            full_description="Fallback full.",
            description_lt="Lietuviškas paslaugos aprašymas.",
            description_en="English service description.",
            duration_minutes=45,
            price="70.00",
            is_active=True,
        )
        self.article_category = ArticleCategory.objects.create(
            name="Bilingual Articles",
            description="Bilingual article category.",
        )

    def tearDown(self):
        activate("lt")

    def test_lithuanian_is_default_and_language_urls_render_expected_navigation(self):
        default_response = self.client.get("/")
        self.assertRedirects(default_response, "/lt/", fetch_redirect_response=False)

        lt_response = self.client.get("/lt/")
        self.assertContains(lt_response, "Pradžia")
        self.assertContains(lt_response, "Paslaugos")

        en_response = self.client.get("/en/")
        self.assertContains(en_response, "Home")
        self.assertContains(en_response, "Services")

    def test_language_switcher_redirects_to_selected_language_prefix(self):
        response = self.client.post(
            "/i18n/setlang/",
            {"language": "en", "next": "/lt/services/"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/en/services/")

    def test_services_display_lithuanian_and_english_content_by_url_language(self):
        lt_response = self.client.get("/lt/services/")
        self.assertContains(lt_response, "Lietuviška paslauga")
        self.assertContains(lt_response, "Trumpas lietuviškas paslaugos aprašymas.")
        self.assertNotContains(lt_response, "English Service")

        en_response = self.client.get("/en/services/")
        self.assertContains(en_response, "English Service")
        self.assertContains(en_response, "English short service description.")
        self.assertNotContains(en_response, "Lietuviška paslauga")

    def test_article_detail_uses_english_content_when_available(self):
        article = Article.objects.create(
            category=self.article_category,
            title="Fallback article",
            title_lt="Lietuviškas straipsnis",
            title_en="English Article",
            summary="Article summary.",
            body="Fallback body.",
            content_lt="Lietuviškas straipsnio turinys.",
            content_en="English article content.",
            is_published=True,
        )

        lt_response = self.client.get(f"/lt/articles/{article.slug}/")
        self.assertContains(lt_response, "Lietuviškas straipsnis")
        self.assertContains(lt_response, "Lietuviškas straipsnio turinys.")

        en_response = self.client.get(f"/en/articles/{article.slug}/")
        self.assertContains(en_response, "English Article")
        self.assertContains(en_response, "English article content.")
        self.assertNotContains(en_response, "This article is currently available only in Lithuanian.")

    def test_lithuanian_only_article_shows_notice_in_english_mode(self):
        article = Article.objects.create(
            category=self.article_category,
            title="Fallback Lithuanian-only article",
            title_lt="Tik lietuviškas straipsnis",
            summary="Article summary.",
            body="Fallback Lithuanian body.",
            content_lt="Tik lietuviškas turinys.",
            is_published=True,
        )

        response = self.client.get(f"/en/articles/{article.slug}/")

        self.assertContains(response, "Tik lietuviškas straipsnis")
        self.assertContains(response, "Tik lietuviškas turinys.")
        self.assertContains(response, "This article is currently available only in Lithuanian.")


class ProfileRoutingTests(TestCase):
    def setUp(self):
        activate("lt")

    def test_admin_profile_link_redirects_to_admin_profile_not_dashboard(self):
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("aterapija:profile"))

        self.assertRedirects(response, reverse("aterapija:admin_profile"))

    def test_admin_profile_page_updates_admin_user(self):
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )
        self.client.force_login(admin)

        response = self.client.post(
            reverse("aterapija:admin_profile"),
            {
                "username": "admin-updated",
                "email": "admin@example.com",
                "first_name": "Admin",
                "last_name": "User",
                "phone": "+37061111111",
            },
        )

        self.assertRedirects(response, reverse("aterapija:admin_dashboard"))
        admin.refresh_from_db()
        self.assertEqual(admin.username, "admin-updated")
        self.assertEqual(admin.email, "admin@example.com")
        self.assertEqual(admin.first_name, "Admin")
        self.assertEqual(admin.last_name, "User")
        self.assertEqual(admin.admin_profile.phone, "+37061111111")

    def test_admin_profile_page_saves_profile_photo(self):
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )
        self.client.force_login(admin)

        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse("aterapija:admin_profile"),
                {
                    "username": "admin",
                    "email": "",
                    "first_name": "",
                    "last_name": "",
                    "profile_picture": SimpleUploadedFile(
                        "avatar.jpg",
                        b"avatar image contents",
                        content_type="image/jpeg",
                    ),
                },
            )

        self.assertRedirects(response, reverse("aterapija:admin_dashboard"))
        admin.refresh_from_db()
        self.assertTrue(admin.admin_profile.profile_picture.name.startswith("admin_profiles/avatar"))

    def test_client_profile_page_redirects_to_client_dashboard_after_save(self):
        client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
        client = get_user_model().objects.create_user(
            username="client",
            password="password123",
        )
        client.groups.add(client_group)
        self.client.force_login(client)

        response = self.client.post(
            reverse("aterapija:client_profile"),
            {
                "username": "client-updated",
                "email": "client@example.com",
                "first_name": "Client",
                "last_name": "User",
                "phone": "123",
            },
        )

        self.assertRedirects(response, reverse("aterapija:client_dashboard"))
        client.refresh_from_db()
        self.assertEqual(client.username, "client-updated")
        self.assertEqual(client.client_profile.phone, "123")

    def test_therapist_profile_page_redirects_to_therapist_dashboard_after_save(self):
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        therapist_user = get_user_model().objects.create_user(
            username="therapist",
            password="password123",
        )
        therapist_user.groups.add(therapist_group)
        Therapist.objects.create(user=therapist_user, full_name="Therapist User")
        self.client.force_login(therapist_user)

        response = self.client.post(
            reverse("aterapija:therapist_profile"),
            {
                "username": "therapist-updated",
                "email": "therapist@example.com",
                "first_name": "Therapist",
                "last_name": "User",
                "full_name": "Therapist User",
                "phone": "+37062222222",
                "bio": "Bio",
                "specializations": "Stress",
            },
        )

        self.assertRedirects(response, reverse("aterapija:therapist_dashboard"))
        therapist_user.refresh_from_db()
        self.assertEqual(therapist_user.username, "therapist-updated")
        self.assertEqual(therapist_user.therapist_profile.phone, "+37062222222")

    def test_therapist_can_take_help_me_choose_questionnaire(self):
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        therapist_user = get_user_model().objects.create_user(
            username="therapist-questionnaire",
            password="password123",
        )
        therapist_user.groups.add(therapist_group)
        Therapist.objects.create(user=therapist_user, full_name="Therapist User")
        category = ServiceCategory.objects.create(
            name="Questionnaire Category",
            description="Demo category.",
        )
        service = Service.objects.create(
            category=category,
            name="Questionnaire Service",
            short_description="Short demo service.",
            full_description="Long demo service.",
            duration_minutes=60,
            price="50.00",
            is_active=True,
        )
        question = WellbeingQuestion.objects.create(
            question_text="What do you need help with?",
            order=1,
            is_active=True,
        )
        answer = WellbeingAnswerOption.objects.create(
            question=question,
            answer_text="Stress",
            order=1,
        )
        answer.related_services.add(service)
        self.client.force_login(therapist_user)

        response = self.client.get(reverse("aterapija:assessment"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "What do you need help with?")

        response = self.client.post(reverse("aterapija:assessment"), {"answers": [answer.pk]})

        self.assertRedirects(response, reverse("aterapija:assessment_results"))
        assessment = WellbeingAssessment.objects.get(user=therapist_user)
        self.assertTrue(assessment.answer_options.filter(pk=answer.pk).exists())

        response = self.client.get(reverse("aterapija:assessment_results"))

        self.assertContains(response, "Questionnaire Service")

    def test_admin_profile_shows_client_questionnaire_results(self):
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )
        client = get_user_model().objects.create_user(
            username="client",
            email="client@example.com",
        )
        ClientProfile.objects.create(user=client, full_name="Client User", phone="+37060000000")
        category = ServiceCategory.objects.create(
            name="Demo Category",
            description="Demo category.",
        )
        service = Service.objects.create(
            category=category,
            name="Stress Support",
            short_description="Short demo service.",
            full_description="Long demo service.",
            duration_minutes=60,
            price="50.00",
            is_active=True,
        )
        question = WellbeingQuestion.objects.create(
            question_text="What feels difficult?",
            order=1,
            is_active=True,
        )
        answer = WellbeingAnswerOption.objects.create(
            question=question,
            answer_text="I feel overwhelmed",
            order=1,
        )
        answer.related_services.add(service)
        assessment = WellbeingAssessment.objects.create(user=client)
        assessment.answer_options.add(answer)
        self.client.force_login(admin)

        profile_response = self.client.get(reverse("aterapija:admin_profile"))

        self.assertNotContains(profile_response, "Klausimyno rezultatai")
        self.assertNotContains(profile_response, "Client User")

        list_response = self.client.get(reverse("aterapija:admin_assessment_list"))

        self.assertContains(list_response, "Klausimyno rezultatai")
        self.assertContains(list_response, "Client User")
        self.assertContains(list_response, "+37060000000")
        self.assertContains(list_response, reverse("aterapija:admin_assessment_detail", kwargs={"pk": assessment.pk}))
        self.assertNotContains(list_response, "What feels difficult?")

        detail_response = self.client.get(
            reverse("aterapija:admin_assessment_detail", kwargs={"pk": assessment.pk})
        )

        self.assertContains(detail_response, "What feels difficult?")
        self.assertContains(detail_response, "I feel overwhelmed")
        self.assertContains(detail_response, "Stress Support")
        self.assertContains(detail_response, "Peržiūrėti detales")
        self.assertContains(detail_response, "+37060000000")

    def test_admin_nav_points_help_and_contact_to_dedicated_admin_pages(self):
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("aterapija:admin_profile"))

        self.assertContains(response, f'href="{reverse("aterapija:admin_assessment_list")}"')
        self.assertContains(response, f'href="{reverse("aterapija:admin_contact_message_list")}"')
        self.assertNotContains(response, "#help-me-choose-results")
        self.assertNotContains(response, "#client-messages")

    def test_contact_form_saves_message_and_admin_message_list_shows_it(self):
        admin = get_user_model().objects.create_user(
            username="admin",
            password="password123",
            is_staff=True,
        )

        response = self.client.post(
            reverse("aterapija:contact"),
            {
                "name": "Client Sender",
                "email": "sender@example.com",
                "subject": "Need support",
                "message": "Please contact me.",
            },
        )

        self.assertRedirects(response, reverse("aterapija:contact"))
        self.assertTrue(ContactMessage.objects.filter(subject="Need support").exists())

        self.client.force_login(admin)
        contact_message = ContactMessage.objects.get(subject="Need support")
        profile_response = self.client.get(reverse("aterapija:admin_profile"))

        self.assertNotContains(profile_response, "Klientų žinutės")

        list_response = self.client.get(reverse("aterapija:admin_contact_message_list"))

        self.assertContains(list_response, "Klientų žinutės")
        self.assertContains(
            list_response,
            reverse("aterapija:admin_contact_message_detail", kwargs={"pk": contact_message.pk}),
        )
        self.assertNotContains(list_response, "Please contact me.")

        detail_response = self.client.get(
            reverse("aterapija:admin_contact_message_detail", kwargs={"pk": contact_message.pk})
        )

        self.assertContains(detail_response, "Client Sender")
        self.assertContains(detail_response, "Need support")
        self.assertContains(detail_response, "Please contact me.")

    def test_admin_can_create_question_with_choice_options(self):
        admin = get_user_model().objects.create_user(username="admin", password="password123", is_staff=True)
        category = ServiceCategory.objects.create(name="Question Services", description="Demo")
        service = Service.objects.create(
            category=category,
            name="Question Linked Service",
            short_description="Short",
            full_description="Long",
            duration_minutes=60,
            price="50.00",
            is_active=True,
        )
        self.client.force_login(admin)

        response = self.client.post(
            reverse("aterapija:admin_question_add"),
            {
                "question_text": "Choose one option",
                "question_type": "single",
                "order": 2,
                "is_active": "on",
                "answer_options-TOTAL_FORMS": "1",
                "answer_options-INITIAL_FORMS": "0",
                "answer_options-MIN_NUM_FORMS": "0",
                "answer_options-MAX_NUM_FORMS": "1000",
                "answer_options-0-answer_text": "I need support",
                "answer_options-0-related_services": [service.pk],
                "answer_options-0-order": "1",
            },
        )

        self.assertRedirects(response, reverse("aterapija:admin_question_list"))
        question = WellbeingQuestion.objects.get(question_text="Choose one option")
        self.assertEqual(question.question_type, WellbeingQuestion.TYPE_SINGLE)
        self.assertTrue(question.answer_options.filter(answer_text="I need support", related_services=service).exists())

    def test_text_question_answers_are_saved_from_questionnaire(self):
        client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
        user = get_user_model().objects.create_user(username="client-text", password="password123")
        user.groups.add(client_group)
        question = WellbeingQuestion.objects.create(
            question_text="Tell us more",
            question_type=WellbeingQuestion.TYPE_TEXTAREA,
            order=1,
            is_active=True,
        )
        self.client.force_login(user)

        response = self.client.post(reverse("aterapija:assessment"), {f"question_{question.pk}": "Written answer"})

        self.assertRedirects(response, reverse("aterapija:assessment_results"))
        self.assertTrue(WellbeingTextAnswer.objects.filter(question=question, answer_text="Written answer").exists())

    def test_guest_can_view_questionnaire(self):
        question = WellbeingQuestion.objects.create(
            question_text="What support do you need?",
            order=1,
            is_active=True,
        )

        response = self.client.get(reverse("aterapija:assessment"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, question.question_text)

    def test_guest_questionnaire_answers_are_saved_after_login(self):
        client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
        existing_client = get_user_model().objects.create_user(username="existing-client")
        existing_client.groups.add(client_group)
        user = get_user_model().objects.create_user(username="client-pending", password="password123")
        user.groups.add(client_group)
        question = WellbeingQuestion.objects.create(
            question_text="Choose a need",
            order=1,
            is_active=True,
        )
        answer = WellbeingAnswerOption.objects.create(question=question, answer_text="Stress", order=1)
        text_question = WellbeingQuestion.objects.create(
            question_text="Tell us more",
            question_type=WellbeingQuestion.TYPE_TEXTAREA,
            order=2,
            is_active=True,
        )

        response = self.client.post(
            reverse("aterapija:assessment"),
            {"answers": [answer.pk], f"question_{text_question.pk}": "Saved after login"},
        )

        self.assertRedirects(
            response,
            f"{reverse('aterapija:login')}?next={reverse('aterapija:assessment_results')}",
        )
        self.assertEqual(WellbeingAssessment.objects.count(), 0)
        self.assertIn("pending_assessment_data", self.client.session)

        response = self.client.post(
            reverse("aterapija:login"),
            {"username": "client-pending", "password": "password123"},
        )

        self.assertRedirects(response, reverse("aterapija:assessment_results"))
        assessment = WellbeingAssessment.objects.get(user=user)
        self.assertTrue(assessment.answer_options.filter(pk=answer.pk).exists())
        self.assertFalse(WellbeingAssessment.objects.filter(user=existing_client).exists())
        self.assertTrue(
            WellbeingTextAnswer.objects.filter(
                assessment=assessment,
                question=text_question,
                answer_text="Saved after login",
            ).exists()
        )
        self.assertNotIn("pending_assessment_data", self.client.session)
        self.assertNotIn("pending_assessment_token", self.client.session)

    def test_guest_questionnaire_answers_are_saved_after_registration(self):
        question = WellbeingQuestion.objects.create(
            question_text="Choose one",
            order=1,
            is_active=True,
        )
        answer = WellbeingAnswerOption.objects.create(question=question, answer_text="Support", order=1)

        response = self.client.post(reverse("aterapija:assessment"), {"answers": [answer.pk]})

        self.assertRedirects(
            response,
            f"{reverse('aterapija:login')}?next={reverse('aterapija:assessment_results')}",
        )

        response = self.client.post(
            reverse("aterapija:register"),
            {
                "username": "new-client-pending",
                "email": "new-client@example.com",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )

        self.assertRedirects(response, reverse("aterapija:assessment_results"))
        user = get_user_model().objects.get(username="new-client-pending")
        assessment = WellbeingAssessment.objects.get(user=user)
        self.assertTrue(assessment.answer_options.filter(pk=answer.pk).exists())
        self.assertNotIn("pending_assessment_data", self.client.session)
        self.assertNotIn("pending_assessment_token", self.client.session)

    def test_stale_assessment_session_keys_are_not_reused_after_login(self):
        client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
        old_user = get_user_model().objects.create_user(username="old-assessment-user")
        old_user.groups.add(client_group)
        new_user = get_user_model().objects.create_user(username="new-assessment-user", password="password123")
        new_user.groups.add(client_group)
        question = WellbeingQuestion.objects.create(question_text="Choose one", order=1, is_active=True)
        answer = WellbeingAnswerOption.objects.create(question=question, answer_text="Old answer", order=1)
        old_assessment = WellbeingAssessment.objects.create(user=old_user)
        old_assessment.answer_options.add(answer)
        session = self.client.session
        session["assessment_answer_option_ids"] = [answer.pk]
        session["latest_assessment_id"] = old_assessment.pk
        session.save()

        response = self.client.post(
            reverse("aterapija:login"),
            {"username": "new-assessment-user", "password": "password123"},
        )

        self.assertRedirects(response, reverse("aterapija:client_dashboard"))
        self.assertNotIn("assessment_answer_option_ids", self.client.session)
        self.assertNotIn("latest_assessment_id", self.client.session)
        self.assertFalse(WellbeingAssessment.objects.filter(user=new_user).exists())

    def test_invalid_pending_questionnaire_is_discarded_after_login(self):
        client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
        user = get_user_model().objects.create_user(username="invalid-pending-client", password="password123")
        user.groups.add(client_group)
        session = self.client.session
        session["pending_assessment_token"] = "current-token"
        session["pending_assessment_data"] = {
            "token": "stale-token",
            "answers": {"selected_option_ids": [], "text_answers": {}},
        }
        session.save()

        response = self.client.post(
            reverse("aterapija:login"),
            {"username": "invalid-pending-client", "password": "password123", "next": reverse("aterapija:assessment_results")},
        )

        self.assertRedirects(response, reverse("aterapija:assessment"))
        self.assertFalse(WellbeingAssessment.objects.filter(user=user).exists())
        self.assertNotIn("pending_assessment_data", self.client.session)
        self.assertNotIn("pending_assessment_token", self.client.session)

    def test_pending_questionnaire_data_is_isolated_by_browser_session(self):
        client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
        first_user = get_user_model().objects.create_user(username="first-session-client", password="password123")
        first_user.groups.add(client_group)
        second_user = get_user_model().objects.create_user(username="second-session-client", password="password123")
        second_user.groups.add(client_group)
        question = WellbeingQuestion.objects.create(question_text="Choose one", order=1, is_active=True)
        first_answer = WellbeingAnswerOption.objects.create(question=question, answer_text="First answer", order=1)
        second_answer = WellbeingAnswerOption.objects.create(question=question, answer_text="Second answer", order=2)
        first_browser = DjangoTestClient()
        second_browser = DjangoTestClient()

        first_browser.post(reverse("aterapija:assessment"), {"answers": [first_answer.pk]})
        second_browser.post(reverse("aterapija:assessment"), {"answers": [second_answer.pk]})

        first_response = first_browser.post(
            reverse("aterapija:login"),
            {"username": "first-session-client", "password": "password123"},
        )
        second_response = second_browser.post(
            reverse("aterapija:login"),
            {"username": "second-session-client", "password": "password123"},
        )

        self.assertRedirects(first_response, reverse("aterapija:assessment_results"))
        self.assertRedirects(second_response, reverse("aterapija:assessment_results"))
        first_assessment = WellbeingAssessment.objects.get(user=first_user)
        second_assessment = WellbeingAssessment.objects.get(user=second_user)
        self.assertTrue(first_assessment.answer_options.filter(pk=first_answer.pk).exists())
        self.assertFalse(first_assessment.answer_options.filter(pk=second_answer.pk).exists())
        self.assertTrue(second_assessment.answer_options.filter(pk=second_answer.pk).exists())
        self.assertFalse(second_assessment.answer_options.filter(pk=first_answer.pk).exists())

    def test_admin_can_edit_about_page_content(self):
        admin = get_user_model().objects.create_user(username="admin", password="password123", is_staff=True)
        self.client.force_login(admin)

        response = self.client.post(
            reverse("aterapija:admin_about_edit"),
            {
                "title": "About A Terapija",
                "main_text": "Edited about page text.",
            },
        )

        self.assertRedirects(response, reverse("aterapija:admin_dashboard"))
        self.assertEqual(AboutPage.objects.get(pk=1).main_text, "Edited about page text.")
        public_response = self.client.get(reverse("aterapija:about"))
        self.assertContains(public_response, "Edited about page text.")

    def test_admin_can_create_service_and_link_therapist(self):
        admin = get_user_model().objects.create_user(username="admin", password="password123", is_staff=True)
        therapist_user = get_user_model().objects.create_user(username="service-therapist")
        therapist = Therapist.objects.create(user=therapist_user, full_name="Service Therapist")
        category = ServiceCategory.objects.create(name="Admin Services", description="Demo")
        self.client.force_login(admin)

        response = self.client.post(
            reverse("aterapija:admin_service_add"),
            {
                "category": category.pk,
                "name": "Admin Created Service",
                "short_description": "Short",
                "full_description": "Long",
                "duration_minutes": 60,
                "price": "80.00",
                "is_active": "on",
                "therapists": [therapist.pk],
            },
        )

        self.assertRedirects(response, reverse("aterapija:admin_service_list"))
        service = Service.objects.get(name="Admin Created Service")
        self.assertTrue(service.therapists.filter(pk=therapist.pk).exists())

    def test_admin_article_image_upload_and_remove(self):
        admin = get_user_model().objects.create_user(username="admin", password="password123", is_staff=True)
        category = ArticleCategory.objects.create(name="Image Articles", description="Demo")
        self.client.force_login(admin)

        with TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            create_response = self.client.post(
                reverse("aterapija:article_manage_add"),
                {
                    "category": category.pk,
                    "title": "Image Article",
                    "summary": "Summary",
                    "body": "Body",
                    "is_published": "on",
                    "image": SimpleUploadedFile("article.jpg", b"image content", content_type="image/jpeg"),
                },
            )
            article = Article.objects.get(title="Image Article")
            remove_response = self.client.post(
                reverse("aterapija:article_manage_edit", kwargs={"pk": article.pk}),
                {
                    "category": category.pk,
                    "title": "Image Article",
                    "summary": "Summary",
                    "body": "Body",
                    "is_published": "on",
                    "remove_image": "on",
                },
            )

        self.assertRedirects(create_response, reverse("aterapija:article_manage_list"))
        article.refresh_from_db()
        self.assertRedirects(remove_response, reverse("aterapija:article_manage_list"))
        self.assertEqual(article.image.name, "")

    def test_admin_dashboard_shows_payment_received_earnings(self):
        admin = get_user_model().objects.create_user(username="admin", password="password123", is_staff=True)
        therapist_user = get_user_model().objects.create_user(username="paid-therapist")
        therapist = Therapist.objects.create(user=therapist_user, full_name="Paid Therapist")
        category = ServiceCategory.objects.create(name="Paid Services", description="Demo")
        service = Service.objects.create(
            category=category,
            name="Paid Service",
            short_description="Short",
            full_description="Long",
            duration_minutes=60,
            price="90.00",
            is_active=True,
        )
        service.therapists.add(therapist)
        BookingRequest.objects.create(
            client_name="Paid Client",
            client_email="paid@example.com",
            service=service,
            therapist=therapist,
            preferred_date=timezone.localdate() + timedelta(days=1),
            preferred_time=time(10, 0),
            payment_received=True,
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("aterapija:admin_dashboard"))

        self.assertContains(response, "Paid Therapist")
        self.assertContains(response, "90,00")
        self.assertContains(response, 'name="payment_received"')
        self.assertContains(response, "checked")

    def test_admin_can_toggle_booking_payment_received_from_table(self):
        admin = get_user_model().objects.create_user(username="admin", password="password123", is_staff=True)
        therapist_user = get_user_model().objects.create_user(username="toggle-therapist")
        therapist = Therapist.objects.create(user=therapist_user, full_name="Toggle Therapist")
        category = ServiceCategory.objects.create(name="Toggle Services", description="Demo")
        service = Service.objects.create(
            category=category,
            name="Toggle Service",
            short_description="Short",
            full_description="Long",
            duration_minutes=60,
            price="90.00",
            is_active=True,
        )
        service.therapists.add(therapist)
        booking = BookingRequest.objects.create(
            client_name="Toggle Client",
            client_email="toggle@example.com",
            service=service,
            therapist=therapist,
            preferred_date=timezone.localdate() + timedelta(days=1),
            preferred_time=time(10, 0),
        )
        self.client.force_login(admin)

        response = self.client.post(
            reverse("aterapija:admin_booking_payment_toggle", kwargs={"pk": booking.pk}),
            {"payment_received": "on", "next": reverse("aterapija:admin_booking_request_list")},
        )

        self.assertRedirects(response, reverse("aterapija:admin_booking_request_list"))
        booking.refresh_from_db()
        self.assertTrue(booking.payment_received)

        self.client.post(reverse("aterapija:admin_booking_payment_toggle", kwargs={"pk": booking.pk}), {})
        booking.refresh_from_db()
        self.assertFalse(booking.payment_received)

    def test_therapist_can_toggle_payment_for_own_booking(self):
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        therapist_user = get_user_model().objects.create_user(username="payment-therapist", password="password123")
        therapist_user.groups.add(therapist_group)
        therapist = Therapist.objects.create(user=therapist_user, full_name="Payment Therapist")
        category = ServiceCategory.objects.create(name="Therapist Payment Services", description="Demo")
        service = Service.objects.create(
            category=category,
            name="Therapist Payment Service",
            short_description="Short",
            full_description="Long",
            duration_minutes=60,
            price="90.00",
            is_active=True,
        )
        service.therapists.add(therapist)
        booking = BookingRequest.objects.create(
            client_name="Therapist Payment Client",
            client_email="therapist-payment@example.com",
            service=service,
            therapist=therapist,
            preferred_date=timezone.localdate() + timedelta(days=1),
            preferred_time=time(10, 0),
        )
        self.client.force_login(therapist_user)

        dashboard_response = self.client.get(reverse("aterapija:therapist_dashboard"))

        self.assertContains(dashboard_response, "Mokėjimas")
        self.assertContains(dashboard_response, 'name="payment_received"')
        self.assertContains(
            dashboard_response,
            reverse("aterapija:therapist_booking_payment_toggle", kwargs={"pk": booking.pk}),
        )

        response = self.client.post(
            reverse("aterapija:therapist_booking_payment_toggle", kwargs={"pk": booking.pk}),
            {"payment_received": "on", "next": reverse("aterapija:therapist_dashboard")},
        )

        self.assertRedirects(response, reverse("aterapija:therapist_dashboard"))
        booking.refresh_from_db()
        self.assertTrue(booking.payment_received)

        updated_dashboard_response = self.client.get(reverse("aterapija:therapist_dashboard"))
        self.assertContains(updated_dashboard_response, "Gautos pajamos")
        self.assertContains(updated_dashboard_response, "€90,00")
        self.assertContains(updated_dashboard_response, "Šiandien")
        self.assertContains(updated_dashboard_response, "Šį mėnesį")
        self.assertContains(updated_dashboard_response, "Per visą laikotarpį")

    def test_therapist_payment_summary_only_counts_own_paid_approved_bookings(self):
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        therapist_user = get_user_model().objects.create_user(username="summary-therapist", password="password123")
        other_user = get_user_model().objects.create_user(username="summary-other-therapist")
        therapist_user.groups.add(therapist_group)
        other_user.groups.add(therapist_group)
        therapist = Therapist.objects.create(user=therapist_user, full_name="Summary Therapist")
        other_therapist = Therapist.objects.create(user=other_user, full_name="Summary Other Therapist")
        category = ServiceCategory.objects.create(name="Summary Services", description="Demo")
        service = Service.objects.create(
            category=category,
            name="Summary Service",
            short_description="Short",
            full_description="Long",
            duration_minutes=60,
            price="90.00",
            is_active=True,
        )
        other_service = Service.objects.create(
            category=category,
            name="Summary Other Service",
            short_description="Short",
            full_description="Long",
            duration_minutes=60,
            price="120.00",
            is_active=True,
        )
        service.therapists.add(therapist)
        other_service.therapists.add(other_therapist)
        today = timezone.localdate()
        month_start = today.replace(day=1)
        same_month_date = today + timedelta(days=1)
        if same_month_date.month != today.month:
            same_month_date = month_start
        previous_month_date = month_start - timedelta(days=1)

        BookingRequest.objects.create(
            client_name="Paid One",
            client_email="paid-one@example.com",
            service=service,
            therapist=therapist,
            preferred_date=today,
            preferred_time=time(10, 0),
            payment_received=True,
        )
        BookingRequest.objects.create(
            client_name="Paid Two",
            client_email="paid-two@example.com",
            service=service,
            therapist=therapist,
            preferred_date=same_month_date,
            preferred_time=time(10, 0),
            payment_received=True,
        )
        BookingRequest.objects.create(
            client_name="Paid Older",
            client_email="paid-older@example.com",
            service=service,
            therapist=therapist,
            preferred_date=previous_month_date,
            preferred_time=time(10, 0),
            payment_received=True,
        )
        BookingRequest.objects.create(
            client_name="Unpaid",
            client_email="unpaid@example.com",
            service=service,
            therapist=therapist,
            preferred_date=today,
            preferred_time=time(10, 0),
            payment_received=False,
        )
        BookingRequest.objects.create(
            client_name="Cancelled Paid",
            client_email="cancelled-paid@example.com",
            service=service,
            therapist=therapist,
            preferred_date=today,
            preferred_time=time(10, 0),
            payment_received=True,
            status=BookingRequest.STATUS_CANCELLED,
        )
        BookingRequest.objects.create(
            client_name="Other Paid",
            client_email="other-paid@example.com",
            service=other_service,
            therapist=other_therapist,
            preferred_date=today,
            preferred_time=time(10, 0),
            payment_received=True,
        )
        self.client.force_login(therapist_user)

        response = self.client.get(reverse("aterapija:therapist_dashboard"))

        stats = response.context["payment_stats"]
        self.assertEqual(stats["today"]["paid_booking_count"], 1)
        self.assertEqual(stats["today"]["total_received"], Decimal("90.00"))
        self.assertEqual(stats["month"]["paid_booking_count"], 2)
        self.assertEqual(stats["month"]["total_received"], Decimal("180.00"))
        self.assertEqual(stats["all_time"]["paid_booking_count"], 3)
        self.assertEqual(stats["all_time"]["total_received"], Decimal("270.00"))
        self.assertContains(response, "Gautos pajamos")
        self.assertContains(response, "€90,00")
        self.assertContains(response, "€180,00")
        self.assertContains(response, "€270,00")
        self.assertContains(response, "Šiandien")
        self.assertContains(response, "Šį mėnesį")
        self.assertContains(response, "Per visą laikotarpį")

    def test_therapist_cannot_toggle_payment_for_another_therapists_booking(self):
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        therapist_user = get_user_model().objects.create_user(username="own-payment-therapist", password="password123")
        other_user = get_user_model().objects.create_user(username="other-payment-therapist", password="password123")
        therapist_user.groups.add(therapist_group)
        other_user.groups.add(therapist_group)
        Therapist.objects.create(user=therapist_user, full_name="Own Payment Therapist")
        other_therapist = Therapist.objects.create(user=other_user, full_name="Other Payment Therapist")
        category = ServiceCategory.objects.create(name="Other Payment Services", description="Demo")
        service = Service.objects.create(
            category=category,
            name="Other Payment Service",
            short_description="Short",
            full_description="Long",
            duration_minutes=60,
            price="90.00",
            is_active=True,
        )
        service.therapists.add(other_therapist)
        booking = BookingRequest.objects.create(
            client_name="Other Payment Client",
            client_email="other-payment@example.com",
            service=service,
            therapist=other_therapist,
            preferred_date=timezone.localdate() + timedelta(days=1),
            preferred_time=time(10, 0),
        )
        self.client.force_login(therapist_user)

        response = self.client.post(
            reverse("aterapija:therapist_booking_payment_toggle", kwargs={"pk": booking.pk}),
            {"payment_received": "on", "next": reverse("aterapija:therapist_dashboard")},
        )

        self.assertEqual(response.status_code, 404)
        booking.refresh_from_db()
        self.assertFalse(booking.payment_received)

    def test_client_cannot_toggle_booking_payment(self):
        client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
        client = get_user_model().objects.create_user(username="payment-client", password="password123")
        client.groups.add(client_group)
        therapist_user = get_user_model().objects.create_user(username="client-payment-therapist")
        therapist = Therapist.objects.create(user=therapist_user, full_name="Client Payment Therapist")
        category = ServiceCategory.objects.create(name="Client Payment Services", description="Demo")
        service = Service.objects.create(
            category=category,
            name="Client Payment Service",
            short_description="Short",
            full_description="Long",
            duration_minutes=60,
            price="90.00",
            is_active=True,
        )
        service.therapists.add(therapist)
        booking = BookingRequest.objects.create(
            client_name="Client Payment Client",
            client_email="client-payment@example.com",
            client=client,
            service=service,
            therapist=therapist,
            preferred_date=timezone.localdate() + timedelta(days=1),
            preferred_time=time(10, 0),
        )
        self.client.force_login(client)

        dashboard_response = self.client.get(reverse("aterapija:client_dashboard"))
        self.assertNotContains(dashboard_response, 'name="payment_received"')

        response = self.client.post(
            reverse("aterapija:therapist_booking_payment_toggle", kwargs={"pk": booking.pk}),
            {"payment_received": "on"},
        )

        self.assertRedirects(response, reverse("aterapija:client_dashboard"))
        booking.refresh_from_db()
        self.assertFalse(booking.payment_received)

    def test_cancelled_bookings_are_hidden_from_admin_booking_tables(self):
        admin = get_user_model().objects.create_user(username="admin", password="password123", is_staff=True)
        therapist_user = get_user_model().objects.create_user(username="cancelled-therapist")
        therapist = Therapist.objects.create(user=therapist_user, full_name="Cancelled Therapist")
        category = ServiceCategory.objects.create(name="Cancelled Services", description="Demo")
        service = Service.objects.create(
            category=category,
            name="Cancelled Service",
            short_description="Short",
            full_description="Long",
            duration_minutes=60,
            price="90.00",
            is_active=True,
        )
        service.therapists.add(therapist)
        BookingRequest.objects.create(
            client_name="Visible Client",
            client_email="visible@example.com",
            service=service,
            therapist=therapist,
            preferred_date=timezone.localdate() + timedelta(days=1),
            preferred_time=time(10, 0),
            status=BookingRequest.STATUS_APPROVED,
        )
        BookingRequest.objects.create(
            client_name="Cancelled Client",
            client_email="cancelled@example.com",
            service=service,
            therapist=therapist,
            preferred_date=timezone.localdate() + timedelta(days=2),
            preferred_time=time(10, 0),
            status=BookingRequest.STATUS_CANCELLED,
        )
        self.client.force_login(admin)

        dashboard_response = self.client.get(reverse("aterapija:admin_dashboard"))
        list_response = self.client.get(reverse("aterapija:admin_booking_request_list"))

        self.assertContains(dashboard_response, "Visible Client")
        self.assertNotContains(dashboard_response, "Cancelled Client")
        self.assertContains(list_response, "Visible Client")
        self.assertNotContains(list_response, "Cancelled Client")

    def test_booking_creation_creates_notifications_for_admin_and_therapist_only(self):
        admin = get_user_model().objects.create_user(username="admin", password="password123", is_staff=True)
        client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
        client = get_user_model().objects.create_user(
            username="notify-client",
            email="notify-client@example.com",
            password="password123",
        )
        client.groups.add(client_group)
        therapist_user = get_user_model().objects.create_user(username="notify-therapist")
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        therapist_user.groups.add(therapist_group)
        therapist = Therapist.objects.create(user=therapist_user, full_name="Notify Therapist")
        category = ServiceCategory.objects.create(name="Notify Services", description="Demo")
        service = Service.objects.create(
            category=category,
            name="Notify Service",
            short_description="Short",
            full_description="Long",
            duration_minutes=60,
            price="90.00",
            is_active=True,
        )
        service.therapists.add(therapist)
        self.client.force_login(client)

        response = self.client.post(
            reverse("aterapija:booking_create"),
            {
                "service": service.pk,
                "therapist": therapist.pk,
                "preferred_date": timezone.localdate() + timedelta(days=1),
                "preferred_time": "10:00",
                "message": "",
            },
        )

        self.assertRedirects(response, reverse("aterapija:booking_thanks"))
        self.assertTrue(Notification.objects.filter(recipient=admin, notification_type=Notification.TYPE_BOOKING_CREATED).exists())
        self.assertTrue(Notification.objects.filter(recipient=therapist_user, notification_type=Notification.TYPE_BOOKING_CREATED).exists())
        self.assertFalse(Notification.objects.filter(recipient=client, notification_type=Notification.TYPE_BOOKING_CREATED).exists())

        dashboard_response = self.client.get(reverse("aterapija:client_dashboard"))
        self.assertNotContains(dashboard_response, "Pranešimai")

        self.client.force_login(therapist_user)
        therapist_response = self.client.get(reverse("aterapija:therapist_dashboard"))
        self.assertContains(therapist_response, "Pranešimai")

    def test_notification_can_be_marked_read_and_all_read(self):
        user = get_user_model().objects.create_user(username="notification-user", password="password123")
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        user.groups.add(therapist_group)
        first = Notification.objects.create(
            recipient=user,
            notification_type=Notification.TYPE_MESSAGE,
            title="First",
        )
        Notification.objects.create(
            recipient=user,
            notification_type=Notification.TYPE_MESSAGE,
            title="Second",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("aterapija:notifications"))
        self.assertContains(response, "First")
        self.assertContains(response, "Pažymėti visus kaip perskaitytus")

        response = self.client.post(reverse("aterapija:notification_mark_read", kwargs={"pk": first.pk}))
        first.refresh_from_db()
        self.assertTrue(first.is_read)
        self.assertRedirects(response, reverse("aterapija:notifications"))

        response = self.client.post(reverse("aterapija:notifications_mark_all_read"))
        self.assertRedirects(response, reverse("aterapija:notifications"))
        self.assertFalse(Notification.objects.filter(recipient=user, is_read=False).exists())

    def test_therapist_notifications_are_paginated_five_per_page(self):
        user = get_user_model().objects.create_user(username="therapist-notifications", password="password123")
        therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
        user.groups.add(therapist_group)
        for index in range(6):
            Notification.objects.create(
                recipient=user,
                notification_type=Notification.TYPE_MESSAGE,
                title=f"Therapist notification {index}",
            )
        self.client.force_login(user)

        response = self.client.get(reverse("aterapija:notifications"))

        self.assertEqual(len(response.context["notifications"]), 5)
        self.assertContains(response, "Therapist notification 5")
        self.assertNotContains(response, "Therapist notification 0")
        self.assertContains(response, "Puslapis 1 iš 2")
        self.assertContains(response, "Toliau")
        self.assertContains(response, "Ankstesni")

        response = self.client.get(reverse("aterapija:notifications"), {"page": 2})

        self.assertEqual(len(response.context["notifications"]), 1)
        self.assertContains(response, "Therapist notification 0")
        self.assertContains(response, "Puslapis 2 iš 2")

    def test_admin_notifications_are_paginated_and_controls_hide_for_single_page(self):
        admin = get_user_model().objects.create_user(username="admin-notifications", password="password123", is_staff=True)
        for index in range(5):
            Notification.objects.create(
                recipient=admin,
                notification_type=Notification.TYPE_MESSAGE,
                title=f"Admin notification {index}",
            )
        self.client.force_login(admin)

        response = self.client.get(reverse("aterapija:notifications"))

        self.assertEqual(len(response.context["notifications"]), 5)
        self.assertContains(response, "Admin notification 4")
        self.assertContains(response, "Admin notification 0")
        self.assertNotContains(response, "Page 1 /")
        self.assertNotContains(response, 'aria-label="Notification pagination"')

    def test_client_cannot_access_notifications(self):
        client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
        client = get_user_model().objects.create_user(username="no-notification-client", password="password123")
        client.groups.add(client_group)
        self.client.force_login(client)

        response = self.client.get(reverse("aterapija:notifications"))

        self.assertRedirects(response, reverse("aterapija:client_dashboard"))

    def test_contact_form_creates_message_notifications(self):
        admin = get_user_model().objects.create_user(username="admin", password="password123", is_staff=True)
        client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
        client = get_user_model().objects.create_user(username="message-client", password="password123")
        client.groups.add(client_group)
        self.client.force_login(client)

        response = self.client.post(
            reverse("aterapija:contact"),
            {
                "name": "Message Client",
                "email": "message@example.com",
                "subject": "Question",
                "message": "Hello",
            },
        )

        self.assertRedirects(response, reverse("aterapija:contact"))
        self.assertTrue(Notification.objects.filter(recipient=admin, notification_type=Notification.TYPE_MESSAGE).exists())
        self.assertFalse(Notification.objects.filter(recipient=client, notification_type=Notification.TYPE_MESSAGE).exists())

    def test_client_dashboard_hides_cancelled_bookings_and_frees_time(self):
        client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)
        client = get_user_model().objects.create_user(username="cancel-client", password="password123")
        client.groups.add(client_group)
        therapist_user = get_user_model().objects.create_user(username="free-therapist")
        therapist = Therapist.objects.create(user=therapist_user, full_name="Free Therapist")
        category = ServiceCategory.objects.create(name="Free Services", description="Demo")
        service = Service.objects.create(
            category=category,
            name="Free Service",
            short_description="Short",
            full_description="Long",
            duration_minutes=60,
            price="90.00",
            is_active=True,
        )
        service.therapists.add(therapist)
        booking = BookingRequest.objects.create(
            client_name="Cancel Client",
            client_email="cancel@example.com",
            client=client,
            service=service,
            therapist=therapist,
            preferred_date=timezone.localdate() + timedelta(days=2),
            preferred_time=time(10, 0),
            status=BookingRequest.STATUS_CANCELLED,
        )
        self.client.force_login(client)

        response = self.client.get(reverse("aterapija:client_dashboard"))

        self.assertNotContains(response, "Free Service")
        self.assertTrue(
            BookingRequest.is_time_available(
                therapist,
                service,
                booking.preferred_date,
                booking.preferred_time,
            )
        )
