"""The ledger: shops, customers and the append-only money events, with every business rule in one place.

Both the phone app's sync (apps.sync) and the REST read endpoints (apps.shops) call apps.ledger.service, and the
website will too, so a rule can never differ between the app and the website.
"""
