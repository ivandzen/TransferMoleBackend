#!/bin/bash

if [ -z "$MODE" ]; then
  echo "MODE not set"
  exit 1
fi

########################################################################################################################
# LOADING TESTS

if [ "$MODE" = "LOAD_TEST" ]; then
  locust -f ./locustfile.py -u 1
  exit $?
fi

########################################################################################################################
# PRODUCTION SERVICES

if [ "$MODE" = "API_SERVICE" ]; then
  gunicorn -w "${NUM_WORKERS:=1}" \
  -k uvicorn.workers.UvicornWorker \
  -b api_service:8080 tm.service.api_service:app \
  --proxy-protocol --proxy-allow-from '*' --forwarded-allow-ips '*'
  exit $?
fi

if [ "$MODE" = "API_SERVICE_LOCAL" ]; then
  gunicorn -w "${NUM_WORKERS:=4}" \
  -k uvicorn.workers.UvicornWorker \
  -b localhost:9000 tm.service.api_service:app \
  --proxy-protocol --proxy-allow-from '*' --forwarded-allow-ips '*'
  exit $?
fi

if [ "$MODE" = "CHAIN_MONITOR" ]; then
  python3 -m tm.service.chain_monitor
  exit $?
fi

if [ "$MODE" = "TG_BOT" ]; then
  python3 -m tm.service.tg_bot
  exit $?
fi

if [ "$MODE" = "REPORTER_BOT" ]; then
  python3 -m tm.service.reporter_bot
  exit $?
fi

########################################################################################################################
# DEBUG SERVICES

if [ "$MODE" = "DEBUG_API_SERVICE" ]; then
  uvicorn --host localhost --port 9000 tm.service.api_service:app --reload --log-config=log_conf.yaml --use-colors
  exit $?
fi

if [ "$MODE" = "DEBUG_API_SERVICE_MULTITHREAD" ]; then
  uvicorn --host localhost --port 9000 tm.service.api_service:app --log-config=log_conf.yaml --use-colors --workers 4
  exit $?
fi

########################################################################################################################
# WRONG PARAMETERS

echo "Unexpected MODE $MODE"
exit 1
