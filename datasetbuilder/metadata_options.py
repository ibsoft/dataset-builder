"""Administrator-managed metadata option definitions."""
from .models import MetadataOption, db

OPTION_FIELDS = ('Knowledge Type', 'Category', 'Operational Status', 'Knowledge Status', 'Solution Status')
FIELD_LIMITS = {'Knowledge Type': 120, 'Category': 120, 'Operational Status': 120,
                'Knowledge Status': 60, 'Solution Status': 120}


def all_options():
    options = {field: [] for field in OPTION_FIELDS}
    for option in db.session.query(MetadataOption).order_by(MetadataOption.position, MetadataOption.id):
        if option.field in options:
            options[option.field].append(option)
    return options


def option_label(options, field, value, lang):
    if lang == 'el':
        for option in options.get(field, []):
            if option.value == value:
                return option.greek_label
    return value
