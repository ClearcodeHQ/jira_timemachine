jira_timemachine
================

This package copies worklogs from a source Jira to an issue in a destination Jira. It's idempotent: rerunning it
updates already copied worklogs instead of duplicating them.

To re-write your worklog for the last three days from one JIRA to another, use timemachine command:

.. code-block::

    timemachine --config example_config/config.json --days 3

Check the example config for the needed fields; both Jira and Tempo require personal access tokens, see
<https://confluence.atlassian.com/cloud/api-tokens-938839638.html> and
<https://tempo-io.atlassian.net/wiki/spaces/TEMPO/pages/199065601/How+to+use+Tempo+Cloud+REST+APIs#HowtouseTempoCloudRESTAPIs-Createapersonalauthorizationtoken>.
