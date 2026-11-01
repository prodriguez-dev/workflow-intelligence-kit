"""Drafts follow the configured voice; bad config fails before any drafting."""

import tomllib
import unittest

from helpers import CFG, CONFIG_PATH, TODAY, TZ, rec

import config as config_mod
from drafts import SILENT, money, render_draft, render_telegram
from selection import evaluate, select


def draft_for(record, cfg=CFG):
    d = evaluate(record, TODAY, TZ, cfg.selection)
    assert d.action == "draft", d
    return d, render_draft(d, cfg)


def raw_config():
    with open(CONFIG_PATH, "rb") as fh:
        return tomllib.load(fh)


class Drafts(unittest.TestCase):
    def test_email_uses_voice_and_business_fields(self):
        _, text = draft_for(rec(expires_on="2026-11-26"))
        self.assertEqual(text["subject"], "Checking in on your roof replacement estimate")
        self.assertTrue(text["body"].startswith("Hi Pat,\n\n"))
        self.assertIn("sent over on Oct 27", text["body"])
        self.assertIn("Pricing holds through Nov 26.", text["body"])
        self.assertTrue(text["body"].endswith("Jordan\nExample Ridge Roofing | 555-0142"))

    def test_no_expiry_means_no_expiry_sentence_and_no_gap(self):
        _, text = draft_for(rec(expires_on=None))
        self.assertNotIn("Pricing holds", text["body"])
        self.assertNotIn("\n\n\n", text["body"])
        self.assertNotIn("  ", text["body"])

    def test_missing_first_name_uses_fallback_greeting(self):
        for first in (None, "", "  "):
            with self.subTest(first=first):
                _, text = draft_for(rec(customer__first_name=first))
                self.assertTrue(text["body"].startswith("Hi there,"))

    def test_final_follow_up_adds_final_sentence(self):
        _, first = draft_for(rec())
        _, last = draft_for(rec(sent_at="2026-10-15T09:00:00-06:00", follow_up_count=1,
                                last_follow_up_at="2026-10-27T09:00:00-06:00"))
        self.assertNotIn("pestering", first["body"])
        self.assertIn("I won't keep pestering you", last["body"])

    def test_sms_has_no_subject_and_is_short(self):
        _, text = draft_for(rec(customer__email=None, expires_on="2026-11-26"))
        self.assertEqual(text["subject"], "")
        self.assertIn("it's Jordan with Example Ridge Roofing", text["body"])
        self.assertLess(len(text["body"]), 320)  # two SMS segments at most

    def test_missing_job_title_uses_fallback(self):
        _, text = draft_for(rec(job__title=None))
        self.assertIn("your roofing estimate", text["subject"])

    def test_money(self):
        self.assertEqual(money(14850, "$"), "$14,850")
        self.assertEqual(money(6120.5, "$"), "$6,120.50")
        self.assertEqual(money(None, "$"), "")
        self.assertEqual(money(True, "$"), "")


class Telegram(unittest.TestCase):
    def test_nothing_to_do_is_silent(self):
        drafts, skipped = select([rec(status="won"), rec(id="X", last_customer_reply_at="2026-10-30T09:00:00-06:00")],
                                 TODAY, TZ, CFG.selection)
        self.assertEqual(render_telegram(drafts, [], skipped, TODAY, CFG), SILENT)

    def test_attention_alone_is_not_silent(self):
        drafts, skipped = select([rec(customer__email=None, customer__phone=None)], TODAY, TZ, CFG.selection)
        out = render_telegram(drafts, [], skipped, TODAY, CFG)
        self.assertIn("nothing to draft", out)
        self.assertIn("EST-T1 Pat Placeholder: no usable email or phone on file", out)
        self.assertNotIn("Nothing has been sent", out)  # no drafts, no approval footer

    def test_drafts_are_numbered_and_footer_says_nothing_sent(self):
        records = [rec(id="A"), rec(id="B", customer__email=None)]
        drafts, skipped = select(records, TODAY, TZ, CFG.selection)
        out = render_telegram(drafts, [render_draft(d, CFG) for d in drafts], skipped, TODAY, CFG)
        self.assertIn("[1/2] A", out)
        self.assertIn("[2/2] B", out)
        self.assertIn("Text to 555-0101", out)
        self.assertIn("Nothing has been sent.", out)

    def test_no_em_or_en_dashes_in_output(self):
        records = [rec(id="A", expires_on="2026-11-20"), rec(id="B", customer__email=None, follow_up_count=1,
                   last_follow_up_at="2026-10-28T09:00:00-06:00"), rec(id="C", status="lost")]
        drafts, skipped = select(records, TODAY, TZ, CFG.selection)
        out = render_telegram(drafts, [render_draft(d, CFG) for d in drafts], skipped, TODAY, CFG)
        self.assertNotIn("\u2014", out)  # em dash
        self.assertNotIn("\u2013", out)  # en dash


class ConfigValidation(unittest.TestCase):
    def test_shipped_config_loads(self):
        self.assertEqual(CFG.selection.followup_after_days, 3)
        self.assertEqual(CFG.business.timezone, "America/Denver")

    def test_unknown_placeholder_is_rejected(self):
        raw = raw_config()
        raw["voice"]["email_body"] = "Hi {frist_name}"
        with self.assertRaisesRegex(config_mod.ConfigError, r"\{frist_name\}"):
            config_mod.from_dict(raw)

    def test_unbalanced_brace_is_rejected(self):
        raw = raw_config()
        raw["voice"]["sms_body"] = "Hi {first_name"
        with self.assertRaises(config_mod.ConfigError):
            config_mod.from_dict(raw)

    def test_sentence_cannot_nest_itself(self):
        raw = raw_config()
        raw["voice"]["expiry_sentence"] = "{expiry_sentence}"
        with self.assertRaises(config_mod.ConfigError):
            config_mod.from_dict(raw)

    def test_bad_threshold_is_rejected(self):
        for value in (0, -3, "3", 2.5, True):
            with self.subTest(value=value):
                raw = raw_config()
                raw["selection"]["followup_after_days"] = value
                with self.assertRaises(config_mod.ConfigError):
                    config_mod.from_dict(raw)

    def test_bad_timezone_is_rejected(self):
        raw = raw_config()
        raw["business"]["timezone"] = "Mountain Time"
        with self.assertRaisesRegex(config_mod.ConfigError, "timezone"):
            config_mod.from_dict(raw)

    def test_unknown_voice_key_is_rejected(self):
        raw = raw_config()
        raw["voice"]["tone"] = "cheery"
        with self.assertRaisesRegex(config_mod.ConfigError, "tone"):
            config_mod.from_dict(raw)

    def test_missing_source_is_rejected(self):
        raw = raw_config()
        del raw["source"]["base_url"]
        with self.assertRaisesRegex(config_mod.ConfigError, "base_url"):
            config_mod.from_dict(raw)

    def test_bad_channel_preference(self):
        raw = raw_config()
        raw["selection"]["channel_preference"] = ["pigeon"]
        with self.assertRaises(config_mod.ConfigError):
            config_mod.from_dict(raw)


if __name__ == "__main__":
    unittest.main()
