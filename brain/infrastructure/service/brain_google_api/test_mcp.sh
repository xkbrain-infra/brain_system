#!/bin/bash
export GOOGLE_CREDENTIALS_PATH=/brain/secrets/brain-google-api
exec ./releases/v0.1.0/bin/brain-google-api
