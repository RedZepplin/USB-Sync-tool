@echo off
setlocal enabledelayedexpansion

:: --- CONFIGURATION ---
set "SRC=C:\projects\Test"  
set "VOLUME_LABEL=" :: Optional: set to something like USB_SYNC to only sync those
set "LOGFILE=%~dp0usb_sync.log"

:: --- VALIDATE CONFIG ---
if not exist "%SRC%" (
    echo [ERROR] Source folder "%SRC%" does not exist.
    pause
    exit /b
)

echo Watching for USB drives... (Ctrl+C to exit)
echo --- Script started at %DATE% %TIME% --- >> "%LOGFILE%"

:loop
:: Find removable drives using WMIC and filter junk lines with FINDSTR
for /f "skip=1 tokens=1 delims=" %%D in ('wmic logicaldisk where "drivetype=2" get deviceid') do (
	set "DRIVE=%%D"
    set "DRIVE=!DRIVE: =!"  
    echo [DEBUG] Found drive: !DRIVE!

    if not "!DRIVE!"=="" (
        if not defined SYNCED_!DRIVE:~0,2! (
            
            :: Optional: check volume label if set
            if defined VOLUME_LABEL (
                for /f "tokens=*" %%L in ('vol !DRIVE! 2^>nul') do (
                    echo %%L | findstr /C:"%VOLUME_LABEL%" >nul || (
                        echo Skipping !DRIVE! (label mismatch)
                        set SYNCED_!DRIVE:~0,2!=skipped
                        goto :nextDrive
                    )
                )
            )

            echo [%DATE% %TIME%] Syncing to !DRIVE!... >> "%LOGFILE%"
            echo Syncing to !DRIVE!...

            robocopy "%SRC%" "!DRIVE!\sync" /MIR /R:1 /W:1 /NP /NDL /NFL /LOG+:"%LOGFILE%"

            echo [%DATE% %TIME%] Done syncing to !DRIVE!. >> "%LOGFILE%"
            set SYNCED_!DRIVE:~0,2!=done
        )
    )
    :nextDrive
)

timeout /t 5 >nul
goto loop
