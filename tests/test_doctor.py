import pytest

from scripts.doctor import configured, has_placeholder, mask, parse_env


@pytest.mark.parametrize("value", ["+91XXXX123456", "you.demo@example.com", "CHANGEME", "<api-key>"])
def test_detects_placeholders(value):
    assert has_placeholder(value)


@pytest.mark.parametrize("value", ["", "deepseek-v4.1-flash-free", "actual@example.org", "0123456789"])
def test_accepts_non_placeholder_values(value):
    assert not has_placeholder(value)


def test_mask_does_not_reveal_even_short_secrets():
    assert mask("") == "<unset>"
    assert mask("a") == "<set, 1 chars>"
    assert mask("example-password") == "<set, 16 chars>"


def test_env_quoting_comments_empty_values_and_duplicate_keys():
    text = """# comment
export TOKEN="hello # world"
EMPTY=
BARE
NAME=first
NAME='second value' # comment
MODEL=some-model # comment
"""
    assert parse_env(text) == {
        "TOKEN": "hello # world",
        "EMPTY": "",
        "BARE": "",
        "NAME": "second value",
        "MODEL": "some-model",
    }


def test_env_does_not_expand_environment(monkeypatch):
    monkeypatch.setenv("DOCTOR_TEST_SECRET", "must-not-expand")
    assert parse_env("TOKEN=${DOCTOR_TEST_SECRET}") == {"TOKEN": "${DOCTOR_TEST_SECRET}"}


def test_env_malformed_secret_is_not_in_error(capsys):
    with pytest.raises(ValueError, match="^Invalid dotenv syntax$"):
        parse_env('TOKEN="secret-without-closing-quote')
    assert capsys.readouterr() == ("", "")


def test_required_config_rejects_missing_blank_and_placeholder():
    assert not configured({}, "TOKEN")
    assert not configured({"TOKEN": "  "}, "TOKEN")
    assert not configured({"TOKEN": "XXXX"}, "TOKEN")
    assert configured({"TOKEN": "real-value"}, "TOKEN")
