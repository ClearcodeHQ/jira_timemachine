jira_timemachine
================

This package copies worklogs from a source Jira to an issue in a destination Jira. It's idempotent: rerunning it
updates already copied worklogs instead of duplicating them.

.. warning::

    This might log you out from cloud jira browser session!

To re-write your worklog for the last three days from one JIRA to another, use timemachine command:

.. code-block::

    timemachine --config example_config/config.json --days 3

Check the example config for the needed fields; Tempo access requires generating a personal access token, see
<https://tempo-io.atlassian.net/wiki/spaces/TEMPO/pages/199065601/How+to+use+Tempo+Cloud+REST+APIs#HowtouseTempoCloudRESTAPIs-Createapersonalauthorizationtoken>.
