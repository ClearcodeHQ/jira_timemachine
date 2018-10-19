# -*- coding: utf-8 -*-

# Copyright (c) 2016 by jira_timemachine authors and contributors <see AUTHORS file>
#
# This module is part of jira_timemachine and is released under
# the MIT License (MIT): http://opensource.org/licenses/MIT
import re
import json
import logging
from datetime import timedelta
import time
from typing import Iterator, Dict, List, IO, Any, TypeVar, Callable

import click
import arrow
from jira import JIRA
import jira
from selenium.webdriver.chrome.options import Options
from splinter import Browser
import requests
from requests.utils import add_dict_to_cookiejar

__version__ = '0.0.0'

logger = logging.getLogger(__name__)


TEMPO_EPOCH = arrow.Arrow(2017, 6, 9)
"""
The date since which worklogs are available in Tempo only.

Older ones are both in Tempo and JIRA REST API, while they have different IDs, so we must use one source for them only.
"""


T = TypeVar('T')


def wait(callback, timeout=6):
    # type: (Callable[[], T], int) -> T
    """Retry *callback* until it returns a truthy value and return that value."""
    for _ in xrange(timeout * 10):
        result = callback()
        if result:
            return result
        time.sleep(0.1)
    else:
        raise ValueError('Timeout calling %s' % callback)


def issues(jira, query):
    # type: (JIRA, str) -> Iterator[jira.Issue]
    """Issues iterator"""
    issue_index = 1
    while True:
        issues = jira.search_issues(jql_str=query, startAt=issue_index, maxResults=50)
        for issue in issues:
            yield issue
        issue_index += 51
        if len(issues) < 50:
            raise StopIteration()


