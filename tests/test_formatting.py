from split_tracker.formatting import format_duration, format_pace, parse_pace_to_seconds


def test_format_duration():
    assert format_duration(None) == "—"
    assert format_duration(65.432) == "1:05.43"
    assert format_duration(3661.2) == "1:01:01.20"
    assert format_duration(-3.2) == "-0:03.20"


def test_format_pace():
    assert format_pace(None) == "—"
    assert format_pace(330.0) == "5:30.00/mi"


def test_parse_pace_to_seconds():
    assert parse_pace_to_seconds(330) == 330.0
    assert parse_pace_to_seconds("5:30") == 330.0
    assert parse_pace_to_seconds("1:02:03") == 3723.0
    assert parse_pace_to_seconds("") is None
    assert parse_pace_to_seconds("not a pace") is None
