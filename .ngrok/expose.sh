#!/bin/bash
set -e
echo "Exposing llm-gateway at: https://hyperpolysyllabically-saronic-mee.ngrok-free.app"
ngrok http 8000 --url https://hyperpolysyllabically-saronic-mee.ngrok-free.app
