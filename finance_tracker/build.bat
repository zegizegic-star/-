@echo off
chcp 65001 >nul
echo ============================================
echo   Сборка "Мои финансы" в отдельную программу (.exe)
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ОШИБКА] Python не найден на этом компьютере.
    echo Скачайте и установите Python с https://www.python.org/downloads/
    echo Важно: на первом экране установки поставьте галочку "Add python.exe to PATH".
    echo После установки запустите этот файл ещё раз.
    pause
    exit /b 1
)

echo Устанавливаю необходимые библиотеки, подождите...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ОШИБКА] Не удалось установить библиотеки. Проверьте подключение к интернету.
    pause
    exit /b 1
)

echo.
echo Собираю программу (обычно 1-3 минуты)...
python -m PyInstaller --noconfirm --onedir --windowed --name "МоиФинансы" ^
    --icon "icon.ico" --add-data "icon.ico;." --collect-data certifi ^
    --hidden-import PIL._tkinter_finder app.py

if errorlevel 1 (
    echo [ОШИБКА] Сборка не удалась. Прочитайте сообщение об ошибке выше.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Готово!
echo   Программа лежит здесь: dist\МоиФинансы\МоиФинансы.exe
echo ============================================
echo.
echo Скопируйте ВСЮ папку dist\МоиФинансы (не только exe-файл!) в любое
echo удобное место (например, на Рабочий стол) и запускайте
echo МоиФинансы.exe внутри неё двойным кликом — как обычную программу.
echo Данные будут сохраняться в файле finance_data.db рядом с exe,
echo внутри той же папки.
echo.
pause
