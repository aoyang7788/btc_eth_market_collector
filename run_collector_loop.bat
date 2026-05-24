@echo off
title Market Collector V5
cd /d "%~dp0"
python main.py --loop --interval 15
pause
