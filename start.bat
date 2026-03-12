@echo off
chcp 65001 > nul
title PORT-MIS 관제현황 서버

echo.
echo  ====================================
echo   PORT-MIS 모선별관제현황 조회 서버
echo  ====================================
echo.
echo  서버 주소: http://localhost:8000
echo  종료: Ctrl + C
echo.

cd /d %~dp0
python main.py

pause
