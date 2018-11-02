# -*- coding: utf-8 -*-

# Copyright (c) 2016 by jira_timemachine authors and contributors <see AUTHORS file>
#
# This module is part of jira_timemachine and is released under
# the MIT License (MIT): http://opensource.org/licenses/MIT

"""Module for synchronization of Jira worklogs between different instances."""

import re
import json
from datetime import date, timedelta
import time
from typing import Iterator, Dict, List, IO, Any, TypeVar, Callable

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
        # type: (date, str) -> Iterator[dict]
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
                yield row
            url = response_data['metadata'].get('next')

    def update_worklog(self, worklog_id, data):
        # type: (int, dict) -> None
        """
        Update the specified worklog.

        :param dict data: worklog parameters
        """
        res = self.session.put(
            'https://api.tempo.io/2/worklogs/%d' % worklog_id,
            data=json.dumps(data)
        )
        try:
            res.raise_for_status()
        except:
            click.echo(res.content)
            raise

    def post_worklog(self, data):
        # type: (dict) -> None
        """
        Upload a new worklog.

        :param dict data: worklog parameters
        """
        res = self.session.post(
            'https://api.tempo.io/2/worklogs',
            data=json.dumps(data)
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
    worklog_msg = u"TIMEMACHINE_WID {id}: {author} spent {timeSpentSeconds}s on {issue} at {date}"
    # JQL Query based to list all issues to read worklogs from.
    issue_jql = "project = {project_key} AND updated >= -{0}d ORDER BY key ASC"

    source_worklogs = {}  # type: Dict[int, Any]
    source_url = config_dict['source_jira']['url']
    source_tempo = TempoClient(config_dict['source_jira']['tempo_token'])
    destination_tempo = TempoClient(config_dict['destination_jira']['tempo_token'])

    if utcnow - timedelta(days=days) < TEMPO_EPOCH:
        source_jira = JIRA(
            source_url,
            basic_auth=(config_dict['source_jira']['login'], config_dict['source_jira']['password'])
        )
        source_user = source_jira.user(config_dict['source_jira']['login'])
        for issue in issues(source_jira, issue_jql.format(days, project_key=config_dict['source_jira']['project_key'])):
            for worklog in source_jira.worklogs(issue):
                if not worklog.author == source_user:
                    # click.echo(u'Skip, worklog author not in map {0}'.format(worklog.author))
                    continue
                if arrow.get(worklog.updated) < utcnow - timedelta(days=days):
                    click.echo('Skip, update too long ago {0}'.format(worklog.updated))
                    continue
                source_worklogs[int(worklog.id)] = {
                    'timeSpentSeconds': worklog.timeSpentSeconds,
                    'id': worklog.id,
                    'author': worklog.author,
                    'issue': issue,
                    'date': arrow.get(worklog.started)
                }
                click.echo(worklog_msg.format(**source_worklogs[int(worklog.id)]))

    for worklog in source_tempo.get_worklogs(
            from_date=(utcnow - timedelta(days=days)).date(),
            username=config_dict['source_jira']['login'],
    ):
        if worklog['author']['username'] != config_dict['source_jira']['login']:
            continue
        start = arrow.get('{startDate} {startTime}'.format(**worklog))
        if start < utcnow - timedelta(days=days):
            click.echo('Skip, update too long ago {0}'.format(start))
            continue
        if start < TEMPO_EPOCH:
            click.echo('Skip, update before Tempo epoch {0}'.format(start))
            continue
        source_worklogs[int(worklog['jiraWorklogId'])] = {
            'timeSpentSeconds': worklog['timeSpentSeconds'],
            # Each Tempo worklog has separate Jira and Tempo worklog IDs. Use Jira IDs so worklogs can be idempotently
            # synced if a Jira instance adds/removes Tempo.
            'id': worklog['jiraWorklogId'],
            'issue': worklog['issue']['key'],
            'author': worklog['author']['username'],
            'date': arrow.get(start)
        }

    # Query all recent user's worklogs and then filter by task. It should be faster than querying by issue and
    # filtering by user if several users sync worklogs to the same issue and the user doesn't have too many worklogs in
    # other issues (e.g. logging time to the destination Jira mostly via the timemachine).
    for ccworklog in destination_tempo.get_worklogs(
            from_date=(utcnow - timedelta(days=days)).date(),
            username=config_dict['destination_jira']['login'],
    ):
        if ccworklog['issue']['key'] != config_dict['destination_jira']['issue']:
            continue
        match = auto_worklog.match(ccworklog['description'])
        if not match:
            continue
        worklog_id = match.groupdict()['id']
        if int(worklog_id) not in source_worklogs:
            # might be some old worklog
            continue
        source_worklog = source_worklogs[int(worklog_id)]
        comment = worklog_msg.format(**source_worklog)
        if ccworklog['description'] == comment:
            del source_worklogs[int(worklog_id)]
            click.echo(u"Nothing changed for {0}".format(ccworklog['description']))
            continue
        else:
            click.echo(u"Updating worklog {0} to {1}".format(ccworklog['description'], comment))
            destination_tempo.update_worklog(
                ccworklog['tempoWorklogId'], {
                    'attributes': [],
                    'authorUsername': config_dict['destination_jira']['login'],
                    'description': worklog_msg.format(**source_worklog),
                    'issueKey': ccworklog['issue']['key'],
                    'startDate': source_worklog['date'].format('YYYY-MM-DD'),
                    'startTime': source_worklog['date'].format('HH:mm:ss'),
                    'timeSpentSeconds': source_worklog['timeSpentSeconds'],
                })
            del source_worklogs[int(worklog_id)]
            continue

    click.echo("Writing {0} worklogs to Destination JIRA".format(len(source_worklogs)))

    with click.progressbar(source_worklogs.values(), label="Writing worklog") as worklogs:

        for source_worklog in worklogs:
            destination_tempo.post_worklog({
                'issueKey': config_dict['destination_jira']['issue'],
                'timeSpentSeconds': source_worklog['timeSpentSeconds'],
                'startDate': source_worklog['date'].format('YYYY-MM-DD'),
                'startTime': source_worklog['date'].format('HH:mm:ss'),
                'description': worklog_msg.format(**source_worklog),
                'authorUsername': config_dict['destination_jira']['login'],
                'attributes': [],
            })
