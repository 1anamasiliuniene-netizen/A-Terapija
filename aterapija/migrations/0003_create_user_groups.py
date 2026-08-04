from django.db import migrations


def create_user_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ["Admin", "Therapist", "Client"]:
        Group.objects.get_or_create(name=name)


def remove_user_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=["Admin", "Therapist", "Client"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("aterapija", "0002_bookingrequest_client_wellbeingassessment"),
    ]

    operations = [
        migrations.RunPython(create_user_groups, remove_user_groups),
    ]
