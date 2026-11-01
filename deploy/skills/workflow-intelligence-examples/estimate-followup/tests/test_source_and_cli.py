"""The two-call source (fixture and real HTTP) and the CLI end to end."""

import io
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from datetime import date

from helpers import FIXTURE_PATH, TODAY

import estimate_followup
import fixture_server
from source import FixtureSource, HttpSource, SourceError, shift_record

EXPECTED_DRAFTS = ["EST-2041", "EST-2043", "EST-2051", "EST-2053", "EST-2042"]


def cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = estimate_followup.run(list(args))
    return code, out.getvalue(), err.getvalue()


class Fixture(unittest.TestCase):
    def test_call_one_lists_only_open(self):
        ids = FixtureSource(FIXTURE_PATH).list_open_ids()
        self.assertNotIn("EST-2048", ids)  # won
        self.assertNotIn("EST-2052", ids)  # lost
        self.assertEqual(len(ids), 12)

    def test_call_two_reads_by_id_and_404s(self):
        src = FixtureSource(FIXTURE_PATH)
        self.assertEqual(src.get_estimate("EST-2041")["customer"]["last_name"], "Placeholder")
        self.assertIsNone(src.get_estimate("EST-9999"))

    def test_shift_dates_moves_the_fixture_to_today(self):
        src = FixtureSource(FIXTURE_PATH, today=date(2026, 12, 2), shift_dates=True)
        self.assertEqual(src.shift_days, 30)
        rec = src.get_estimate("EST-2041")
        self.assertEqual(rec["sent_at"], "2026-11-26T10:14:00-06:00")
        self.assertEqual(rec["expires_on"], "2026-12-26")

    def test_shift_leaves_bad_and_empty_values_alone(self):
        r = shift_record({"sent_at": "", "expires_on": "garbage", "last_follow_up_at": None}, 5)
        self.assertEqual(r, {"sent_at": "", "expires_on": "garbage", "last_follow_up_at": None})

    def test_unreadable_fixture_is_a_source_error(self):
        with self.assertRaises(SourceError):
            FixtureSource("/nonexistent/estimates.json")

    def test_fixture_is_clearly_fake(self):
        with open(FIXTURE_PATH) as fh:
            for e in json.load(fh)["estimates"]:
                c = e["customer"]
                if c.get("email"):
                    self.assertRegex(c["email"], r"@example\.(com|net)$")
                if c.get("phone"):
                    self.assertRegex(c["phone"], r"^555-01\d\d$")


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.url = fixture_server.start(FIXTURE_PATH, today=TODAY)
        cls.auth_server, cls.auth_url = fixture_server.start(FIXTURE_PATH, today=TODAY, token="t0ken")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.auth_server.shutdown()

    def test_http_matches_fixture(self):
        http, fixture = HttpSource(self.url), FixtureSource(FIXTURE_PATH)
        ids = http.list_open_ids()
        self.assertEqual(ids, fixture.list_open_ids())
        self.assertEqual(http.get_estimate(ids[0]), fixture.get_estimate(ids[0]))
        self.assertIsNone(http.get_estimate("EST-9999"))
        self.assertEqual(http.calls[0], "GET /estimates?status=open -> 200")
        self.assertEqual(http.calls[-1], "GET /estimates/EST-9999 -> 404")

    def test_token_is_sent_and_required(self):
        self.assertEqual(len(HttpSource(self.auth_url, token="t0ken").list_open_ids()), 12)
        with self.assertRaisesRegex(SourceError, "401.*ESTIMATES_API_TOKEN"):
            HttpSource(self.auth_url, token="wrong", token_env="ESTIMATES_API_TOKEN").list_open_ids()

    def test_fixture_server_refuses_writes(self):
        req = urllib.request.Request(f"{self.url}/estimates/EST-2041", data=b"{}", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 405)

    def test_plain_http_to_remote_host_is_refused(self):
        with self.assertRaisesRegex(SourceError, "https"):
            HttpSource("http://crm.example.com/api")
        HttpSource("https://crm.example.com/api")  # fine

    def test_unreachable_is_a_source_error(self):
        server, url = fixture_server.start(FIXTURE_PATH)
        server.shutdown()
        server.server_close()
        with self.assertRaisesRegex(SourceError, "unreachable"):
            HttpSource(url, retries=0, timeout=2).list_open_ids()

    def test_cli_over_http_gives_same_drafts(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = cli("--source", self.url, "--today", "2026-11-02", "--state", f"{tmp}/s.json")
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual(result["source"], "http")
        self.assertEqual([d["estimate_id"] for d in result["drafts"]], EXPECTED_DRAFTS)

    def test_cli_exit_4_when_source_fails(self):
        code, _, err = cli("--source", "http://127.0.0.1:9/", "--today", "2026-11-02", "--state", "/nonexistent/s.json")
        self.assertEqual(code, 4)
        self.assertIn("source error", err)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "nested", "surfaced.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_shipped_fixture_end_to_end(self):
        code, out, _ = cli("--today", "2026-11-02", "--state", self.state)
        self.assertEqual(code, 0)
        result = json.loads(out)
        self.assertEqual([d["estimate_id"] for d in result["drafts"]], EXPECTED_DRAFTS)
        self.assertEqual({a["estimate_id"]: a["reason"] for a in result["needs_attention"]},
                         {"EST-2046": "missing_contact", "EST-2054": "bad_data"})
        self.assertEqual({s["estimate_id"]: s["reason"] for s in result["skipped"]}, {
            "EST-2044": "replied", "EST-2045": "expired", "EST-2047": "not_due",
            "EST-2049": "max_followups", "EST-2050": "do_not_contact",
        })
        self.assertFalse(os.path.exists(self.state))  # preview never writes

    def test_shifted_fixture_gives_same_result_any_day(self):
        code, out, _ = cli("--today", "2027-03-15", "--state", self.state)
        self.assertEqual([d["estimate_id"] for d in json.loads(out)["drafts"]], EXPECTED_DRAFTS)

    def test_record_then_rerun_is_silent(self):
        code, out, _ = cli("--today", "2026-11-02", "--state", self.state, "--record", "--format", "telegram")
        self.assertEqual(code, 0)
        self.assertIn("5 drafts to review", out)
        with open(self.state) as fh:
            ledger = json.load(fh)["surfaced"]
        self.assertEqual(set(ledger), set(EXPECTED_DRAFTS) | {"EST-2046", "EST-2054"})
        self.assertEqual(oct(os.stat(self.state).st_mode & 0o777), "0o600")

        code, out, _ = cli("--today", "2026-11-02", "--state", self.state, "--record", "--format", "telegram")
        self.assertEqual(out.strip(), "[SILENT]")

    def test_unsaveable_ledger_is_reported_in_the_message(self):
        blocker = os.path.join(self.tmp.name, "file")
        open(blocker, "w").close()
        code, out, err = cli("--today", "2026-11-02", "--state", os.path.join(blocker, "s.json"),
                             "--record", "--format", "telegram")
        self.assertEqual(code, 0)
        self.assertIn("could not save the list of drafted estimates", out)
        self.assertIn("could not save ledger", err)

    def test_corrupt_ledger_warns_and_continues(self):
        os.makedirs(os.path.dirname(self.state))
        with open(self.state, "w") as fh:
            fh.write("{not json")
        code, out, err = cli("--today", "2026-11-02", "--state", self.state)
        self.assertEqual(code, 0)
        self.assertIn("ignoring unreadable ledger", err)
        self.assertEqual(len(json.loads(out)["drafts"]), 5)

    def test_bad_config_exits_2(self):
        bad = os.path.join(self.tmp.name, "bad.toml")
        with open(bad, "w") as fh:
            fh.write('[source]\nbase_url = "fixtures/estimates.json"\n[voice]\nemail_body = "{oops}"\n')
        code, _, err = cli("--config", bad, "--today", "2026-11-02", "--state", self.state)
        self.assertEqual(code, 2)
        self.assertIn("{oops}", err)

    def test_bad_today_exits_2(self):
        self.assertEqual(cli("--today", "11/02/2026", "--state", self.state)[0], 2)

    def test_listed_but_gone_counts_as_not_found(self):
        class Flaky(FixtureSource):
            def get_estimate(self, eid):
                return None if eid == "EST-2041" else super().get_estimate(eid)

        original = estimate_followup.open_source
        estimate_followup.open_source = lambda *a, **k: Flaky(FIXTURE_PATH)
        try:
            _, out, _ = cli("--today", "2026-11-02", "--state", self.state)
        finally:
            estimate_followup.open_source = original
        result = json.loads(out)
        self.assertNotIn("EST-2041", [d["estimate_id"] for d in result["drafts"]])
        self.assertIn({"estimate_id": "EST-2041", "reason": "not_found", "label": "gone from the CRM",
                       "detail": "listed as open but the read returned 404"}, result["skipped"])


if __name__ == "__main__":
    unittest.main()
