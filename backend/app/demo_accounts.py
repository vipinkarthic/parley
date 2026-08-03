"""Pre-seeded demo accounts so the app can be tested instantly.

These are always created on startup (independent of SEED_SAMPLE_DATA) and are
surfaced on the login page's "Demo accounts" helper. All share one password.
"""
DEMO_PASSWORD = "demo1234"

DEMO_ACCOUNTS = [
    {"name": "Vipin Karthic", "email": "vipin@demo.dev", "color": "#0B5CFF"},
    {"name": "Priya Sharma", "email": "priya@demo.dev", "color": "#EC4899"},
    {"name": "Marcus Lee", "email": "marcus@demo.dev", "color": "#12B76A"},
]
