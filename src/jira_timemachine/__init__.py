# -*- coding: utf-8 -*-

# Copyright (c) 2016 by jira_timemachine authors and contributors <see AUTHORS file>
#
# This module is part of jira_timemachine and is released under
# the MIT License (MIT): http://opensource.org/licenses/MIT

"""Module for synchronization of Jira worklogs between different instances."""

import copy
import re
import json
from datetime import date, timedelta
import time
from typing import Iterator, Dict, List, IO, TypeVar, Callable, Optional

import attr
import click
import arrow
from jira import JIRA
import jira
import requests

__version__ = '0.0.0'


TEMPO_EPOCH = arrow.Arrow(2017, 6, 9)
"""
The date since which worklogs are available in Tempo only.

Older ones are both in Tempo and JIRA REST API, while they have different IDs, so we must use one source for them only.
"""


@attr.s
class Worklog(object):
    """JIRA or Tempo worklog."""

    id = attr.ib(type=int)
    """
    JIRA worklog ID.

    Each Tempo worklog has separate Jira and Tempo worklog IDs. We use Jira IDs so worklogs can be idempotently synced
    if a Jira instance adds/removes Tempo.
    """
    tempo_id = attr.ib(type=Optional[int])
    """Tempo worklog ID or None for plain Jira worklogs."""
    started = attr.ib(type=arrow.Arrow)
    time_spent_seconds = attr.ib(type=int)
    description = attr.ib(type=unicode)
    author = attr.ib(type=unicode)
    issue = attr.ib(type=unicode)

    @classmethod
    def from_tempo(cls, worklog):
        # type: (dict) -> Worklog
        """Return a worklog from Tempo API response."""
        return cls(
            id=int(worklog['jiraWorklogId']),
            tempo_id=int(worklog['tempoWorklogId']),
            author=worklog['author']['username'],
            started=arrow.get('{startDate} {startTime}'.format(**worklog)),
            time_spent_seconds=int(worklog['timeSpentSeconds']),
            issue=worklog['issue']['key'],
            description=worklog['description'],
        )

    @classmethod
    def from_jira(cls, worklog):
        # type: (jira.Worklog) -> Worklog
        """Return a worklog from JIRA API response."""
        return cls(
            id=worklog.id,
            tempo_id=None,
            author=worklog.author.username,
            time_spent_seconds=worklog.timeSpentSeconds,
            issue=worklog.issue.key,
            started=arrow.get(worklog.started),
            description=worklog.comment,
        )

    def to_tempo(self):
        # type: () -> dict
        """Return self as dict for use in Tempo API."""
        return {
            'attributes': [],
            'authorUsername': self.author,
            'description': self.description,
            'issueKey': self.issue,
            'startDate': self.started.format('YYYY-MM-DD'),
            'startTime': self.started.format('HH:mm:ss'),
            'timeSpentSeconds': self.time_spent_seconds,
        }


def issues(jira_instance, query):
    # type: (JIRA, str) -> Iterator[jira.Issue]
    """Issues iterator"""
    issue_index = 1
    while True:
        search_results = jira_instance.search_issues(jql_str=query, startAt=issue_index, maxResults=50)
        for issue in search_results:
            yield issue
        issue_index += 51
        if len(search_results) < 50:
            return


class TempoClient(object):
    """
    A client for Tempo Cloud APIs.

    See <https://tempo-io.github.io/tempo-api-docs/> for the API documentation.
    """

    def __init__(self, tempo_token):
        # type: (str) -> None
        """Prepare session for Tempo API requests."""
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': 'Bearer %s' % tempo_token
        })

    def get_worklogs(self, from_date, username):
        # type: (date, str) -> Iterator[Worklog]
        """
        Return all recent worklogs for the specified user.

        :rtype: list
        :returns: list of dicts representing worklogs
        """
        url = 'https://api.tempo.io/2/worklogs/user/%s?from=%s&to=%s' % (username, from_date, date.today())
        while url:
            res = self.session.get(
                url,
                allow_redirects=False,
            )
            try:
                res.raise_for_status()
            except:
                click.echo(res.content)
                raise
            response_data = res.json()
            for row in response_data['results']:
                yield Worklog.from_tempo(row)
            url = response_data['metadata'].get('next')

    def update_worklog(self, worklog):
        # type: (Worklog) -> None
        """
        Update the specified worklog.

        :param Worklog worklog: updated worklog data
        """
        if worklog.tempo_id is None:
            raise ValueError('The worklog to update must have a Tempo ID')
        res = self.session.put(
            'https://api.tempo.io/2/worklogs/%d' % worklog.tempo_id,
            data=json.dumps(worklog.to_tempo())
        )
        try:
            res.raise_for_status()
        except:
            click.echo(res.content)
            raise

    def post_worklog(self, worklog):
        # type: (Worklog) -> None
        """
        Upload a new worklog.

        :param dict worklog: new worklog data
        """
        res = self.session.post(
            'https://api.tempo.io/2/worklogs',
            data=json.dumps(worklog.to_tempo())
        )
        try:
            res.raise_for_status()
        except:
            click.echo(res.content)
            raise


