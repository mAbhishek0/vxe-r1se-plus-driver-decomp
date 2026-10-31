@echo off
rem Builds dist\R1SE_Portable.exe (needs: pip install hidapi pyinstaller)
cd /d "%~dp0"
python -m PyInstaller --clean --noconfirm --onefile --windowed --name R1SE_Portable ^
  --add-data "%~dp0src\dpi_table_3395se.json;." --paths "%~dp0src" ^
  --distpath dist --workpath build --specpath build src\r1se_gui.py
