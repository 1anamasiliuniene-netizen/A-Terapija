from django.db import migrations


def backfill_lithuanian_content_fields(apps, schema_editor):
    Service = apps.get_model("aterapija", "Service")
    Therapist = apps.get_model("aterapija", "Therapist")
    Article = apps.get_model("aterapija", "Article")

    for service in Service.objects.all():
        update_fields = []
        if not service.title_lt:
            service.title_lt = service.name
            update_fields.append("title_lt")
        if not service.description_lt:
            service.description_lt = service.full_description or service.short_description
            update_fields.append("description_lt")
        if update_fields:
            service.save(update_fields=update_fields)

    for therapist in Therapist.objects.all():
        if not therapist.bio_lt and therapist.bio:
            therapist.bio_lt = therapist.bio
            therapist.save(update_fields=["bio_lt"])

    for article in Article.objects.all():
        update_fields = []
        if not article.title_lt:
            article.title_lt = article.title
            update_fields.append("title_lt")
        if not article.content_lt:
            article.content_lt = article.body
            update_fields.append("content_lt")

        is_translated_to_en = bool(article.title_en and article.content_en)
        if article.is_translated_to_en != is_translated_to_en:
            article.is_translated_to_en = is_translated_to_en
            update_fields.append("is_translated_to_en")

        if update_fields:
            article.save(update_fields=update_fields)


def noop_reverse(apps, schema_editor):
    # Existing content must not be removed if this migration is rolled back.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("aterapija", "0014_article_content_en_article_content_lt_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_lithuanian_content_fields, noop_reverse),
    ]
