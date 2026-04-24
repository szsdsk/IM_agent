#!/bin/bash
echo "Installing dependencies..."
pip install -r requirements.txt

echo "Starting Agent-Pilot Backend..."
python main.py
