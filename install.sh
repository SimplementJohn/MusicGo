#!/bin/bash
echo "===================================="
echo "  MusicGo - Installation Linux/Mac"
echo "===================================="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERREUR] Python 3 n'est pas installé."
    echo "  Ubuntu/Debian : sudo apt install python3 python3-pip"
    echo "  macOS         : brew install python3"
    exit 1
fi
echo "[OK] Python 3 détecté : $(python3 --version)"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "[ERREUR] Node.js n'est pas installé."
    echo "  Ubuntu/Debian : sudo apt install nodejs npm"
    echo "  macOS         : brew install node"
    exit 1
fi
echo "[OK] Node.js détecté : $(node --version)"

# Install Python dependencies
echo ""
echo "[INFO] Installation des dépendances Python..."
pip3 install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "[ERREUR] Échec de l'installation des dépendances Python."
    exit 1
fi
echo "[OK] Dépendances Python installées"

# Install Node dependencies
echo ""
echo "[INFO] Installation des dépendances Node.js..."
npm install
if [ $? -ne 0 ]; then
    echo "[ERREUR] Échec de l'installation des dépendances Node."
    exit 1
fi
echo "[OK] Dépendances Node installées"

# Check ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo ""
    echo "[ATTENTION] ffmpeg n'est pas installé."
    echo "  Ubuntu/Debian : sudo apt install ffmpeg"
    echo "  macOS         : brew install ffmpeg"
else
    echo "[OK] ffmpeg détecté"
fi

# Check yt-dlp
if ! python3 -m yt_dlp --version &> /dev/null; then
    echo "[INFO] Installation de yt-dlp..."
    pip3 install yt-dlp
fi
echo "[OK] yt-dlp disponible"

# Install spotdl
if ! command -v spotdl &> /dev/null; then
    echo "[INFO] Installation de spotdl..."
    pip3 install spotdl
    if [ $? -ne 0 ]; then
        echo "[ATTENTION] spotdl n'a pas pu être installé."
    else
        echo "[OK] spotdl installé"
    fi
else
    echo "[OK] spotdl détecté"
fi

echo ""
echo "===================================="
echo "  Installation terminée !"
echo "===================================="
echo ""
echo "Mode développement (2 terminaux) :"
echo "  Terminal 1 : python3 app.py"
echo "  Terminal 2 : npm run dev"
echo "  Ouvrir http://localhost:3000"
echo ""
echo "Mode production :"
echo "  npm run build"
echo "  python3 app.py"
echo "  Ouvrir http://localhost:8080"
echo ""
