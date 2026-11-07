@echo off
rem Compile launcher.py en lightAPM.exe (a la racine du projet).
rem Prerequis : python -m pip install pyinstaller
cd /d "%~dp0.."
python -m PyInstaller --onefile --noconsole --clean --name lightAPM ^
  --icon "%CD%\app\assets\lightapm_icon.ico" ^
  --distpath "%CD%" --workpath "%CD%\build" --specpath "%CD%\build" ^
  launcher\launcher.py
if errorlevel 1 (
  echo.
  echo ECHEC de la compilation.
  exit /b 1
)
rmdir /s /q build
echo.
echo lightAPM.exe pret.
