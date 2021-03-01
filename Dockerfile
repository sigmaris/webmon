FROM python:3.7-slim

RUN mkdir /src

COPY webmon /src/webmon
COPY setup.py /src/setup.py

RUN BUILD_DEPS='build-essential libpq-dev python3-dev' \
    && apt-get update \
    && apt-get install -y --no-install-recommends ${BUILD_DEPS} libpq5 \
    && pip3.7 install /src \
    && apt-get purge --auto-remove -y ${BUILD_DEPS} \
    && apt-get autoremove -y --purge \
    && apt-get clean \
    && useradd -ms /bin/bash -d /src webmon

USER webmon
