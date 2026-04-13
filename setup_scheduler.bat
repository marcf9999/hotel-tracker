@echo off
REM Creates a Windows Scheduled Task to run the Marriott checker every 2 hours

set PYTHON_PATH=C:\Users\marcf\AppData\Local\Python\bin\python.exe
set SCRIPT_PATH=C:\Users\marcf\Documents\marriott-checker\checker.py

REM Delete existing task if it exists
schtasks /delete /tn "MarriottAvailabilityChecker" /f 2>nul

REM Create the scheduled task - runs every 2 hours, starting now
schtasks /create ^
  /tn "MarriottAvailabilityChecker" ^
  /tr "\"%PYTHON_PATH%\" \"%SCRIPT_PATH%\"" ^
  /sc hourly ^
  /mo 2 ^
  /st 00:00 ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /f

if %errorlevel% equ 0 (
    echo.
    echo Task created successfully! The checker will run every 2 hours.
    echo Task name: MarriottAvailabilityChecker
    echo.
    echo To view: schtasks /query /tn "MarriottAvailabilityChecker"
    echo To delete: schtasks /delete /tn "MarriottAvailabilityChecker" /f
    echo To run now: schtasks /run /tn "MarriottAvailabilityChecker"
) else (
    echo.
    echo Failed to create task. Try running this script as Administrator.
)
pause
