jira_timemachine
================

This package copies worklogs from a source JIRA to an issue in a destination JIRA. It's idempotent: rerunning it
updates already copied worklogs instead of duplicating them.

To re-write your worklog for the last three days from one JIRA to another, use timemachine command:

.. code-block::

    timemachine --config example_config/config.json --days 3

Check the example config for the needed fields; both JIRA and Tempo require personal access tokens, see
<https://confluence.atlassian.com/cloud/api-tokens-938839638.html> and
<https://tempo-io.atlassian.net/wiki/spaces/TEMPO/pages/199065601/How+to+use+Tempo+Cloud+REST+APIs#HowtouseTempoCloudRESTAPIs-Createapersonalauthorizationtoken>.

Issue mapping
-------------

In a simple case, all worklogs are copied into a single destination JIRA issue: specify it as the
``destination_jira.issue`` key in the config.

To copy worklogs of specific other issues to different issues, specify them in the ``issue_map`` config key: it's an
object with keys of source JIRA keys mapped to destination JIRA views. If a key is missing, ``destination_jira.issue``
is used to choose the target issue.

Running ``timemachine`` again does not move existing worklogs. Do not remove destination issues from the ``issue_map``
while they have matching worklogs: only known destination issues are searched for copied worklogs, ones present
elsewhere will be duplicated.
