import gzip
import io
import json
from argparse import Namespace

from azure_region_monitor import cli


class _FakeResponse:
    def __init__(self, payload, content_encoding=None):
        self._payload = payload
        self.headers = {}
        if content_encoding:
            self.headers["Content-Encoding"] = content_encoding

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_fetch_url_text_plain(monkeypatch):
    def fake_urlopen(request, timeout=60):
        return _FakeResponse(b'{"ok": true}')

    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    assert cli._fetch_url_text("https://example/api.json") == '{"ok": true}'


def test_fetch_url_text_gzip(monkeypatch):
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb") as stream:
        stream.write(b'{"gz": 1}')
    compressed = buffer.getvalue()

    def fake_urlopen(request, timeout=60):
        return _FakeResponse(compressed, content_encoding="gzip")

    monkeypatch.setattr(cli.urllib.request, "urlopen", fake_urlopen)
    assert cli._fetch_url_text("https://example/api.json") == '{"gz": 1}'


def test_fetch_url_text_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky_urlopen(request, timeout=60):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("boom")
        return _FakeResponse(b'{"ok": 1}')

    monkeypatch.setattr(cli.urllib.request, "urlopen", flaky_urlopen)
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)
    assert cli._fetch_url_text("https://example/api.json") == '{"ok": 1}'
    assert calls["n"] == 3


def test_fetch_url_text_raises_after_exhausting_retries(monkeypatch):
    def always_fail(request, timeout=60):
        raise OSError("down")

    monkeypatch.setattr(cli.urllib.request, "urlopen", always_fail)
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)
    try:
        cli._fetch_url_text("https://example/api.json", attempts=3)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as error:
        assert "after 3 attempts" in str(error)


def test_social_drafts_cli_reads_history_index(tmp_path, capsys):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "index.json").write_text(
        json.dumps(
            {
                "days": [
                    {
                        "date": "2026-07-08",
                        "narrative": "A useful rollout\n\nTwo monitored regions gained a signal.",
                        "narrative_source": "ai",
                        "change_type_counts": {"new_availability": 2, "regression": 0},
                        "parked_unknown_changes": 0,
                        "highlights": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    cli._social_drafts(Namespace(history=history_dir, site_url="https://example.test", limit=1))

    output = capsys.readouterr().out
    assert "## Social post drafts" in output
    assert "#### LinkedIn draft" in output
    assert "https://example.test/blog/2026-07-08.html" in output
