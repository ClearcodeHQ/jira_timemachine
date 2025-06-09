FROM python:3.13.4-slim as builder

WORKDIR /usr/src/app
# Install required dependencies and cache test dependencies, so they won't be redownloaded when updating after the code
# is changed. (We cannot use setup.py here, since it requires other files from this package.)
COPY pyproject.toml .
COPY jira_timemachine .
RUN pip install build && python -m build .

FROM python:3.13.4-slim as app
COPY --from=builder /usr/src/app/dist/jira_timemachine-*.whl .
RUN pip install jira_timemachine-*.whl
