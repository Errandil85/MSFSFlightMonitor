@echo off
REM Create virtual environment named MSFSFlightMonitor
python -m venv MSFSFlightMonitor

REM Activate the virtual environment
call MSFSFlightMonitor\Scripts\activate

REM Upgrade pip
python -m pip install --upgrade pip

REM Install requirements
pip install -r requirements.txt

echo Virtual environment 'MSFSFlightMonitor' is set up and activated.