from django.db import migrations


ABOUT_DEFAULTS = {
    "hero_eyebrow": {
        "lt": "Apie A Terapija",
        "en": "About A Terapija",
    },
    "hero_title": {
        "lt": "Terapija, padedanti vėl pasijusti savimi",
        "en": "Therapy that helps you return to yourself",
    },
    "hero_subtitle": {
        "lt": "Jauki erdvė, kur susilieja terapija, kūno pažinimas ir sąmoningas buvimas",
        "en": "A gentle space where therapeutic care, body awareness and mindful presence meet",
    },
    "story_eyebrow": {
        "lt": "Mūsų filosofija",
        "en": "Our approach",
    },
    "story_title": {
        "lt": "Sveikatinimas prasideda, kai jaučiamės pakankamai saugūs suprasti patį save",
        "en": "Healing begins when we feel safe enough to understand ourselves",
    },
    "story_text_1": {
        "lt": "A Terapija - tai rami, profesionali ir šilta erdvė žmonėms, norintiems kasdien geriau jaustis savo kūne ir su savo emocijomis.",
        "en": "A Terapija was created as a calm, professional and human space for people who want to feel better in their body, emotions and everyday life.",
    },
    "story_text_2": {
        "lt": "Tikime, kad terapija turi būti skaidri, pagarbi ir palaikanti - niekada šalta, skubi ar varginanti.",
        "en": "We believe that therapy should feel clear, respectful and supportive - never cold, rushed or overwhelming.",
    },
    "therapist_eyebrow": {
        "lt": "Susipažinkite su mūsų terapeutais",
        "en": "Meet our therapists",
    },
    "therapist_title": {
        "lt": "Susipažinkite su mūsų terapeutais",
        "en": "Meet our therapists",
    },
    "therapist_intro": {
        "lt": "",
        "en": "",
    },
    "mission": {
        "lt": "",
        "en": "",
    },
    "vision": {
        "lt": "",
        "en": "",
    },
    "values": {
        "lt": "",
        "en": "",
    },
    "process_title": {
        "lt": "Kaip vyksta terapija",
        "en": "How therapy works",
    },
    "process_1_title": {
        "lt": "Įsivertinkite",
        "en": "Assess",
    },
    "process_1_text": {
        "lt": "Mes aiškinamės jūsų poreikius",
        "en": "We clarify your needs",
    },
    "process_2_title": {
        "lt": "Rezervuokite",
        "en": "Book",
    },
    "process_2_text": {
        "lt": "Pasirinkite tinkamą laiką",
        "en": "Choose a suitable time",
    },
    "process_3_title": {
        "lt": "Patirkite",
        "en": "Heal",
    },
    "process_3_text": {
        "lt": "Jūsų sesija pritaikyta individualiai",
        "en": "Your session is personalised",
    },
    "process_4_title": {
        "lt": "Integruokite",
        "en": "Integrate",
    },
    "process_4_text": {
        "lt": "Visada turite mūsų palaikymą",
        "en": "You leave with support",
    },
    "cta_eyebrow": {
        "lt": "Pradėkite palengva",
        "en": "Begin gently",
    },
    "cta_title": {
        "lt": "Ar jūs pasiruošę pasirūpinti savimi?",
        "en": "Ready to take care of yourself?",
    },
    "cta_text": {
        "lt": "Pradėkite nuo mažo ir aiškaus žingsnio.",
        "en": "Start with one clear, supportive step.",
    },
}


def backfill_about_page(apps, schema_editor):
    AboutPage = apps.get_model("aterapija", "AboutPage")
    for about_page in AboutPage.objects.all():
        for field_name, defaults in ABOUT_DEFAULTS.items():
            legacy_value = getattr(about_page, field_name, "")
            lt_field = f"{field_name}_lt"
            en_field = f"{field_name}_en"

            if not getattr(about_page, lt_field, ""):
                setattr(about_page, lt_field, defaults["lt"] or legacy_value)
            if not getattr(about_page, en_field, ""):
                setattr(about_page, en_field, legacy_value or defaults["en"])

        about_page.save()


class Migration(migrations.Migration):

    dependencies = [
        ("aterapija", "0021_aboutpage_hero_eyebrow_aboutpage_hero_eyebrow_en_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_about_page, migrations.RunPython.noop),
    ]
