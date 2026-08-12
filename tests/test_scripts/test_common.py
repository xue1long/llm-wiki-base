from scripts._common import log_message


def test_log_message_formats_and_appends(tmp_path, capsys, monkeypatch):
    report = tmp_path / "report.txt"
    monkeypatch.setattr("scripts._common.time.strftime", lambda fmt: "12:34:56")

    log_message("中文消息", report)

    assert capsys.readouterr().out == "[12:34:56] 中文消息\n"
    assert report.read_text(encoding="utf-8") == "[12:34:56] 中文消息\n"
