FROM ubuntu:22.04 AS base

RUN apt update && apt install -y ca-certificates
RUN apt install -y python3 python3-pip
RUN apt install -y gunicorn

COPY requirements.txt entrypoint.sh log_conf.yaml /opt/

WORKDIR /opt

RUN pip3 install -r ./requirements.txt

COPY tm/ /opt/tm/
