@echo off
echo ====================================
echo   MusicGo - Installation Windows
echo ====================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH.
    echo Telechargez Python sur https://www.python.org/downloads/
    pause
    exit /b 1
)
echo [OK] Python detecte

:: Check Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Node.js n'est pas installe ou pas dans le PATH.
    echo Telechargez Node.js sur https://nodejs.org/
    pause
    exit /b 1
)
echo [OK] Node.js detecte :
node --version

:: Install Python dependencies
echo.
echo [INFO] Installation des dependances Python...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERREUR] Echec de l'installation des dependances Python.
    pause
    exit /b 1
)
echo [OK] Dependances Python installees

:: Install Node dependencies
echo.
echo [INFO] Installation des dependances Node.js...
npm install
if errorlevel 1 (
    echo [ERREUR] Echec de l'installation des dependances Node.
    pause
    exit /b 1
)
echo [OK] Dependances Node installees

:: Check ffmpeg
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ATTENTION] ffmpeg n'est pas installe ou pas dans le PATH.
    echo ffmpeg est necessaire pour la conversion audio.
    echo.
    echo Installation via winget :
    echo   winget install Gyan.FFmpeg
    echo.
) else (
    echo [OK] ffmpeg detecte
)

:: Check yt-dlp
python -m yt_dlp --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installation de yt-dlp...
    pip install yt-dlp
)
echo [OK] yt-dlp disponible

:: Check spotdl
spotdl --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installation de spotdl...
    pip install spotdl
    if errorlevel 1 (
        echo [ATTENTION] spotdl n'a pas pu etre installe.
        echo Le support Spotify ne sera pas disponible.
    ) else (
        echo [OK] spotdl installe
    )
) else (
    echo [OK] spotdl detecte
)

echo.
echo ====================================
echo   Installation terminee !
echo ====================================
echo.
echo Mode developpement (2 terminaux) :
echo   Terminal 1 : python app.py
echo   Terminal 2 : npm run dev
echo   Ouvrir http://localhost:3000
echo.
echo Mode production :
echo   npm run build
echo   python app.py
echo   Ouvrir http://localhost:8080
echo.
pause
