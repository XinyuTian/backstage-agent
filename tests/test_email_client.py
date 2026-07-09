from datetime import datetime, timedelta, timezone

from backstage_agent.email_client import (
    _is_in_requested_window,
    _search_query_for_date,
    _subject_matches,
)


def test_search_query_adds_since_date():
    cutoff = datetime(2026, 7, 5, tzinfo=timezone.utc)

    query = _search_query_for_date('(FROM "backstage")', None, None, cutoff, ["basic filter"])

    assert query == '(FROM "backstage" SUBJECT "basic filter" SINCE "05-Jul-2026")'


def test_search_query_for_target_date_adds_before_date():
    start = datetime(2026, 7, 5, tzinfo=timezone.utc)
    end = datetime(2026, 7, 6, tzinfo=timezone.utc)
    cutoff = datetime(2026, 7, 1, tzinfo=timezone.utc)

    query = _search_query_for_date('(FROM "backstage")', start, end, cutoff, ["basic filter"])

    assert query == (
        '(FROM "backstage" SUBJECT "basic filter" SINCE "05-Jul-2026" BEFORE "06-Jul-2026")'
    )


def test_is_in_requested_window_filters_old_messages():
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)

    assert _is_in_requested_window(datetime.now(timezone.utc), cutoff, None, None)
    assert not _is_in_requested_window(
        datetime.now(timezone.utc) - timedelta(days=2),
        cutoff,
        None,
        None,
    )


def test_is_in_requested_window_filters_to_target_day():
    cutoff = datetime(2026, 7, 1, tzinfo=timezone.utc)
    start = datetime(2026, 7, 5, tzinfo=timezone.utc)
    end = datetime(2026, 7, 6, tzinfo=timezone.utc)

    assert _is_in_requested_window(datetime(2026, 7, 5, 12, tzinfo=timezone.utc), cutoff, start, end)
    assert not _is_in_requested_window(
        datetime(2026, 7, 6, tzinfo=timezone.utc),
        cutoff,
        start,
        end,
    )


def test_subject_matches_all_keywords_case_insensitive():
    assert _subject_matches("1 New Roles Available for basic filter - Jul 5", ["basic filter"])
    assert not _subject_matches("Saved applications reminder", ["basic filter"])
