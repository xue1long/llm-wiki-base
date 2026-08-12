import builtins

from scripts._common import log_message


def test_log_message_formats_appends_and_flushes(tmp_path, monkeypatch):
    report = tmp_path / "report.txt"
    monkeypatch.setattr("scripts._common.time.strftime", lambda fmt: "12:34:56")
    printed = []

    def fake_print(*args, **kwargs):
        printed.append((args, kwargs))

    monkeypatch.setattr(builtins, "print", fake_print)

    log_message("中文消息", report)
    log_message("second", report)

    assert printed == [
        (("[12:34:56] 中文消息",), {"flush": True}),
        (("[12:34:56] second",), {"flush": True}),
    ]
    assert report.read_text(encoding="utf-8") == "[12:34:56] 中文消息\n[12:34:56] second\n"
