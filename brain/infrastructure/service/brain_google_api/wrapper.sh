#!/bin/bash
export GOOGLE_CREDENTIALS_PATH=/brain/secrets/brain_google_api/credentials.json
exec /brain/infrastructure/service/brain_google_api/releases/current/brain_google_api "$@"
