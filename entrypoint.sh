#!bin/bash

set -e

: ${CLOUD_MQTT_HOST:=argus.paris.inria.fr}
: ${CLOUD_MQTT_PORT:=8883}
: ${CLOUD_NETWORK_ID:=1200}

cd /srv/
ls -al .data

exec python -m swarmit.dashboard.main -a cloud -H ${CLOUD_MQTT_HOST} -P ${CLOUD_MQTT_PORT} --network-id ${CLOUD_NETWORK_ID} --http-port 8001
