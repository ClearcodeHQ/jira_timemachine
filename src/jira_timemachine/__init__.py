# -*- coding: utf-8 -*-

# Copyright (c) 2016 by jira_timemachine authors and contributors <see AUTHORS file>
#
# This module is part of jira_timemachine and is released under
# the MIT License (MIT): http://opensource.org/licenses/MIT

"""Module for synchronization of Jira worklogs between different instances."""

import copy
import re
import itertools
import json
from datetime import date, timedelta
import time
from typing import Iterator, Dict, List, IO, TypeVar, Callable, Optional, Tuple, Union, Text

import attr
import click
from click import ClickException
import arrow
from jira import JIRA
import jira
import requests
from requests import HTTPError

__version__ = '0.0.0'


@attr.s  # pylint:disable=too-few-public-methods
class Worklog(object):
    """JIRA or Tempo worklog."""

    id = attr.ib(type=int)  # pylint:disable=invalid-name
    """
    JIRA worklog ID.

    Each Tempo worklog has separate Jira and Tempo worklog IDs. We use Jira IDs so worklogs can be idempotently synced
    if a Jira instance adds/removes Tempo.
    """
    tempo_id = attr.ib(type=Optional[int])
    """Tempo worklog ID or None for plain Jira worklogs."""
    started = attr.ib(type=arrow.Arrow)
    time_spent_seconds = attr.ib(type=int)
    description = attr.ib(type=Text)
    author = attr.ib(type=Text)
    issue = attr.ib(type=Text)

    def to_tempo(self):
        # type: () -> dict
        """Return self as dict for use in Tempo API."""
        return {
            'attributes': [],
            'authorAccountId': self.author,
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

    def __init__(self, tempo_token, account_id):
        # type: (str, str) -> None
        """Prepare session for Tempo API requests."""
        self.account_id = account_id
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': 'Bearer %s' % tempo_token
        })

    def get_worklogs(self, from_date, single_user=True):
        # type: (date, bool) -> Iterator[Worklog]
        """
        Return all recent worklogs for the specified user.

        :rtype: iterator
        :returns: yields Worklog instances
        """
        if single_user:
            url = 'https://api.tempo.io/core/3/worklogs/user/%s?from=%s&to=%s' % (
                self.account_id, from_date, date.today())
        else:
            url = 'https://api.tempo.io/core/3/worklogs?from=%s&to=%s' % (from_date, date.today())
        while url:
            res = self.session.get(
                url,
                allow_redirects=False,
            )
            try:
                res.raise_for_status()
            except Exception:
                click.echo(res.content)
                raise
            response_data = res.json()
            for row in response_data['results']:
                if single_user and row['author']['accountId'] != self.account_id:
                    continue
                try:
                    yield Worklog(
                        id=int(row['jiraWorklogId']),
                        tempo_id=int(row['tempoWorklogId']),
                        author=row['author']['accountId'],
                        started=arrow.get('{startDate} {startTime}'.format(**row)),
                        time_spent_seconds=int(row['timeSpentSeconds']),
                        issue=row['issue']['key'],
                        description=row['description'],
                    )
                except TypeError as exc:
                    msg = f'Encountered an error {exc} while processing a worklog entry {row}'
                    click.echo(msg, err=True)
                    continue

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
            b'https://api.tempo.io/core/3/worklogs/%d' % worklog.tempo_id,
            json=worklog.to_tempo()
        )
        try:
            res.raise_for_status()
        except Exception:
            click.echo(res.content)
            raise

    def post_worklog(self, worklog):
        # type: (Worklog) -> None
        """
        Upload a new worklog.

        :param dict worklog: new worklog data
        """
        res = self.session.post(
            b'https://api.tempo.io/core/3/worklogs',
            json=worklog.to_tempo()
        )
        try:
            res.raise_for_status()
        except HTTPError:
            click.echo(res.content)


class JIRAClient(object):  # pylint:disable=too-few-public-methods
    """A client for JIRA API."""

    _ISSUE_JQL = 'project = {project_key} AND updated >= "{0}" ORDER BY key ASC'
    """JQL query format for listing all issues with worklogs to read."""

    def __init__(self, config):
        # type: (dict) -> None
        """Initialize with credentials from the *config* dict."""
        self._jira = JIRA(
            config['url'],
            basic_auth=(config['email'], config['jira_token'])
        )
        self._project_key = config.get('project_key')
        self.account_id = self._jira.myself()['accountId']  # type: str

    def _issues(self, query):
        # type: (str) -> Iterator[jira.Issue]
        """Issues iterator."""
        issue_index = 1
        max_results = 50
        while True:
            search_results = self._jira.search_issues(jql_str=query, startAt=issue_index, maxResults=max_results)
            for issue in search_results:
                yield issue
            issue_index += max_results
            if len(search_results) < max_results:
                return

    def get_worklogs(self, from_date, single_user=True):
        # type: (date, bool) -> Iterator[Worklog]
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
                    author=jira_worklog.author.accountId,
                    time_spent_seconds=int(jira_worklog.timeSpentSeconds),
                    issue=issue.key,
                    started=arrow.get(jira_worklog.started),
                    description=getattr(jira_worklog, 'comment', u''),
                )
                if single_user and worklog.author != self.account_id:
                    continue
                yield worklog


def get_tempo_client(config):
    # type: (dict) -> TempoClient
    """Return a Tempo client for the source of worklogs specified in *config*."""
    jira_client = JIRAClient(config)
    return TempoClient(config['tempo_token'], jira_client.account_id)


