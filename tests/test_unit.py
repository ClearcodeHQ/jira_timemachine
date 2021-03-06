"""Tests not using external services."""

from datetime import date

import arrow
from mock import patch, call
import pytest

from jira_timemachine import Worklog, get_worklogs, format_time, match_worklog


def test_worklog_to_tempo():
    """Test representing a worklog as a Tempo dict."""
    assert Worklog(
        id=123,
        tempo_id=456,
        started=arrow.get('2018-11-16T15:12:13Z'),
        time_spent_seconds=900,
        description=u'Invent test data',
        author=u'q.atester',
        issue=u'X-11',
        ).to_tempo() == {
            'attributes': [],
            'authorAccountId': u'q.atester',
            'description': u'Invent test data',
            'issueKey': u'X-11',
            'startDate': u'2018-11-16',
            'startTime': u'15:12:13',
            'timeSpentSeconds': 900,
        }


@pytest.mark.parametrize('all_users, single_user', (
    (False, True),
    (True, False),
))
def test_get_worklogs(all_users, single_user):
    """Test that get_worklogs performs proper calls and filters worklogs by date."""
    old_sample_worklogs = [
        Worklog(id=1, tempo_id=2, started=arrow.get('2018-11-10'), time_spent_seconds=1, description=u'', author=u'', issue=u''),
        Worklog(id=1, tempo_id=2, started=arrow.get('2018-11-11'), time_spent_seconds=1, description=u'', author=u'', issue=u''),
    ]
    recent_sample_worklogs = [
        Worklog(id=1, tempo_id=2, started=arrow.get('2018-11-16'), time_spent_seconds=1, description=u'', author=u'', issue=u''),
        Worklog(id=1, tempo_id=2, started=arrow.get('2018-11-17'), time_spent_seconds=1, description=u'', author=u'', issue=u''),
    ]
    config = {'magic': True, 'login': 'the.user'}
    with patch('jira_timemachine.get_client') as mock_get_client:
        mock_get_client.return_value.get_worklogs.return_value = iter(old_sample_worklogs + recent_sample_worklogs)
        assert list(get_worklogs(config, arrow.get('2018-11-16'), all_users)) == recent_sample_worklogs

    assert mock_get_client.mock_calls == [
        call(config),
        call().get_worklogs(from_date=date(2018, 11, 16), single_user=single_user),
    ]


@pytest.mark.parametrize('seconds, result', (
    (0, ''),  # this won't occur in a worklog
    (1, '1s'),
    (59, '59s'),
    (60, '1m'),
    (61, '1m 1s'),
    (3599, '59m 59s'),
    (3600, '1h'),
    (24 * 3600, '24h'),
    (24 * 3600 + 10, '24h 10s'),
    (24 * 3600 + 15 * 60, '24h 15m'),
    (24 * 3600 + 15 * 60 + 5, '24h 15m 5s'),
))
def test_format_time(seconds, result):
    """Test format_time on sample data."""
    assert format_time(seconds) == result


def test_match_worklog():
    """Test that match_worklog finds correct source worklogs."""
    def make(i, description):
        """Return a sample worklog instance."""
        return Worklog(id=i, tempo_id=None, started=arrow.get('2018-11-10'), time_spent_seconds=1,
                       description=description, author=u'', issue=u'')

    w123 = make(123, 'Anything')
    w124 = make(124, 'Else')
    source_worklogs = {
        123: w123,
        124: w124,
    }

    assert match_worklog(source_worklogs, make(125, 'Some original work')) is None
    assert match_worklog(source_worklogs, make(125, 'TIMEMACHINE_WID 122')) is None
    assert match_worklog(source_worklogs, make(125, 'TIMEMACHINE_WID 123')) is w123
    assert match_worklog(source_worklogs,
                         make(125, 'TIMEMACHINE_WID 124: X spent 1440s on Y-126 at 2018-11-16T12:34:01Z')) is w124
