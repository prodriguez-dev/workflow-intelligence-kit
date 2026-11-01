"""Shared test setup: import path, a record builder, and the shipped config."""

import copy
import os
import sys
from datetime import date

sys.dont_write_bytecode = True
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(TESTS_DIR)
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
REPO_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", "..", "..", ".."))
CONFIG_PATH = os.path.join(SKILL_DIR, "config.toml")
FIXTURE_PATH = os.path.join(SKILL_DIR, "fixtures", "estimates.json")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import config as config_mod  # noqa: E402

CFG = config_mod.load(CONFIG_PATH)
TZ = CFG.business.tz  # America/Denver in the shipped config
TODAY = date(2026, 11, 2)

BASE = {
    "id": "EST-T1",
    "status": "open",
    "customer": {"first_name": "Pat", "last_name": "Placeholder", "email": "pat@example.com",
                 "phone": "555-0101", "do_not_contact": False},
    "job": {"title": "roof replacement", "address": "1 Test St, Sampleton"},
    "amount": 10000,
    "sent_at": "2026-10-27T10:00:00-06:00",
    "expires_on": None,
    "last_customer_reply_at": None,
    "follow_up_count": 0,
    "last_follow_up_at": None,
}


def rec(**overrides):
    """A qualifying record (6 days old on TODAY) with fields overridden.

    Keys under customer or job are written as customer__email=..., job__title=...
    """
    r = copy.deepcopy(BASE)
    for key, value in overrides.items():
        if "__" in key:
            outer, inner = key.split("__", 1)
            r[outer][inner] = value
        else:
            r[key] = value
    return r
