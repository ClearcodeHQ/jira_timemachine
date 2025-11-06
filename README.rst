
jira_timemachine
================

This package copies worklogs from a source JIRA to an issue in a destination JIRA. It's idempotent: rerunning it
updates already copied worklogs instead of duplicating them.

To re-write your worklog for the last three days from one JIRA to another, use timemachine command:

.. code-block:: bash

    timemachine --config example_config/config.json --days 3

Check the example config for the needed fields; both JIRA and Tempo require personal access tokens, see
<https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/> and
<https://apidocs.tempo.io/>.

.. note::

    Timemachine will use regular JIRA's worklogs to read worklogs from if you
    won't have *tempo_token* configuration key, or have it empty.

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

Tempo dependency
----------------

The destination JIRA must have the `Tempo <https://www.tempo.io/>`__ plugin. It is
optional for the source JIRA (and the ``timecheck`` command can be used as an
alternative to the builtin JIRA time tracking reports).

When source JIRA has Tempo and its token is provided, ``timemachine`` accesses all
worklogs of the user; if Tempo is not used, only a single project (specified via
``project_key``) is synchronized.

In case of the source JIRA gaining or losing Tempo (and the configuration having the
token only when Tempo is used), we attempt to keep ``timemachine`` idempotent: worklogs
are identified by their JIRA IDs, not Tempo IDs.

Use via Docker
--------------

Run ``timemachine``::

  docker run --rm -v $PWD/example_config:/config clearcode/jira_timemachine:v1.2.1 timemachine --config /config/config.json

Run ``timecheck``::

  docker run --rm -v $PWD/example_config:/config clearcode/jira_timemachine:v1.2.1 timecheck --config /config/config.json

Example configs
---------------

Mapping worklogs from the ``source.atlassian.net`` jira project ``JIRA`` to the
``ARIJ-123`` issue on ``destination.atlassian.net``::

  {
    "source_jira": {
      "url": "https://source.atlassian.net",
      "email": "login@login.com",
      "jira_token": "",
      "project_key": "JIRA",
      "tempo_token": ""
    },
    "destination_jira": {
      "url": "https://destination.atlassian.net",
      "email": "login@login.com",
      "jira_token": "",
      "issue": "ARIJ-123",
      "tempo_token": ""
    },
    "issue_map": {
    }
  }

Mapping ``JIRA-101`` to ``ARIJ-1``, ``JIRA-102`` to ``ARIJ-2`` and every other issue to
``ARIJ-3``::

  {
    "source_jira": {
      "url": "https://source.atlassian.net",
      "email": "login@login.com",
      "jira_token": "",
      "project_key": "JIRA",
      "tempo_token": ""
    },
    "destination_jira": {
      "url": "https://destination.atlassian.net",
      "email": "login@login.com",
      "jira_token": "",
      "issue": "ARIJ-3",
      "tempo_token": ""
    },
    "issue_map": {
      "JIRA-101": "ARIJ-1",
      "JIRA-102": "ARIJ-2"
    }
  }

In any of these examples, provide your own tokens; delete the ``tempo_token`` field in
``source_jira`` or leave it blank if that JIRA has no Tempo plugin.