class TempoClient(object):
    """
    A client for Tempo Cloud APIs.

    Since there is no documented authentication method for it, we use Selenium to obtain Tempo context and session from
    the browser (as set by JIRA), later use Tempo REST API via requests.

    Previous versions of Tempo have similar API documented at <https://tempoplugin.jira.com/wiki/display/JTS/Tempo+REST+APIs>.
    """

    def __init__(self, jira_url, email, jira_password):
        # type: (str, str, str) -> None
        """Obtain Tempo credentials from JIRA."""
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--disable-gpu')
        browser = Browser('chrome', options=chrome_options)
        browser.visit(jira_url)
        browser.find_by_id('username').fill(email)
        browser.find_by_id('login-submit').click()
        wait(lambda: browser.find_by_id('password').visible)
        browser.find_by_id('password').fill(jira_password)
        browser.find_by_id('login-submit').click()
        wait(lambda: 'Dashboard.jspa' in browser.url)
        browser.visit(jira_url + '/plugins/servlet/ac/is.origo.jira.tempo-plugin/tempo-my-work#!')

        def get_tempo_frame():
            # type: () -> Any
            for frame in browser.find_by_tag('iframe'):
                if frame['id'].startswith('is.origo.jira.tempo-plugin'):
                    return frame
            return None

        frame = wait(get_tempo_frame)
        with browser.get_iframe(frame['id']) as iframe:
            tempo_state = json.loads(iframe.find_by_id('tempo-container')['data-initial-state'])
        self.session = requests.Session()
        self.session.cookies = add_dict_to_cookiejar(
            self.session.cookies,
            {'tempo_session': tempo_state['tempoSession']})
        self.session.headers.update({
            'Tempo-Context': tempo_state['tempoContext'],
            'Tempo-Session': tempo_state['tempoSession'],
            'Origin': 'https://app.tempo.io',
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36',
        })

    def get_worklogs(self, data):
        # type: (dict) -> List[dict]
        """
        Return worklogs matching specified criteria.

        :param dict data: parameters for worklog filtering: known used ones are "from", "to" (specifying a date), "worker" (user's name)

        :rtype: list
        :returns: list of dicts representing worklogs
        """
        res = self.session.post(
            'https://app.tempo.io/rest/tempo-timesheets/4/worklogs/search',
            data=json.dumps(data))
        return res.json()

    def update_worklog(self, worklog_id, data):
        # type: (int, dict) -> None
        """
        Update the specified worklog.

        :param dict data: worklog parameters
        """
        res = self.session.put(
            'https://app.tempo.io/rest/tempo-timesheets/4/worklogs/%d/' % worklog_id,
            data=json.dumps(data)
        )
        res.raise_for_status()

    def post_worklog(self, data):
        # type: (dict) -> None
        """
        Upload a new worklog.

        :param dict data: worklog parameters
        """
        res = self.session.post(
            'https://app.tempo.io/rest/tempo-timesheets/4/worklogs',
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
    config_dict = json.load(config)
    utcnow = arrow.utcnow()

    auto_worklog = re.compile("TIMEMACHINE_WID (?P<id>\d+).*")
    """regexp to detect the automatic worklog in Destination JIRA."""
    worklog_msg = u"TIMEMACHINE_WID {id}: {author} spent {timeSpentSeconds}s on {issue} at {date}"
    """Automatic worklog message."""
    issue_jql = "project = {project_key} AND updated >= -{0}d ORDER BY key ASC"
    """JQL Query based to list all issues to read worklogs from."""



    destination_url = config_dict['destination_jira']['url']
    destination_jira = JIRA(
        destination_url,
        basic_auth=(config_dict['destination_jira']['login'], config_dict['destination_jira']['password'])
    )
    destination_user = destination_jira.user(config_dict['destination_jira']['login'])
    destination_jira_issue = destination_jira.issue(config_dict['destination_jira']['issue'])
    source_worklogs = {}  # type: Dict[int, Any]
    sorce_url = config_dict['source_jira']['url']
    source_tempo = TempoClient(
        sorce_url, config_dict['source_jira']['email'], config_dict['source_jira']['password']
    )
    destination_tempo = TempoClient(
        destination_url, config_dict['destination_jira']['email'], config_dict['destination_jira']['password']
    )

    if utcnow - timedelta(days=days) < TEMPO_EPOCH:
        source_jira = JIRA(
            sorce_url,
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

    for worklog in source_tempo.get_worklogs({
            'from': str((utcnow - timedelta(days=days)).date()),
            'worker': [config_dict['source_jira']['login']]}):
        if worklog['worker'] != config_dict['source_jira']['login']:
            continue
        if arrow.get(worklog['started']) < utcnow - timedelta(days=days):
            click.echo('Skip, update too long ago {0}'.format(worklog['started']))
            continue
        if arrow.get(worklog['started']) < TEMPO_EPOCH:
            click.echo('Skip, update before Tempo epoch {0}'.format(worklog['started']))
            continue
        source_worklogs[int(worklog['originId'])] = {
            'timeSpentSeconds': worklog['timeSpentSeconds'],
            'id': worklog['originId'],
            'issue': worklog['issue']['key'],
            'author': worklog['worker'],
            'date': arrow.get(worklog['started'])
        }

    for ccworklog in destination_tempo.get_worklogs({
            'from': str((utcnow - timedelta(days=days)).date()),
            'worker': [config_dict['destination_jira']['login']],
            'taskId': [destination_jira_issue.id],
    }):
        match = auto_worklog.match(ccworklog['comment'])
        if not match:
            continue
        worklog_id = match.groupdict()['id']
        if int(worklog_id) not in source_worklogs:
            # might be some old worklog
            continue
        source_worklog = source_worklogs[int(worklog_id)]
        comment = worklog_msg.format(**source_worklog)
        if ccworklog['comment'] == comment:
            del source_worklogs[int(worklog_id)]
            click.echo(u"Nothing changed for {0}".format(ccworklog['comment']))
            continue
        else:
            print(u"Updating worklog {0} to {1}".format(ccworklog['comment'], comment))
            destination_tempo.update_worklog(
                ccworklog['originId'], {
                    'attributes': {},
                    'billableSeconds': None,
                    'comment': worklog_msg.format(**source_worklog),
                    'originId':  ccworklog['originId'],
                    'originTaskId': destination_jira_issue.id,
                    'started': source_worklog['date'].format('YYYY-MM-DDTHH:mm:ss.SSS'),
                    'timeSpentSeconds': source_worklog['timeSpentSeconds'],
                    'worker': destination_user.name,
                })
            del source_worklogs[int(worklog_id)]
            continue

    click.echo("Writing {0} worklogs to Destination JIRA".format(len(source_worklogs)))

    with click.progressbar(source_worklogs.values(), label="Writing worklog") as worklogs:

        for source_worklog in worklogs:
            destination_tempo.post_worklog({
                'attributes': {},
                'comment': worklog_msg.format(**source_worklog),
                'includeNonWorkingDays': False,
                'originTaskId': destination_jira_issue.id,
                'remainingEstimate': 0,
                'started': source_worklog['date'].format('YYYY-MM-DDTHH:mm:ss.SSS'),
                'timeSpentSeconds': source_worklog['timeSpentSeconds'],
                'worker': destination_user.name,
            })
