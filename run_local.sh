#!/bin/bash

env $(cat ../.env | grep -v "#" | xargs) ./entrypoint.sh
