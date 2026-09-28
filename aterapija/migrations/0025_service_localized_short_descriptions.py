from django.db import migrations, models


def backfill_localized_short_descriptions(apps, schema_editor):
    Service = apps.get_model("aterapija", "Service")

    for service in Service.objects.all():
        update_fields = []
        fallback_short = service.short_description or ""

        if not service.short_description_lt:
            service.short_description_lt = fallback_short or service.description_lt[:255]
            update_fields.append("short_description_lt")

        if not service.short_description_en:
            service.short_description_en = fallback_short or service.description_en[:255]
            update_fields.append("short_description_en")

        if update_fields:
            service.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ("aterapija", "0024_servicecategory_description_en_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="short_description_en",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="service",
            name="short_description_lt",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.RunPython(backfill_localized_short_descriptions, migrations.RunPython.noop),
    ]