@click.command()
@click.option('--config', help="Config path", type=click.File())
@click.option('--days', help="How many days back to look", default=1)
def timemachine(config, days):
    # type: (IO[str], int) -> None
    """Copy worklogs from source Jira issues to the destination Jira issue."""
    config_dict = json.load(config)
    utcnow = arrow.utcnow()

    # Regexp to detect the automatic worklog in Destination JIRA.
    auto_worklog = re.compile(r'TIMEMACHINE_WID (?P<id>\d+).*')
    # Automatic worklog message.
    worklog_msg = u"TIMEMACHINE_WID {0.id}: {0.author} spent {0.time_spent_seconds}s on {0.issue} at {0.started}"
    # JQL Query based to list all issues to read worklogs from.
    issue_jql = "project = {project_key} AND updated >= -{0}d ORDER BY key ASC"

    source_worklogs = {}  # type: Dict[int, Worklog]
    source_url = config_dict['source_jira']['url']
    source_tempo = TempoClient(config_dict['source_jira']['tempo_token'])
    destination_tempo = TempoClient(config_dict['destination_jira']['tempo_token'])

    if utcnow - timedelta(days=days) < TEMPO_EPOCH:
        source_jira = JIRA(
            source_url,
            basic_auth=(config_dict['source_jira']['login'], config_dict['source_jira']['jira_token'])
        )
        for issue in issues(source_jira, issue_jql.format(days, project_key=config_dict['source_jira']['project_key'])):
            for jira_worklog in source_jira.worklogs(issue):
                worklog = Worklog.from_jira(jira_worklog)
                if not worklog.author == config_dict['source_jira']['login']:
                    # click.echo(u'Skip, worklog author not in map {0}'.format(worklog.author))
                    continue
                if arrow.get(worklog.started) < utcnow - timedelta(days=days):
                    click.echo('Skip, update too long ago {0}'.format(worklog.started))
                    continue
                source_worklogs[int(worklog.id)] = worklog

    for worklog in source_tempo.get_worklogs(
            from_date=(utcnow - timedelta(days=days)).date(),
            username=config_dict['source_jira']['login'],
    ):
        if worklog.author != config_dict['source_jira']['login']:
            continue
        start = worklog.started
        if start < utcnow - timedelta(days=days):
            click.echo('Skip, update too long ago {0}'.format(start))
            continue
        if start < TEMPO_EPOCH:
            click.echo('Skip, update before Tempo epoch {0}'.format(start))
            continue
        source_worklogs[worklog.id] = worklog

    # Query all recent user's worklogs and then filter by task. It should be faster than querying by issue and
    # filtering by user if several users sync worklogs to the same issue and the user doesn't have too many worklogs in
    # other issues (e.g. logging time to the destination Jira mostly via the timemachine).
    for ccworklog in destination_tempo.get_worklogs(
            from_date=(utcnow - timedelta(days=days)).date(),
            username=config_dict['destination_jira']['login'],
    ):
        if ccworklog.issue != config_dict['destination_jira']['issue']:
            continue
        match = auto_worklog.match(ccworklog.description)
        if not match:
            continue
        worklog_id = int(match.groupdict()['id'])
        try:
            source_worklog = source_worklogs[worklog_id]
        except KeyError:
            # might be some old worklog
            continue
        del source_worklogs[worklog_id]
        comment = worklog_msg.format(source_worklog)
        if ccworklog.description == comment:
            click.echo(u"Nothing changed for {0}".format(ccworklog.description))
            continue
        click.echo(u"Updating worklog {0} to {1}".format(ccworklog.description, comment))
        ccworklog.description = worklog_msg.format(source_worklog)
        ccworklog.started = source_worklog.started
        ccworklog.time_spent_seconds = source_worklog.time_spent_seconds
        destination_tempo.update_worklog(ccworklog)

    click.echo("Writing {0} worklogs to Destination JIRA".format(len(source_worklogs)))

    with click.progressbar(source_worklogs.values(), label="Writing worklog") as worklogs:

        for source_worklog in worklogs:
            source_worklog.issue = config_dict['destination_jira']['issue']
            source_worklog.description = worklog_msg.format(source_worklog)
            source_worklog.author = config_dict['destination_jira']['login']
            destination_tempo.post_worklog(source_worklog)
