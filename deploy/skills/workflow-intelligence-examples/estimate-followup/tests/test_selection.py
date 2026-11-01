"""Which estimates qualify for a follow-up draft, and why the rest do not."""

import unittest
from dataclasses import replace
from datetime import timedelta
from zoneinfo import ZoneInfo

from helpers import CFG, TODAY, TZ, rec

from selection import evaluate, select

SEL = CFG.selection  # followup_after_days=3, max_followups=2, redraft_after_days=3


def decide(record, today=TODAY, tz=TZ, selection=SEL, surfaced=None):
    return evaluate(record, today, tz, selection, surfaced)


class Threshold(unittest.TestCase):
    def test_qualifies_exactly_at_threshold(self):
        d = decide(rec(sent_at="2026-10-30T09:00:00-06:00"))
        self.assertEqual((d.action, d.days_waiting), ("draft", 3))

    def test_one_day_short_is_not_due(self):
        d = decide(rec(sent_at="2026-10-31T09:00:00-06:00"))
        self.assertEqual((d.action, d.reason, d.days_waiting), ("skip", "not_due", 2))

    def test_threshold_comes_from_config(self):
        strict = replace(SEL, followup_after_days=7)
        self.assertEqual(decide(rec(), selection=strict).reason, "not_due")  # 6 days < 7
        self.assertEqual(decide(rec(sent_at="2026-10-26T09:00:00-06:00"), selection=strict).action, "draft")

    def test_days_count_from_last_follow_up_not_send(self):
        d = decide(rec(sent_at="2026-10-01T09:00:00-06:00", follow_up_count=1,
                       last_follow_up_at="2026-11-01T09:00:00-07:00"))
        self.assertEqual((d.reason, d.days_waiting), ("not_due", 1))

    def test_calendar_days_in_business_timezone(self):
        # 23:30 in Denver on Oct 30 is 05:30 UTC on Oct 31.
        late = rec(sent_at="2026-10-30T23:30:00-06:00")
        self.assertEqual(decide(late).action, "draft")  # Denver: 3 days
        self.assertEqual(decide(late, tz=ZoneInfo("UTC")).reason, "not_due")  # UTC: 2 days

    def test_naive_timestamp_is_business_local(self):
        self.assertEqual(decide(rec(sent_at="2026-10-30T23:30:00")).days_waiting, 3)

    def test_date_only_sent_at(self):
        self.assertEqual(decide(rec(sent_at="2026-10-30")).days_waiting, 3)

    def test_sent_in_the_future_is_not_due(self):
        self.assertEqual(decide(rec(sent_at="2026-11-05T09:00:00-07:00")).reason, "not_due")


class Replied(unittest.TestCase):
    def test_reply_after_send_skips(self):
        d = decide(rec(last_customer_reply_at="2026-10-28T19:00:00-06:00"))
        self.assertEqual((d.action, d.reason), ("skip", "replied"))

    def test_reply_same_instant_as_send_counts_as_reply(self):
        self.assertEqual(decide(rec(last_customer_reply_at=rec()["sent_at"])).reason, "replied")

    def test_reply_before_send_is_an_old_inquiry(self):
        d = decide(rec(last_customer_reply_at="2026-10-09T08:00:00-06:00"))
        self.assertEqual(d.action, "draft")

    def test_reply_after_a_follow_up_skips(self):
        d = decide(rec(sent_at="2026-10-15T09:00:00-06:00", follow_up_count=1,
                       last_follow_up_at="2026-10-22T09:00:00-06:00",
                       last_customer_reply_at="2026-10-23T12:00:00-06:00"))
        self.assertEqual(d.reason, "replied")

    def test_replied_wins_over_missing_contact(self):
        d = decide(rec(customer__email="", customer__phone=None,
                       last_customer_reply_at="2026-10-28T19:00:00-06:00"))
        self.assertEqual((d.reason, d.needs_attention), ("replied", False))


class Expired(unittest.TestCase):
    def test_expired_yesterday_skips(self):
        d = decide(rec(expires_on=(TODAY - timedelta(days=1)).isoformat()))
        self.assertEqual((d.action, d.reason), ("skip", "expired"))

    def test_expiring_today_still_qualifies(self):
        self.assertEqual(decide(rec(expires_on=TODAY.isoformat())).action, "draft")

    def test_no_expiry_qualifies(self):
        self.assertEqual(decide(rec(expires_on=None)).action, "draft")
        self.assertEqual(decide(rec(expires_on="")).action, "draft")

    def test_expiry_as_datetime_uses_its_date(self):
        self.assertEqual(decide(rec(expires_on="2026-11-01T23:59:00-06:00")).reason, "expired")


class Contact(unittest.TestCase):
    def test_no_email_and_no_phone_needs_attention(self):
        d = decide(rec(customer__email=None, customer__phone=None))
        self.assertEqual((d.action, d.reason, d.needs_attention), ("skip", "missing_contact", True))

    def test_blank_and_malformed_values_count_as_missing(self):
        for email, phone in (("   ", ""), ("not-an-email", "12"), ("a@b", "call me")):
            with self.subTest(email=email, phone=phone):
                self.assertEqual(decide(rec(customer__email=email, customer__phone=phone)).reason, "missing_contact")

    def test_missing_customer_object(self):
        self.assertEqual(decide(rec(customer=None)).reason, "missing_contact")

    def test_email_preferred_over_phone(self):
        d = decide(rec())
        self.assertEqual((d.channel, d.to), ("email", "pat@example.com"))

    def test_phone_only_drafts_a_text(self):
        d = decide(rec(customer__email=None))
        self.assertEqual((d.channel, d.to), ("sms", "555-0101"))

    def test_channel_preference_from_config(self):
        d = decide(rec(), selection=replace(SEL, channel_preference=("sms", "email")))
        self.assertEqual(d.channel, "sms")

    def test_email_is_trimmed(self):
        self.assertEqual(decide(rec(customer__email="  pat@example.com ")).to, "pat@example.com")

    def test_do_not_contact_skips_quietly(self):
        d = decide(rec(customer__do_not_contact=True))
        self.assertEqual((d.reason, d.needs_attention), ("do_not_contact", False))


