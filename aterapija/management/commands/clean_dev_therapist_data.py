from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from aterapija.auth_helpers import CLIENT_GROUP, THERAPIST_GROUP
from aterapija.models import (
    BookingRequest,
    ClientProfile,
    Service,
    Therapist,
    TherapistAvailability,
    WellbeingAssessment,
)


class Command(BaseCommand):
    help = "Development-only cleanup that keeps Alex Grok as the only therapist."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm-dev-cleanup",
            action="store_true",
            help="Required confirmation for destructive development cleanup.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without writing to the database.",
        )

    def handle(self, *args, **options):
        self.validate_development_safety(options)

        dry_run = options["dry_run"]
        User = get_user_model()

        alex = Therapist.objects.filter(full_name="Alex Grok").select_related("user").first()
        removed_therapists = Therapist.objects.exclude(full_name="Alex Grok")
        active_services = Service.objects.filter(is_active=True)

        summary = {
            "bookings_deleted": BookingRequest.objects.count(),
            "assessments_deleted": WellbeingAssessment.objects.count(),
            "client_profiles_deleted": ClientProfile.objects.count(),
            "availability_deleted": TherapistAvailability.objects.count(),
            "therapists_deleted": removed_therapists.count(),
            "alex_exists": bool(alex),
            "active_services_assigned": active_services.count(),
        }

        if dry_run:
            self.print_summary(summary, dry_run=True)
            return

        with transaction.atomic():
            BookingRequest.objects.all().delete()
            WellbeingAssessment.objects.all().delete()
            ClientProfile.objects.all().delete()
            TherapistAvailability.objects.all().delete()
            removed_therapists.delete()

            therapist_group, _created = Group.objects.get_or_create(name=THERAPIST_GROUP)
            client_group, _created = Group.objects.get_or_create(name=CLIENT_GROUP)

            alex = Therapist.objects.filter(full_name="Alex Grok").select_related("user").first()
            if alex is None:
                user, _created = User.objects.get_or_create(
                    username="alex.grok",
                    defaults={
                        "first_name": "Alex",
                        "last_name": "Grok",
                        "email": "alex.grok@example.com",
                    },
                )
                alex = Therapist.objects.create(
                    user=user,
                    full_name="Alex Grok",
                    is_active=True,
                )
            else:
                user = alex.user
                alex.is_active = True
                alex.save(update_fields=["is_active"])

            user.first_name = user.first_name or "Alex"
            user.last_name = user.last_name or "Grok"
            user.email = user.email or "alex.grok@example.com"
            user.save(update_fields=["first_name", "last_name", "email"])
            user.groups.add(therapist_group)
            user.groups.remove(client_group)

            for service in Service.objects.all():
                service.therapists.clear()
            alex.services.set(active_services)

        self.print_summary(summary, dry_run=False)

    def validate_development_safety(self, options):
        if not settings.DEBUG:
            raise CommandError("Refusing to run because DEBUG is False.")
        if not options["confirm_dev_cleanup"] and not options["dry_run"]:
            raise CommandError("Pass --confirm-dev-cleanup to run this destructive development cleanup.")
        if connection.vendor != "sqlite":
            raise CommandError("Refusing to run outside the local SQLite development database.")

    def print_summary(self, summary, dry_run):
        prefix = "Would delete" if dry_run else "Deleted"
        self.stdout.write(f"{prefix} {summary['bookings_deleted']} bookings.")
        self.stdout.write(f"{prefix} {summary['assessments_deleted']} questionnaire assessments.")
        self.stdout.write(f"{prefix} {summary['client_profiles_deleted']} client profiles.")
        self.stdout.write(f"{prefix} {summary['availability_deleted']} therapist availability records.")
        self.stdout.write(f"{prefix} {summary['therapists_deleted']} therapists other than Alex Grok.")
        if dry_run:
            alex_status = "exists" if summary["alex_exists"] else "would be created"
            self.stdout.write(f"Alex Grok: {alex_status}.")
            self.stdout.write(f"Would assign {summary['active_services_assigned']} active services to Alex Grok.")
            return
        self.stdout.write("Alex Grok is active and is the only remaining therapist.")
        self.stdout.write(f"Assigned {summary['active_services_assigned']} active services to Alex Grok.")
