FROM python:3.10.3-slim-buster as app

WORKDIR /usr/src/app
# Install required dependencies and cache test dependencies, so they won't be redownloaded when updating after the code
# is changed. (We cannot use setup.py here, since it requires other files from this package.)
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY . .
RUN pip install .
