from django import template

register = template.Library()


@register.filter
def localized_title(value):
    return getattr(value, "display_title", str(value))


@register.filter
def localized_description(value):
    return getattr(value, "display_description", "")


@register.filter
def localized_short_description(value):
    return getattr(value, "display_short_description", "")


@register.filter
def localized_bio(value):
    return getattr(value, "display_bio", "")


@register.filter
def localized_content(value):
    return getattr(value, "display_content", "")
