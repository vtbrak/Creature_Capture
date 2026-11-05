@echo off
rem Locate Anaconda/Miniconda/Miniforge and set CONDA_BAT to its condabin\conda.bat.
rem Called by install_windows.bat and run_windows.bat.
rem Override by setting CONDA_BASE first, e.g.  set CONDA_BASE=D:\anaconda3

set "CONDA_BAT="
if defined CONDA_BASE call :try "%CONDA_BASE%"
if defined CONDA_BAT goto :found
if defined CONDA_EXE (
    for %%I in ("%CONDA_EXE%\..\..") do call :try "%%~fI"
)
if defined CONDA_BAT goto :found
for /f "delims=" %%I in ('where conda.bat 2^>nul') do (
    if not defined CONDA_BAT for %%J in ("%%~dpI..") do call :try "%%~fJ"
)
if defined CONDA_BAT goto :found
for %%B in (
    "%USERPROFILE%\anaconda3"
    "%USERPROFILE%\miniconda3"
    "%USERPROFILE%\miniforge3"
    "%USERPROFILE%\mambaforge"
    "%LOCALAPPDATA%\anaconda3"
    "%LOCALAPPDATA%\miniconda3"
    "%LOCALAPPDATA%\Continuum\anaconda3"
    "%ProgramData%\anaconda3"
    "%ProgramData%\miniconda3"
    "%ProgramData%\miniforge3"
    "C:\anaconda3"
    "C:\miniconda3"
    "C:\tools\anaconda3"
    "C:\tools\miniconda3"
) do (
    if not defined CONDA_BAT call :try %%B
)
if defined CONDA_BAT goto :found

echo.
echo ERROR: Could not find Anaconda / Miniconda (no condabin\conda.bat found).
echo Install Anaconda or Miniconda, or set CONDA_BASE first, for example:
echo     set CONDA_BASE=D:\anaconda3
echo.
exit /b 1

:found
echo Using conda from: %CONDA_BAT%
exit /b 0

:try
if exist "%~1\condabin\conda.bat" set "CONDA_BAT=%~1\condabin\conda.bat"
exit /b 0
