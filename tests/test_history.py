"""Past sessions: the history picture, deleting one, and the time a level comes up."""
from datetime import datetime

from maple_tracker import config, fmt, history
from maple_tracker.share import summary_card

from test_share import RECORD


def test_level_up_clock_time():
    now = datetime(2026, 10, 20, 20, 0).timestamp()
    assert fmt.at(105 * 60, now) == "21:45"
    assert fmt.at(14 * 3600, now) == "Wed 10:00"            # tomorrow: with the day
    assert fmt.at(3 * 24 * 3600, now) == "" and fmt.at(None, now) == ""


def test_history_picture_newest_first_and_best_runs():
    old = dict(RECORD, started="2026-10-17T20:00:00", exp_per_hour=90_000.0)
    blip = dict(RECORD, started="2026-10-19T20:00:00", active_seconds=60, exp_per_hour=9_000_000.0)
    img, rows = history.render([old, RECORD, blip])
    assert [r["started"] for _, _, r in rows] == [blip["started"], RECORD["started"], old["started"]]
    assert all(y1 - y0 == history.ROW for y0, y1, _ in rows)
    assert history.best([old, RECORD, blip], "exp_per_hour") is RECORD   # a 1-minute blip doesn't count
    assert img.width == history.W * 2
    _, rows = history.render([])
    assert rows == []


def test_delete_from_history(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(config, "HISTORY", tmp_path / "sessions.jsonl")
    other = dict(RECORD, started="2026-10-19T20:00:00")
    for r in (RECORD, other):
        config.append_history(r)
    config.delete_history(RECORD)
    assert config.load_history() == [other]


def test_summary_picture_with_levels_and_without_mesos():
    plain = summary_card(RECORD)
    levels = summary_card(dict(RECORD, level_start=37, level_end=38))
    no_mesos = summary_card(dict(RECORD, mesos_start=None))
    assert plain.width == levels.width == no_mesos.width
    assert no_mesos.height < plain.height