def get_client(config):
    # type: (dict) -> Union[TempoClient, JIRAClient]
    """Return a client for the source of worklogs specified in *config*."""
    if 'tempo_token' in config and config['tempo_token']:
        return get_tempo_client(config)
    return JIRAClient(config)


def get_worklogs(config, since, all_users=False):
    # type: (dict, arrow.Arrow, bool) -> Iterator[Worklog]
    """
    Yield user's recent worklogs.

    :param dict config: JIRA configuration
    :param arrow.Arrow since: earliest start time of yielded worklogs
    :param bool all_users: if True, yield also worklogs from other users if available
    """
    for worklog in get_client(config).get_worklogs(
            from_date=since.date(),
            single_user=not all_users,
    ):
        if worklog.started < since:
            click.echo('Skip, update too long ago {0}'.format(worklog.started))
            continue
        yield worklog


def format_time(seconds):
    # type: (int) -> str
    """
    Return *seconds* in a human-readable format (e.g. 25h 15m 45s).

    Unlike `timedelta`, we don't aggregate it into days: it's not useful when reporting logged work hours.
    """
    out = []
    if seconds > 3599:
        out.append('%sh' % (seconds // 3600))
        seconds = seconds % 3600
    if seconds > 59:
        out.append('%sm' % (seconds // 60))
        seconds = seconds % 60
    if seconds > 0:
        out.append('%ss' % seconds)
    return ' '.join(out)


AUTO_WORKLOG = re.compile(r'TIMEMACHINE_WID (?P<id>\d+).*')
"""Regexp to detect the automatic worklog in Destination JIRA."""


def match_worklog(source_worklogs, worklog):
    # type: (Dict[int, Worklog], Worklog) -> Optional[Worklog]
    """
    Return a matching source worklog for the given destination worklog.

    :param dict source_worklogs: a mapping from source JIRA worklog ID to `Worklog` instance
    :param Worklog worklog: destination JIRA worklog

    :rtype: Worklog
    :returns: a worklog from *source_worklogs* that was previously copied into the destination JIRA as *worklog*, or
        None if *worklog* has no corresponding source worklo
    """
    match = AUTO_WORKLOG.match(worklog.description)
    if not match:
        return None
    worklog_id = int(match.groupdict()['id'])
    try:
        return source_worklogs[worklog_id]
    except KeyError:
        # might be some old worklog
        return None


@click.command()
@click.option('--config', help="Config path", type=click.File())
@click.option('--days', help="How many days back to look", default=1)
def timemachine(config, days):
    # type: (IO[str], int) -> None
    """Copy worklogs from source Jira issues to the destination Jira issue."""
    config_dict = json.load(config)
    utcnow = arrow.utcnow()

    # Automatic worklog message.
    worklog_msg = u"TIMEMACHINE_WID {0.id}: {0.author} spent {0.time_spent_seconds}s on {0.issue} at {0.started}"

    source_worklogs = {
        worklog.id: worklog
        for worklog in get_worklogs(config_dict['source_jira'], utcnow - timedelta(days=days))}

    # How mapping to multiple destination JIRA works: we have a default issue (config_dict['destination_jira']) and a
    # mapping from source JIRA issue to a destination JIRA issue (config_dict['issue_map']) overriding it for specific
    # issues. If a worklog is already copied into any of these issues, it might get updated there. New worklogs are
    # created as specified in the mapping. No worklogs are moved or deleted.
    dest_issues = {config_dict['destination_jira']['issue']} | set(config_dict.get('issue_map', {}).values())

    # Query all recent user's worklogs and then filter by task. It should be faster than querying by issue and
    # filtering by user if several users sync worklogs to the same issue and the user doesn't have too many worklogs in
    # other issues (e.g. logging time to the destination Jira mostly via the timemachine).
    destination_tempo = get_tempo_client(config_dict['destination_jira'])
    for ccworklog in destination_tempo.get_worklogs(
            from_date=(utcnow - timedelta(days=days)).date(),
    ):
        if ccworklog.issue not in dest_issues:
            continue
        source_worklog = match_worklog(source_worklogs, ccworklog)
        if source_worklog is None:
            continue
        del source_worklogs[source_worklog.id]
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
            source_worklog.description = worklog_msg.format(source_worklog)
            source_worklog.issue = config_dict.get('issue_map', {}).get(
                source_worklog.issue, config_dict['destination_jira']['issue'])
            source_worklog.author = destination_tempo.account_id
            destination_tempo.post_worklog(source_worklog)


@click.command()
@click.option('--config', help='Config path', type=click.File())
@click.option(
    '--since', help='Date from which to start listing (defaults to the start of the current month)', default='')
@click.option('--pm', 'is_pm', help='Show time spent by all users', type=bool, default=False, is_flag=True)
def timecheck(config, since, is_pm):
    # type: (IO[str], str, bool) -> None
    """List time spent per day and overall on the source JIRA."""
    config_dict = json.load(config)
    start = arrow.get(since) if since else arrow.utcnow().floor('month')
    total = 0

    def worklog_key(worklog):
        # type: (Worklog) -> Tuple[date, Text]
        """Return the worklog grouping key."""
        return (worklog.started.date(), worklog.author)

    for (day, author), worklogs in itertools.groupby(
            sorted(get_worklogs(config_dict['source_jira'], start, all_users=is_pm), key=worklog_key),
            worklog_key,
    ):
        day_sum = sum(worklog.time_spent_seconds for worklog in worklogs)
        total += day_sum
        click.echo('{} {} spent {}'.format(day, author, format_time(day_sum)))

    click.echo('Total {}'.format(format_time(total)))
