"""Add administrator-managed metadata choices.

Revision ID: 0004_metadata_options
Revises: 0003_default_sections
"""
from alembic import op
import sqlalchemy as sa

revision = '0004_metadata_options'
down_revision = '0003_default_sections'
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table(
        'metadata_options',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('field', sa.String(40), nullable=False),
        sa.Column('value', sa.String(120), nullable=False),
        sa.Column('value_key', sa.String(400), nullable=False),
        sa.Column('greek_label', sa.String(120), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.UniqueConstraint('field', 'value_key', name='uq_metadata_option_field_key'),
    )
    defaults = {
        'Knowledge Type': [('Troubleshooting', 'Αντιμετώπιση προβλημάτων'), ('Fact', 'Γεγονός'),
                           ('Known issue', 'Γνωστό πρόβλημα'), ('Verified solution', 'Επαληθευμένη λύση'),
                           ('Troubleshooting note', 'Σημείωση αντιμετώπισης προβλήματος'),
                           ('FAQ', 'Συχνές ερωτήσεις'), ('Lesson learned', 'Δίδαγμα')],
        'Category': [('Connectivity', 'Συνδεσιμότητα'),
                     ('Hardware', 'Υλικό'), ('Software', 'Λογισμικό'),
                     ('Configuration', 'Ρυθμίσεις'), ('Installation', 'Εγκατάσταση'),
                     ('Authentication', 'Αυθεντικοποίηση'), ('Performance', 'Απόδοση'),
                     ('Security', 'Ασφάλεια'), ('Integration', 'Διασύνδεση'),
                     ('Data', 'Δεδομένα'), ('Maintenance', 'Συντήρηση')],
        'Operational Status': [('Operational', 'Λειτουργικό'), ('Degraded', 'Υποβαθμισμένο'),
                               ('SPCommunicationDown', 'Απώλεια επικοινωνίας SP'),
                               ('Offline', 'Εκτός σύνδεσης'), ('Maintenance', 'Συντήρηση')],
        'Knowledge Status': [('Draft', 'Πρόχειρο'), ('In Review', 'Υπό έλεγχο'),
                             ('Approved', 'Εγκεκριμένο'), ('Published', 'Δημοσιευμένο'),
                             ('Archived', 'Αρχειοθετημένο')],
        'Solution Status': [('Not Started', 'Δεν ξεκίνησε'), ('In Progress', 'Σε εξέλιξη'),
                            ('Diagnostic Only', 'Μόνο διάγνωση'), ('Verified', 'Επαληθευμένο'),
                            ('Rejected', 'Απορρίφθηκε')],
    }
    op.bulk_insert(table, [
        {'field': field, 'value': value, 'value_key': value.casefold(),
         'greek_label': greek, 'position': position}
        for field, values in defaults.items() for position, (value, greek) in enumerate(values)
    ])


def downgrade():
    op.drop_table('metadata_options')
