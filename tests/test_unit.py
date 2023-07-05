"""Tests not using external services."""

from datetime import date
from io import StringIO
from unittest.mock import patch, call, Mock

import arrow
import click
import pytest
from pydantic import HttpUrl, parse_obj_as, TypeAdapter
from pydantic_core import Url

from jira_timemachine import Worklog, get_worklogs, format_time, match_worklog, SourceJiraConfig, get_config


def test_worklog_to_tempo():
    """Test representing a worklog as a Tempo dict."""
    assert Worklog(
        id=123,
        tempo_id=456,
        started=arrow.get("2018-11-16T15:12:13Z"),
        time_spent_seconds=900,
        description="Invent test data",
        author="q.atester",
        issue="X-11",
    ).to_tempo() == {
        "attributes": [],
        "authorAccountId": "q.atester",
        "description": "Invent test data",
        "issueKey": "X-11",
        "startDate": "2018-11-16",
        "startTime": "15:12:13",
        "timeSpentSeconds": 900,
    }


@pytest.mark.parametrize(
    "all_users, single_user",
    (
        (False, True),
        (True, False),
    ),
)
def test_get_worklogs(all_users, single_user):
    """Test that get_worklogs performs proper calls and filters worklogs by date."""
    url_adapter: TypeAdapter[HttpUrl] = TypeAdapter(HttpUrl)
    old_sample_worklogs = [
        Worklog(
            id=1, tempo_id=2, started=arrow.get("2018-11-10"), time_spent_seconds=1, description="", author="", issue=""
        ),
        Worklog(
            id=1,
            tempo_id=2,
            started=arrow.get("2018-11-11"),
            time_spent_seconds=1,
            description="",
            author="",
            issue="",
        ),
    ]
    recent_sample_worklogs = [
        Worklog(
            id=1,
            tempo_id=2,
            started=arrow.get("2018-11-16"),
            time_spent_seconds=1,
            description="",
            author="",
            issue="",
        ),
        Worklog(
            id=1,
            tempo_id=2,
            started=arrow.get("2018-11-17"),
            time_spent_seconds=1,
            description="",
            author="",
            issue="",
        ),
    ]
    config = SourceJiraConfig(
        url=url_adapter.validate_python("https://jira.invalid/"),
        email="user@domain.invalid",
        jira_token="magic",
        tempo_token="",
        project_key="",
    )
    with patch("jira_timemachine.get_client") as mock_get_client:
        mock_get_client.return_value.get_worklogs.return_value = iter(old_sample_worklogs + recent_sample_worklogs)
        assert list(get_worklogs(config, arrow.get("2018-11-16"), all_users)) == recent_sample_worklogs

    assert mock_get_client.mock_calls == [
        call(config),
        call().get_worklogs(from_date=date(2018, 11, 16), single_user=single_user),
    ]


@pytest.mark.parametrize(
    "seconds, result",
    (
        (0, ""),  # this won't occur in a worklog
        (1, "1s"),
        (59, "59s"),
        (60, "1m"),
        (61, "1m 1s"),
        (3599, "59m 59s"),
        (3600, "1h"),
        (24 * 3600, "24h"),
        (24 * 3600 + 10, "24h 10s"),
        (24 * 3600 + 15 * 60, "24h 15m"),
        (24 * 3600 + 15 * 60 + 5, "24h 15m 5s"),
    ),
)
def test_format_time(seconds, result):
    """Test format_time on sample data."""
    assert format_time(seconds) == result


def test_match_worklog():
    """Test that match_worklog finds correct source worklogs."""

    def make(i, description):
        """Return a sample worklog instance."""
        return Worklog(
            id=i,
            tempo_id=None,
            started=arrow.get("2018-11-10"),
            time_spent_seconds=1,
            description=description,
            author="",
            issue="",
        )

    w123 = make(123, "Anything")
    w124 = make(124, "Else")
    source_worklogs = {
        123: w123,
        124: w124,
    }

    assert match_worklog(source_worklogs, make(125, "Some original work")) is None
    assert match_worklog(source_worklogs, make(125, "TIMEMACHINE_WID 122")) is None
    assert match_worklog(source_worklogs, make(125, "TIMEMACHINE_WID 123")) is w123
    assert (
        match_worklog(source_worklogs, make(125, "TIMEMACHINE_WID 124: X spent 1440s on Y-126 at 2018-11-16T12:34:01Z"))
        is w124
    )


def test_get_config_ok():
    """Test that a valid config is parsed."""
    config_file = StringIO(
        """{
  "source_jira": {
    "url": "https://source.atlassian.net",
    "email": "login@login.com",
    "jira_token": "a",
    "project_key": "JIRA",
    "tempo_token": "b"
  },
  "destination_jira": {
    "url": "https://destination.atlassian.net",
    "email": "login@login.com",
    "jira_token": "c",
    "issue": "ARIJ-3",
    "tempo_token": "d"
  },
  "issue_map": {
    "JIRA-101": "ARIJ-1",
    "JIRA-102": "ARIJ-2"
  }
}"""
    )
    config = get_config(Mock(), Mock(), config_file)
    assert config.source_jira.url == Url("https://source.atlassian.net")
    assert config.source_jira.email == "login@login.com"
    assert config.source_jira.jira_token == "a"
    assert config.source_jira.project_key == "JIRA"
    assert config.source_jira.tempo_token == "b"
    assert config.destination_jira.url == Url("https://destination.atlassian.net")
    assert config.destination_jira.email == "login@login.com"
    assert config.destination_jira.jira_token == "c"
    assert config.destination_jira.issue == "ARIJ-3"
    assert config.destination_jira.tempo_token == "d"
    assert config.issue_map == {"JIRA-101": "ARIJ-1", "JIRA-102": "ARIJ-2"}


def test_get_config_invalid():
    """Test that we get a proper exception on an invalid config."""
    config_file = StringIO(
        """{
  "source_jira": {
    "url": "https://source.atlassian.net",
    "email": "login@login.com",
    "project_key": "JIRA",
    "tempo_token": "b"
  },
  "destination_jira": {
    "url": "https://destination.atlassian.net",
    "email": "login@login.com",
    "jira_token": "c",
    "issue": "ARIJ-3",
    "tempo_token": "d"
  },
  "issue_map": {
    "JIRA-101": "ARIJ-1",
    "JIRA-102": "ARIJ-2"
  }
}"""
    )
    with pytest.raises(click.BadParameter) as exc_info:
        get_config(Mock(), Mock(), config_file)

    assert exc_info.value.message == ("1 validation error for Config\n" "source_jira.jira_token - Field required\n")
