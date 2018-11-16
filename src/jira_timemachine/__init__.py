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

        :rtype: iterator
        :returns: yields Worklog instances
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
                if row['author']['username'] != username:
                    continue
                yield Worklog(
                    id=int(row['jiraWorklogId']),
                    tempo_id=int(row['tempoWorklogId']),
                    author=row['author']['username'],
                    started=arrow.get('{startDate} {startTime}'.format(**row)),
                    time_spent_seconds=int(row['timeSpentSeconds']),
                    issue=row['issue']['key'],
                    description=row['description'],
                )
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


class JIRAClient(object):
    """A client for JIRA API."""

    _ISSUE_JQL = 'project = {project_key} AND updated >= "{0}" ORDER BY key ASC'
    """JQL query format for listing all issues with worklogs to read."""

    def __init__(self, config):
        # type: (dict) -> None
        """Initialize with credentials from the *config* dict."""
        self._login = config['login']
        self._jira = JIRA(
            config['url'],
            basic_auth=(config['email'], config['jira_token'])
        )
        user = self._jira.current_user()
        if self._login != user:
            raise click.ClickException('Logged in as {} but {} specified in config'.format(user, self._login))
        self._project_key = config['project_key']


    def _issues(self, query):
        # type: (str) -> Iterator[jira.Issue]
        """Issues iterator."""
        issue_index = 1
        while True:
            search_results = self._jira.search_issues(jql_str=query, startAt=issue_index, maxResults=50)
            for issue in search_results:
                yield issue
            issue_index += 51
            if len(search_results) < 50:
                return

    def get_worklogs(self, from_date, username):
        # type: (date, str) -> Iterator[Worklog]
        """
        Return all recent worklogs for the specified user.

        :rtype: iterator
        :returns: yields Worklog instances
        """
        for issue in self._issues(self._ISSUE_JQL.format(from_date, project_key=self._project_key)):
            for jira_worklog in self._jira.worklogs(issue):
                worklog = Worklog(
                    id=int(jira_worklog.id),
                    tempo_id=None,
                    author=jira_worklog.author.name,
                    time_spent_seconds=int(jira_worklog.timeSpentSeconds),
                    issue=issue.key,
                    started=arrow.get(jira_worklog.started),
                    description=getattr(jira_worklog, 'comment', u''),
                )
                if not worklog.author == username:
                    continue
                yield worklog


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

    source_worklogs = {}  # type: Dict[int, Worklog]
    destination_tempo = TempoClient(config_dict['destination_jira']['tempo_token'])

    if 'tempo_token' in config_dict['source_jira']:
        # Get worklogs from Tempo.
        source_tempo = TempoClient(config_dict['source_jira']['tempo_token'])
        for worklog in source_tempo.get_worklogs(
                from_date=(utcnow - timedelta(days=days)).date(),
                username=config_dict['source_jira']['login'],
        ):
            start = worklog.started
            if start < utcnow - timedelta(days=days):
                click.echo('Skip, update too long ago {0}'.format(start))
                continue
            source_worklogs[worklog.id] = worklog
    else:
        # Get worklogs from JIRA.
        source_jira = JIRAClient(config_dict['source_jira'])
        for worklog in source_jira.get_worklogs(
                from_date=(utcnow - timedelta(days=days)).date(),
                username=config_dict['source_jira']['login'],
        ):
            if arrow.get(worklog.started) < utcnow - timedelta(days=days):
                click.echo('Skip, update too long ago {0}'.format(worklog.started))
                continue
            source_worklogs[int(worklog.id)] = worklog

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
