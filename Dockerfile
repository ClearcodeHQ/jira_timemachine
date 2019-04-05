FROM python:3.7 as app

WORKDIR /usr/src/app
# Install required dependencies and cache test dependencies, so they won't be redownloaded when updating after the code
# is changed. (We cannot use setup.py here, since it requires other files from this package.)
COPY requirements.txt requirements-tests.txt ./
RUN pip install -r requirements.txt
RUN pip download -r requirements-tests.txt
COPY . .
RUN pip install .

FROM app as tests

# Run linters and tests.
RUN pip install .[tests]
RUN pylint src/jira_timemachine
RUN mypy src/jira_timemachine tests
RUN pytest
# List outdated dependencies.
RUN pip list -o

FROM app

# Have the application without test dependencies, so the image is smaller and we can check that test dependencies are
# needed only for tests.
