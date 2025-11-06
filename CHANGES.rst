CHANGELOG
#########

.. towncrier release notes start

1.2.0 (2025-11-06)
==================

Features
--------

- Add support to python 3.14


Miscellaneus
------------

- Adjust workflows for actions-reuse 3
- Replace linters with pre-commit
- Updated tests for new Pydantic.


1.1.0 (2024-10-09)
==================

Breaking changes
----------------

- Drop Support for Python 3.9 (`#338 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/338>`__)
- Drop support for Python 3.10


Bugfixes
--------

- Updated SourceJiraConfig creation in tests to satisfy mypy checks. (`#247 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/247>`__)


Features
--------

- Migrated code to pydantic 2 (`#284 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/284>`__)
- Generate error message in config validator instead of relying on pydantic
      - it adds additional clutter like pydantic documentation url and is hard to test. (`#286 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/286>`__)
- Add support for Python 3.12 (`#338 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/338>`__)
- Added support for Python 3.13


Miscellaneus
------------

- `#268 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/268>`_, `#285 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/285>`_, `#385 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/385>`_


1.0.1 (2023-02-21)
==================

Breaking changes
----------------

- Drop support for python 3.8 (`#224 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/224>`__)


Features
--------

- Upload documentation to github-pages. (`#65 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/65>`__)
- Support Python 3.11 (`#224 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/224>`__)


Miscellaneus
------------

- Use towncrier to manage newsfragments and changelog. (`#222 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/222>`__)
- Migrate dependency management to pipenv (`#223 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/223>`__)
- Migrate the automerge pipeline to the shared one. Requiring github app to authenticate. (`#225 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/225>`__)
- Migrate version management tool to tbump (`#226 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/226>`__)
- Migrate package configuration to pyproject.toml (`#231 <https://https://github.com/ClearcodeHQ/jira_timemachine/issues/231>`__)


1.0.0
=====

Features
--------

- Support python 3.9 and 3.8
- Drop support for python 2.7
- Produce a docker image on docker hub
- Reference dockerhub hosted image and tagged in readme

0.0.0
=====

- Created the JIRA Time Machine [by Grzegorz Śliwiński]
