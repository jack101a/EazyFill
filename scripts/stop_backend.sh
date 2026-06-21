#!/bin/bash
pkill -f "uvicorn app.main:app"
echo "Backend stopped."
