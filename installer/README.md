# MusicGo — Installeur Windows

Build un installeur `.exe` autonome pour MusicGo (Python embedded + ffmpeg + yt-dlp + frontend buildé), prêt à être distribué sur Windows 10/11 x64.

## Prérequis

- **Windows 10/11 x64**
- **PowerShell 5.1+** (inclus dans Windows)
- **Node.js 18+** (pour `npm run build`)
- **Python 3.10+** (pour générer l'icône, optionnel si icône déjà présente)
- **Inno Setup 6** — [télécharger](https://jrsoftware.org/isdl.php)
- **Connexion internet** (seulement au premier build — les téléchargements sont mis en cache dans `.cache/`)

## Étapes

### 1. Générer l'icône (une seule fois)

```powershell
pip install pillow
cd installer
python generate-icon.py
```

Produit `installer/musicgo.ico`.

### 2. Préparer le bundle

```powershell
cd installer
.\build-installer.ps1
```

Ce script :
- Télécharge Python 3.11 embedded depuis python.org
- Installe pip dans le Python embedded et y installe `requirements.txt` + `spotdl`
- Télécharge ffmpeg (BtbN builds) et extrait `ffmpeg.exe` + `ffprobe.exe`
- Télécharge `yt-dlp.exe` (dernière release GitHub)
- Exécute `npm run build` dans le repo racine
- Copie `app.py`, `dist/`, `extension/`, `config.json` dans le bundle
- Copie le launcher

Durée : ~3–5 minutes (premier build), <1 min si cache présent.

Taille finale du bundle : ~150–200 MB.

### 3. Compiler l'installeur avec Inno Setup

Option A — ligne de commande :
```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" musicgo-setup.iss
```

Option B — GUI : ouvrir `musicgo-setup.iss` dans Inno Setup Compiler et cliquer sur **Build**.

Produit `installer/output/MusicGo-Setup-1.0.0.exe`.

### 4. Tester l'installeur

- Double-cliquer le `.exe`
- Accepter la licence, choisir le dossier (défaut : `C:\Program Files\MusicGo`)
- Cocher/décocher raccourci Bureau
- Installer (droits admin requis)
- À la fin : case « Lancer MusicGo maintenant »
- Le launcher démarre le backend FastAPI et ouvre `http://localhost:8080` dans le navigateur par défaut

**Désinstallation** : Panneau de config → Applications → MusicGo → Désinstaller (ou menu Démarrer → Désinstaller MusicGo).

## Structure du bundle

```
installer/
├── README.md                  # Cette documentation
├── build-installer.ps1        # Script de préparation (étape 2)
├── musicgo-setup.iss          # Script Inno Setup (étape 3)
├── generate-icon.py           # Générateur d'icône (étape 1)
├── musicgo.ico                # Icône Windows multi-tailles
├── license.txt                # Licence MIT + crédits tiers
├── launcher/
│   └── musicgo_launcher.py    # Lanceur (démarre backend + ouvre navigateur)
├── .cache/                    # Téléchargements cachés (gitignore)
└── bundle/                    # Généré par build-installer.ps1
    ├── python/                # Python 3.11 embedded + site-packages
    ├── ffmpeg/                # ffmpeg.exe + ffprobe.exe
    ├── yt-dlp/                # yt-dlp.exe
    ├── app/
    │   ├── app.py
    │   ├── requirements.txt
    │   ├── dist/              # Frontend Vite buildé
    │   └── extension/         # Extension Chrome/Edge
    └── musicgo_launcher.py
```

## Après installation

**Emplacement installé** : `C:\Program Files\MusicGo\`

**Raccourcis** :
- Menu Démarrer : `MusicGo`, `Désinstaller MusicGo`
- Bureau (optionnel) : `MusicGo.lnk`

**Extension navigateur** — pas auto-installée (impossible hors Chrome Web Store). L'utilisateur doit :
1. Ouvrir `chrome://extensions` (ou `edge://extensions`)
2. Activer « Mode développeur »
3. « Charger l'extension non empaquetée » → sélectionner `C:\Program Files\MusicGo\app\extension\`

Alternative : depuis l'UI MusicGo → bouton « Télécharger l'extension » (endpoint `/api/extension/download`) → dézipper → charger.

## Dépannage

**Le build Inno Setup échoue sur `Source: bundle\*`**
→ `build-installer.ps1` n'a pas été exécuté ou a échoué. Vérifiez que `installer/bundle/python/python.exe` existe.

**L'installeur se lance mais le launcher ne trouve pas `python.exe`**
→ Bundle corrompu. Supprimez `installer/bundle/` et `installer/.cache/`, relancez `build-installer.ps1`.

**Port 8080 déjà utilisé**
→ L'installeur avertit au lancement. Le launcher détecte le conflit et ouvre le navigateur sur l'instance existante au lieu de démarrer un second serveur.

**Le frontend ne s'affiche pas**
→ Vérifiez `{app}\app\dist\index.html`. Si absent, `npm run build` a échoué lors de la préparation.

## Reconstruire proprement

```powershell
Remove-Item -Recurse -Force installer\bundle, installer\.cache, installer\output
.\build-installer.ps1
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" musicgo-setup.iss
```
