import json
from types import SimpleNamespace

import httpx
from openai import APIConnectionError

from lapse.ingest.extract import BatchExtractor


class FakeClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


def response(msg_id="<test@example.com>", **kwargs):
    return {"msg_id": msg_id, "event": "signup", "service_guess": "Example", "confidence": 0.75, **kwargs}


def test_merge_cache_and_inbox_identity(raw, tmp_path):
    cache = tmp_path / "cache.json"
    client = FakeClient(
        [
            json.dumps(
                {
                    "events": [
                        response(
                            event="other",
                            account_identifier="wrong@example.com",
                            phone_last4=["9999"],
                            deadline="2030-01-01",
                        )
                    ]
                }
            )
        ]
    )
    email = raw(
        "Your account will be deactivated on 15 November 2026. Recovery phone ending in 4321.",
        sender="notice@example.edu",
    )
    result = next(iter(BatchExtractor(client=client, cache_path=cache).extract([email])))
    assert result.account_identifier == "demo@example.com"
    assert result.phone_last4 == ["4321"]
    assert str(result.deadline) == "2026-11-15"
    assert result.event == "deactivation_notice"
    assert result.service_guess == "Example"
    replay = raw(email.body_text, sender=email.sender, inbox="email_college")
    cached = next(iter(BatchExtractor(client=client, cache_path=cache).extract([replay])))
    assert cached.inbox == "email_college"
    assert len(client.calls) == 1
    assert "body_text" not in cache.read_text()
    assert "Recovery phone" not in cache.read_text()


def test_retry_then_success(raw, tmp_path):
    client = FakeClient(["bad json", "```json\n" + json.dumps([response()]) + "\n```"])
    sleeps = []
    event = next(
        iter(
            BatchExtractor(client=client, cache_path=tmp_path / "c", sleep=sleeps.append).extract(
                [raw(sender="n@example.com")]
            )
        )
    )
    assert event.event == "signup"
    assert sleeps == [1]
    assert len(client.calls) == 2


def test_failure_not_cached_and_no_llm_ignores_cache(raw, tmp_path):
    cache = tmp_path / "c"
    error = APIConnectionError(request=httpx.Request("POST", "https://example.com"))
    client = FakeClient([error] * 6)
    email = raw("Welcome!", sender="n@example.com")
    event = next(iter(BatchExtractor(client=client, cache_path=cache, sleep=lambda _: None).extract([email])))
    assert event.event == "signup"
    assert event.confidence <= 0.6
    assert not cache.exists()
    client = FakeClient([json.dumps([response()])])
    assert (
        next(iter(BatchExtractor(client=client, cache_path=cache).extract([email]))).service_guess
        == "Example"
    )
    assert next(iter(BatchExtractor(use_llm=False, cache_path=cache).extract([email]))).service_guess is None


def test_batches_twenty_and_skip_confident_rules(raw, tmp_path):
    emails = [raw(msg_id=f"<{i}@example.com>", sender="n@example.com") for i in range(41)]
    client = FakeClient(
        [
            json.dumps([response(email.msg_id) for email in emails[start : start + 20]])
            for start in (0, 20, 40)
        ]
    )
    results = list(BatchExtractor(client=client, cache_path=tmp_path / "c").extract(emails))
    assert len(results) == 41
    assert [len(json.loads(call["messages"][1]["content"])) for call in client.calls] == [20, 20, 1]
    assert (
        next(
            iter(
                BatchExtractor(client=client, cache_path=tmp_path / "c").extract(
                    [raw("New sign-in on Pixel 9")]
                )
            )
        ).device
        == "Pixel 9"
    )
    assert len(client.calls) == 3


def test_bad_item_does_not_discard_siblings(raw, tmp_path):
    client = FakeClient([json.dumps([response(), response("bad", event="invented", confidence=5)])])
    events = list(
        BatchExtractor(client=client, cache_path=tmp_path / "c").extract(
            [raw(sender="n@example.com"), raw(msg_id="bad", sender="n@example.com")]
        )
    )
    assert events[0].service_guess == "Example"
    assert events[1].event == "other"
    assert events[1].confidence <= 0.6
    assert len(client.calls) == 1


def test_prompt_redacts_otp_and_cache_corruption_recovers(raw, tmp_path):
    cache = tmp_path / "c"
    cache.write_text("not json")
    client = FakeClient([json.dumps([response(event="otp_email")])])
    email = raw("Your code is maple-river.", subject="Your OTP 918273", sender="n@example.com")
    list(BatchExtractor(client=client, cache_path=cache).extract([email]))
    request = str(client.calls)
    assert "918273" not in request
    assert "maple-river" not in request


def test_invalid_contact_phone_falls_back_without_caching(raw, tmp_path):
    client = FakeClient([json.dumps([response(contact_change={"kind": "phone", "new_last4": "918273"})])])
    cache = tmp_path / "c"
    event = next(
        BatchExtractor(client=client, cache_path=cache, attempts=1).extract([raw(sender="n@example.com")])
    )
    assert event.contact_change is None
    assert not cache.exists()
