from django import template

register = template.Library()


@register.filter
def get_item(d, key):
    """Safely get dict item by key in templates."""
    try:
        if isinstance(d, dict):
            return d.get(key, '')
        # If it's a Django object or something else, try attribute
        return getattr(d, key, '')
    except Exception:
        return ''
