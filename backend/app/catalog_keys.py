"""One Unicode key policy for API writes, ORM seed data and migration backfill."""
import unicodedata


def display_text(value):
    return ' '.join(unicodedata.normalize('NFC', value).split())


def catalog_key(value):
    return display_text(value).casefold()


KEY_FIELDS = {
    'product_types': {'name_key': 'name', 'sku_key': 'sku'},
    'batches': {'lot_key': 'lot_code'},
    'defect_types': {'name_key': 'name', 'code_key': 'code'},
}
