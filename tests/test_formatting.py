from split_tracker.formatting import format_distance, format_duration, format_pace, parse_distance_to_meters, parse_time_to_seconds


def test_format_duration():
    assert format_duration(None) == "—"
    assert format_duration(65.432) == "1:05.43"
    assert format_duration(3661.2) == "1:01:01.20"
    assert format_duration(-3.2) == "-0:03.20"


def test_format_pace():
    assert format_pace(None) == "—"
    assert format_pace(330.0) == "5:30.00/mi"


def test_parse_time_to_seconds_and_malformed_targets():
    assert parse_time_to_seconds(330) == 330.0
    assert parse_time_to_seconds("5:30") == 330.0
    assert parse_time_to_seconds("1:02:03") == 3723.0
    assert parse_time_to_seconds("") is None
    assert parse_time_to_seconds("not a time") is None


def test_parse_and_format_distance():
    assert parse_distance_to_meters("5K") == 5000.0
    assert parse_distance_to_meters("0.5 mile") == 804.672
    assert parse_distance_to_meters("400 m") == 400.0
    assert format_distance(5000.0) == "5K"