class StatusAndLimits(unittest.TestCase):
    def test_only_open_estimates(self):
        for status in ("won", "lost", "draft", None, "OPEN"):
            with self.subTest(status=status):
                self.assertEqual(decide(rec(status=status)).reason, "not_open")

    def test_follow_up_limit(self):
        self.assertEqual(decide(rec(follow_up_count=2)).reason, "max_followups")

    def test_last_allowed_follow_up_is_final(self):
        d = decide(rec(sent_at="2026-10-15T09:00:00-06:00", follow_up_count=1,
                       last_follow_up_at="2026-10-27T09:00:00-06:00"))
        self.assertEqual((d.action, d.followup_number, d.is_final), ("draft", 2, True))

    def test_first_follow_up_is_not_final(self):
        d = decide(rec())
        self.assertEqual((d.followup_number, d.is_final), (1, False))

    def test_logged_follow_up_with_zero_count_counts_as_one(self):
        d = decide(rec(sent_at="2026-10-10T09:00:00-06:00", follow_up_count=0,
                       last_follow_up_at="2026-10-27T09:00:00-06:00"))
        self.assertEqual(d.followup_number, 2)


class BadData(unittest.TestCase):
    def test_missing_sent_at(self):
        for value in (None, "", "  "):
            with self.subTest(value=value):
                d = decide(rec(sent_at=value))
                self.assertEqual((d.reason, d.needs_attention), ("bad_data", True))

    def test_unparseable_dates(self):
        for field in ("sent_at", "last_customer_reply_at", "last_follow_up_at", "expires_on"):
            with self.subTest(field=field):
                self.assertEqual(decide(rec(**{field: "next tuesday"})).reason, "bad_data")

    def test_bad_follow_up_count(self):
        for value in (-1, "2", True):
            with self.subTest(value=value):
                self.assertEqual(decide(rec(follow_up_count=value)).reason, "bad_data")


class Ledger(unittest.TestCase):
    def test_surfaced_inside_window_is_skipped(self):
        d = decide(rec(), surfaced={"EST-T1": "2026-11-01"})
        self.assertEqual(d.reason, "surfaced_recently")

    def test_surfaced_today_is_skipped(self):
        self.assertEqual(decide(rec(), surfaced={"EST-T1": TODAY.isoformat()}).reason, "surfaced_recently")

    def test_after_window_it_comes_back_marked(self):
        d = decide(rec(), surfaced={"EST-T1": "2026-10-30"})  # 3 days = redraft_after_days
        self.assertEqual((d.action, d.previously_surfaced_on), ("draft", "2026-10-30"))

    def test_attention_items_are_not_repeated_daily(self):
        d = decide(rec(customer__email=None, customer__phone=None), surfaced={"EST-T1": "2026-11-01"})
        self.assertEqual(d.reason, "surfaced_recently")

    def test_bad_data_is_not_repeated_daily(self):
        d = decide(rec(sent_at=""), surfaced={"EST-T1": "2026-11-01"})
        self.assertEqual((d.reason, d.needs_attention), ("surfaced_recently", False))
        self.assertEqual(decide(rec(sent_at=""), surfaced={"EST-T1": "2026-10-20"}).reason, "bad_data")

    def test_garbage_ledger_date_is_ignored(self):
        self.assertEqual(decide(rec(), surfaced={"EST-T1": "soon"}).action, "draft")


class SelectMany(unittest.TestCase):
    def test_oldest_first_then_largest(self):
        records = [
            rec(id="A", sent_at="2026-10-29T09:00:00-06:00"),
            rec(id="B", sent_at="2026-10-20T09:00:00-06:00"),
            rec(id="C", sent_at="2026-10-29T09:00:00-06:00", amount=50000),
        ]
        drafts, _ = select(records, TODAY, TZ, SEL)
        self.assertEqual([d.estimate_id for d in drafts], ["B", "C", "A"])

    def test_cap_holds_the_rest_over(self):
        records = [rec(id=f"E{i}", sent_at=f"2026-10-{10 + i}T09:00:00-06:00") for i in range(5)]
        drafts, skipped = select(records, TODAY, TZ, replace(SEL, max_drafts_per_run=2))
        self.assertEqual([d.estimate_id for d in drafts], ["E0", "E1"])
        self.assertEqual(sorted(d.estimate_id for d in skipped if d.reason == "held_over"), ["E2", "E3", "E4"])

    def test_non_numeric_amount_does_not_break_sorting(self):
        drafts, _ = select([rec(id="A", amount="lots"), rec(id="B", amount=None)], TODAY, TZ, SEL)
        self.assertEqual(len(drafts), 2)


if __name__ == "__main__":
    unittest.main()
