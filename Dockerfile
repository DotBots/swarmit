FROM python:3.13-slim

LABEL maintainer="alexandre.abadie@inria.fr"

RUN python -m pip install --upgrade --no-cache-dir swarmit[dashboard]

COPY entrypoint.sh /srv/
RUN chmod +x /srv/entrypoint.sh

ENTRYPOINT ["/srv/entrypoint.sh"]
