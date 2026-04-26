import './style.css'
import confetti from 'canvas-confetti'
import { apiPost, apiDelete, apiGet } from './api.js'
import { connectWS } from './websocket.js'
import { showToast } from './toast.js'
import { escapeHtml, detectSource } from './utils.js'
import { SOURCE_ICONS, SOURCE_LABELS } from './icons.js'

import packageJson from '../package.json'

const APP_VERSION = packageJson?.version || 'dev'

// === State ===
let analyzeResult = null
let state = { queue: [], library: [] }
let settings = {
    format: localStorage.getItem('musicgo_format') || 'mp3',
    quality: localStorage.getItem('musicgo_quality') || '320',
}

function saveSettings() {
    localStorage.setItem('musicgo_format', settings.format)
    localStorage.setItem('musicgo_quality', settings.quality)
}

// === Render the app shell ===
function renderApp() {
    const app = document.getElementById('app')
    app.innerHTML = `
        <!-- Header -->
        <header class="header">
            <div class="logo">
                <svg class="logo-icon" viewBox="0 0 40 40" width="40" height="40">
                    <circle cx="20" cy="20" r="18" fill="none" stroke="var(--accent)" stroke-width="2"/>
                    <circle cx="20" cy="20" r="6" fill="var(--accent)"/>
                    <path d="M26 12 L26 24" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round"/>
                    <path d="M26 12 L32 10 L32 16 L26 18" fill="var(--accent)" opacity="0.8"/>
                </svg>
                <h1>Music<span class="accent">Go</span></h1>
            </div>
            <div class="status-bar">
                <button id="btn-settings" class="btn-icon" title="Paramètres">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="3"/>
                        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
                    </svg>
                </button>
                <button id="btn-extension" class="btn-ext-install" title="Installer l'extension Chrome / Edge">
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
                        <polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>
                    </svg>
                    Extension
                </button>
                <span id="queue-count" class="status-badge">0 en file</span>
            </div>
        </header>

        <!-- Extension modal -->
        <div id="ext-modal-backdrop" class="ext-modal-backdrop hidden">
            <div class="ext-modal">
                <div class="ext-modal-header">
                    <div class="ext-modal-title">
                        <svg viewBox="0 0 40 40" width="22" height="22">
                            <circle cx="20" cy="20" r="18" fill="none" stroke="#a78bfa" stroke-width="2"/>
                            <circle cx="20" cy="20" r="6" fill="#a78bfa"/>
                            <path d="M26 12 L26 24" stroke="#a78bfa" stroke-width="2.5" stroke-linecap="round"/>
                            <path d="M26 12 L32 10 L32 16 L26 18" fill="#a78bfa" opacity="0.8"/>
                        </svg>
                        Extension YouTube
                    </div>
                    <button id="ext-modal-close" class="btn-icon">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </button>
                </div>

                <!-- ONE-CLICK section -->
                <div class="ext-oneclick">
                    <p>Lance Chrome ou Edge avec l'extension <strong>déjà active</strong> dans une fenêtre dédiée.</p>
                    <button id="btn-ext-launch" class="btn btn-primary ext-launch-btn">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                            <polygon points="5 3 19 12 5 21 5 3"/>
                        </svg>
                        Lancer avec l'extension
                    </button>
                    <div id="ext-launch-status"></div>
                </div>

                <div class="ext-divider"><span>ou installation manuelle</span></div>

                <!-- Manual fallback -->
                <ol class="ext-steps">
                    <li>
                        <span class="ext-step-num">1</span>
                        <div>
                            <strong>Ouvrir les extensions du navigateur</strong>
                            <span><code>chrome://extensions</code> ou <code>edge://extensions</code></span>
                        </div>
                    </li>
                    <li>
                        <span class="ext-step-num">2</span>
                        <div>
                            <strong>Activer le mode développeur</strong>
                            <span>Interrupteur en haut à droite</span>
                        </div>
                    </li>
                    <li>
                        <span class="ext-step-num">3</span>
                        <div>
                            <strong>Charger l'extension non empaquetée</strong>
                            <span>Sélectionner le dossier ou télécharger le ZIP et l'extraire :</span>
                            <code class="ext-path" id="ext-path">~/MusicGo/extension</code>
                            <a href="/api/extension/download" download="musicgo-extension.zip" class="btn-ext-download">
                                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5">
                                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                                    <polyline points="7 10 12 15 17 10"/>
                                    <line x1="12" y1="15" x2="12" y2="3"/>
                                </svg>
                                Télécharger musicgo-extension.zip
                            </a>
                        </div>
                    </li>
                </ol>
            </div>
        </div>

        <!-- Settings Modal -->
        <div id="settings-backdrop" class="settings-backdrop hidden">
            <div class="settings-modal">
                <div class="settings-header">
                    <div class="settings-title">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="var(--accent)" stroke-width="2">
                            <circle cx="12" cy="12" r="3"/>
                            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
                        </svg>
                        Paramètres
                    </div>
                    <button id="settings-close" class="btn-icon">
                        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </button>
                </div>
                <div class="stabs">
                    <button class="stab active" data-stab="storage">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12H2"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>
                        Stockage
                    </button>
                    <button class="stab" data-stab="audio">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>
                        Audio
                    </button>
                    <button class="stab" data-stab="systeme">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8"/><path d="M12 17v4"/></svg>
                        Système
                    </button>
                    <button class="stab" data-stab="info">
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
                        Info
                    </button>
                </div>

                <div id="stab-storage" class="stab-panel">
                    <div class="sf">
                        <label>Dossier de téléchargement</label>
                        <div class="sf-browse-row">
                            <input type="text" id="s-dl-dir" class="sf-input" placeholder="Ex: C:\\Musiques"/>
                            <button id="s-dl-browse" type="button" class="btn btn-ghost btn-sm">Parcourir</button>
                        </div>
                    </div>
                </div>

                <div id="stab-audio" class="stab-panel hidden">
                    <div class="sf"><label>Format par défaut</label>
                        <select id="s-format" class="sf-input">
                            <option value="mp3">MP3</option><option value="flac">FLAC</option>
                            <option value="wav">WAV</option><option value="ogg">OGG</option>
                            <option value="m4a">M4A</option><option value="opus">OPUS</option>
                        </select>
                    </div>
                    <div class="sf"><label>Qualité par défaut</label>
                        <select id="s-quality" class="sf-input">
                            <option value="320">320 kbps</option><option value="256">256 kbps</option>
                            <option value="192">192 kbps</option><option value="128">128 kbps</option>
                        </select>
                    </div>
                    <div class="sf"><label>Échantillonnage par défaut</label>
                        <select id="s-samplerate" class="sf-input">
                            <option value="48000">48 kHz</option><option value="44100">44.1 kHz</option>
                            <option value="0">Auto</option><option value="96000">96 kHz (sans MP3)</option>
                        </select>
                    </div>
                </div>

                <div id="stab-systeme" class="stab-panel hidden">
                    <div class="sf">
                        <label>Démarrage avec Windows</label>
                        <div class="sf-toggle-row">
                            <label class="toggle-switch">
                                <input type="checkbox" id="s-startup"/>
                                <span class="toggle-slider"></span>
                            </label>
                            <span id="s-startup-label" class="toggle-label">Lancer MusicGo au démarrage (minimisé dans le tray)</span>
                        </div>
                        <span id="s-startup-msg" class="settings-msg" style="margin-top:6px;display:block"></span>
                    </div>
                </div>

                <div id="stab-info" class="stab-panel hidden">
                    <div class="sf"><label>Version</label><input type="text" id="s-version" class="sf-input" readonly value="v${APP_VERSION}"/></div>
                </div>

                <div class="settings-footer">
                    <span id="settings-msg" class="settings-msg"></span>
                    <div class="settings-footer-btns">
                        <button id="settings-save" class="btn btn-primary btn-sm">Enregistrer</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- URL Input Section -->
        <section class="input-section">
            <div class="input-wrapper">
                <div class="input-container">
                    <input
                        type="text"
                        id="url-input"
                        placeholder="Coller l'URL YouTube..."
                        autocomplete="off"
                        spellcheck="false"
                    >
                    <div id="source-badge" class="source-indicator hidden"></div>
                </div>
                <button id="btn-paste" class="btn btn-ghost" title="Coller depuis le presse-papiers">
                    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="9" y="2" width="6" height="4" rx="1"/>
                        <path d="M9 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2h-2"/>
                    </svg>
                    Coller
                </button>
                <button id="btn-add" class="btn btn-primary" disabled>
                    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
                    </svg>
                    Ajouter
                </button>
            </div>

            <!-- Format & Quality selectors -->
            <div class="settings-row">
                <div class="setting-group">
                    <label for="sel-format">Format</label>
                    <select id="sel-format">
                        <option value="mp3">MP3</option>
                        <option value="mp4">MP4 (vidéo)</option>
                        <option value="flac">FLAC</option>
                        <option value="wav">WAV</option>
                        <option value="ogg">OGG</option>
                    </select>
                </div>
                <div class="setting-group">
                    <label for="sel-quality">Qualité</label>
                    <select id="sel-quality">
                        <option value="320">320 kbps</option>
                        <option value="256">256 kbps</option>
                        <option value="192">192 kbps</option>
                        <option value="128">128 kbps</option>
                    </select>
                </div>
                <div class="setting-group" id="samplerate-group">
                    <label for="sel-samplerate">Échantillonnage</label>
                    <select id="sel-samplerate">
                        <option value="48000">48 kHz</option>
                        <option value="44100">44.1 kHz</option>
                        <option value="0">Auto</option>
                        <option value="96000">96 kHz (sans MP3)</option>
                    </select>
                </div>
            </div>

            <div id="playlist-dialog" class="playlist-dialog hidden">
                <div class="playlist-info">
                    <span id="playlist-icon" class="source-icon"></span>
                    <span id="playlist-count"></span>
                </div>
                <div class="playlist-actions">
                    <button id="btn-playlist-add" class="btn btn-primary btn-sm">Tout ajouter</button>
                    <button id="btn-playlist-cancel" class="btn btn-ghost btn-sm">Annuler</button>
                </div>
            </div>

            <div id="analyze-loading" class="loading hidden">
                <div class="spinner"></div>
                <span>Analyse de l'URL...</span>
            </div>
        </section>

        <!-- Tabs -->
        <nav class="tabs">
            <button class="tab active" data-tab="queue">
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
                </svg>
                File d'attente
                <span id="tab-queue-count" class="tab-count hidden">0</span>
            </button>
            <button class="tab" data-tab="library">
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>
                </svg>
                Bibliothèque
                <span id="tab-library-count" class="tab-count hidden">0</span>
            </button>
        </nav>

        <!-- Queue Panel -->
        <section id="panel-queue" class="panel active">
            <div class="panel-header">
                <span class="panel-title" id="queue-title">Aucun téléchargement</span>
                <button id="btn-clear-queue" class="btn btn-ghost btn-sm hidden">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                    </svg>
                    Effacer la liste
                </button>
            </div>
            <div id="queue-list" class="download-list"></div>
        </section>

        <!-- Library Panel -->
        <section id="panel-library" class="panel">
            <div class="panel-header">
                <span class="panel-title" id="library-title">Bibliothèque</span>
                <button id="btn-clear-library" class="btn btn-ghost btn-sm hidden">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                    </svg>
                    Effacer la liste
                </button>
            </div>
            <div id="library-list" class="download-list"></div>
        </section>
    `
}

// === DOM helpers ===
const $ = (sel) => document.querySelector(sel)
const $$ = (sel) => document.querySelectorAll(sel)

// === Init the app ===
renderApp()

// === DOM refs (after render) ===
const urlInput = $('#url-input')
const btnAdd = $('#btn-add')
const sourceBadge = $('#source-badge')
const playlistDialog = $('#playlist-dialog')
const playlistCount = $('#playlist-count')
const playlistIcon = $('#playlist-icon')
const btnPlaylistAdd = $('#btn-playlist-add')
const btnPlaylistCancel = $('#btn-playlist-cancel')
const analyzeLoading = $('#analyze-loading')
const queueList = $('#queue-list')
const libraryList = $('#library-list')
const btnClearLibrary = $('#btn-clear-library')
const btnExtension = $('#btn-extension')
const extModalBackdrop = $('#ext-modal-backdrop')
const btnSettingsOpen = $('#btn-settings')
const settingsBackdrop = $('#settings-backdrop')
const btnPaste = $('#btn-paste')
const btnClearQueue = $('#btn-clear-queue')
const queueCountBadge = $('#queue-count')
const tabQueueCount = $('#tab-queue-count')
const tabLibraryCount = $('#tab-library-count')
const queueTitle = $('#queue-title')
const libraryTitle = $('#library-title')
const selFormat = $('#sel-format')
const selQuality = $('#sel-quality')
const selSamplerate = $('#sel-samplerate')

// Restore settings
selFormat.value = settings.format
selQuality.value = settings.quality
selSamplerate.value = localStorage.getItem('musicgo_samplerate') || '48000'

selFormat.addEventListener('change', () => {
    settings.format = selFormat.value
    saveSettings()
})
selQuality.addEventListener('change', () => {
    settings.quality = selQuality.value
    saveSettings()
})
selSamplerate.addEventListener('change', () => {
    localStorage.setItem('musicgo_samplerate', selSamplerate.value)
})

// === URL Input handling ===
urlInput.addEventListener('input', () => {
    const url = urlInput.value.trim()
    playlistDialog.classList.add('hidden')
    analyzeResult = null

    if (!url) {
        sourceBadge.classList.add('hidden')
        btnAdd.disabled = true
        return
    }

    const source = detectSource(url)
    sourceBadge.textContent = SOURCE_LABELS[source] || '?'
    sourceBadge.className = `source-indicator ${source}`
    sourceBadge.classList.remove('hidden')
    btnAdd.disabled = false
})

urlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !btnAdd.disabled) {
        btnAdd.click()
    }
})

// === Paste button ===
btnPaste.addEventListener('click', async () => {
    try {
        const text = await navigator.clipboard.readText()
        const trimmed = text.trim()
        if (!trimmed) return
        if (!trimmed.startsWith('http://') && !trimmed.startsWith('https://')) {
            showToast('Le presse-papiers ne contient pas une URL valide', 'error')
            return
        }
        urlInput.value = trimmed
        urlInput.dispatchEvent(new Event('input'))
        urlInput.focus()
    } catch {
        urlInput.focus()
        showToast('Colle directement dans le champ (Ctrl+V)', 'info')
    }
})

// === Add button ===
btnAdd.addEventListener('click', async () => {
    const url = urlInput.value.trim()
    if (!url) return

    btnAdd.disabled = true
    analyzeLoading.classList.remove('hidden')
    playlistDialog.classList.add('hidden')

    try {
        const result = await apiPost('/api/analyze', {
            url,
            format: settings.format,
            quality: settings.quality,
            samplerate: selSamplerate.value,
        })

        if (result.error) {
            showToast(result.error, 'error')
            btnAdd.disabled = false
            analyzeLoading.classList.add('hidden')
            return
        }

        analyzeResult = result

        if (result.is_playlist && result.track_count > 1) {
            playlistIcon.className = `source-icon ${result.source}`
            playlistIcon.innerHTML = SOURCE_ICONS[result.source] || SOURCE_ICONS.unknown
            playlistCount.textContent = `${result.track_count} titres détectés dans cette playlist`
            playlistDialog.classList.remove('hidden')
            analyzeLoading.classList.add('hidden')
            btnAdd.disabled = false
        } else {
            await addTracks(result.tracks, result.source)
            urlInput.value = ''
            sourceBadge.classList.add('hidden')
            analyzeLoading.classList.add('hidden')
        }
    } catch (e) {
        showToast('Erreur de connexion au serveur', 'error')
        btnAdd.disabled = false
        analyzeLoading.classList.add('hidden')
    }
})

btnPlaylistAdd.addEventListener('click', async () => {
    if (!analyzeResult) return
    playlistDialog.classList.add('hidden')
    analyzeLoading.classList.remove('hidden')
    analyzeLoading.querySelector('span').textContent = 'Ajout des titres...'
    await addTracks(analyzeResult.tracks, analyzeResult.source)
    urlInput.value = ''
    sourceBadge.classList.add('hidden')
    analyzeLoading.classList.add('hidden')
    analyzeLoading.querySelector('span').textContent = "Analyse de l'URL..."
    analyzeResult = null
})

btnPlaylistCancel.addEventListener('click', () => {
    playlistDialog.classList.add('hidden')
    analyzeResult = null
})

async function addTracks(tracks, source) {
    const payload = tracks.map((t) => ({
        url: t.url,
        title: t.title || t.url,
        source: source,
        thumbnail: t.thumbnail || '',
        format: settings.format,
        quality: settings.quality,
        samplerate: selSamplerate.value,
    }))
    try {
        const result = await apiPost('/api/queue/add', { tracks: payload })
        const count = result.added ? result.added.length : 0
        if (Array.isArray(result.added) && result.added.length > 0) {
            const knownIds = new Set(state.queue.map((item) => item.id))
            state.queue = [...result.added.filter((item) => !knownIds.has(item.id)), ...state.queue]
            renderQueue()
            updateCounts()
        } else {
            await refreshState()
        }
        showToast(
            `${count} titre${count > 1 ? 's' : ''} ajouté${count > 1 ? 's' : ''} à la file`,
            'success'
        )
    } catch (e) {
        showToast("Erreur lors de l'ajout", 'error')
    }
}

// === Extension modal ===
btnExtension.addEventListener('click', () => {
    $('#ext-path').textContent = window.location.origin.replace(/:\d+$/, '') + '/./MusicGo/extension'
    extModalBackdrop.classList.remove('hidden')
})
$('#ext-modal-close').addEventListener('click', () => extModalBackdrop.classList.add('hidden'))
extModalBackdrop.addEventListener('click', (e) => { if (e.target === extModalBackdrop) extModalBackdrop.classList.add('hidden') })

$('#btn-ext-launch').addEventListener('click', async () => {
    const btn = $('#btn-ext-launch')
    const status = $('#ext-launch-status')
    btn.disabled = true
    btn.innerHTML = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" style="animation:spin 1s linear infinite"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg> Lancement.`
    status.textContent = ''
    status.className = ''
    try {
        const res = await apiPost('/api/extension/launch', {})
        if (res.success) {
            status.textContent = `✓ ${res.browser} lancé avec l'extension !`
            status.className = 'ext-status-ok'
        } else {
            status.textContent = res.error || 'Erreur inconnue'
            status.className = 'ext-status-err'
        }
    } catch {
        status.textContent = 'Impossible de contacter le serveur'
        status.className = 'ext-status-err'
    }
    btn.disabled = false
    btn.innerHTML = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"/></svg> Lancer avec l'extension`
})

// === Clear queue ===
let clearInProgress = false
btnClearQueue.addEventListener('click', async () => {
    if (clearInProgress) return
    clearInProgress = true
    btnClearQueue.disabled = true
    try {
        await apiDelete('/api/queue')
        showToast("File d'attente vidée", 'info')
    } catch (e) {
        showToast(e.message || 'Erreur', 'error')
    } finally {
        clearInProgress = false
        btnClearQueue.disabled = false
    }
})

// === Clear library (all) ===
btnClearLibrary.addEventListener('click', async () => {
    if (!confirm(`Effacer tout l'historique (${state.library.length} fichier${state.library.length > 1 ? 's' : ''}) ?`)) return
    try {
        const res = await apiDelete('/api/library')
        if (res._status === 401) {
            showToast('Connexion requise pour cette action', 'error')
            return
        }
        showToast('Historique effacé', 'info')
    } catch (e) {
        showToast(e.message || 'Erreur', 'error')
    }
})

// === Clear library (by day) ===
libraryList.addEventListener('click', async (e) => {
    const btn = e.target.closest('.btn-delete-day')
    if (!btn) return
    const ids = JSON.parse(btn.dataset.ids)
    if (!confirm(`Effacer ${ids.length} fichier${ids.length > 1 ? 's' : ''} de ce jour ?`)) return
    try {
        const res = await apiPost('/api/library/remove', { ids })
        if (res._status === 401) {
            showToast('Connexion requise pour cette action', 'error')
            return
        }
        showToast(`${ids.length} fichier${ids.length > 1 ? 's supprimés' : ' supprimé'}`, 'info')
    } catch (err) {
        showToast(err.message || 'Erreur', 'error')
    }
})

// === Open in explorer ===
libraryList.addEventListener('click', async (e) => {
    const btn = e.target.closest('.btn-open-folder')
    if (!btn) return
    const id = btn.dataset.id
    try {
        await apiPost('/api/library/open', { id })
    } catch (err) {
        showToast(err.message || 'Impossible d\'ouvrir le dossier', 'error')
    }
})

// === Tabs ===
$$('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
        $$('.tab').forEach((t) => t.classList.remove('active'))
        $$('.panel').forEach((p) => p.classList.remove('active'))
        tab.classList.add('active')
        $(`#panel-${tab.dataset.tab}`).classList.add('active')
    })
})

// === Render queue ===
function renderQueue() {
    const items = state.queue
    const activeItems = items.filter((i) => i.status !== 'done')

    if (activeItems.length === 0) {
        queueList.innerHTML = `
            <div class="empty-state">
                <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="var(--text-muted)" stroke-width="1.5" opacity="0.5">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="7 10 12 15 17 10"/>
                    <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
                <p>Collez une URL pour commencer</p>
            </div>`
        btnClearQueue.classList.add('hidden')
        queueTitle.textContent = 'Aucun téléchargement'
        return
    }

    btnClearQueue.classList.remove('hidden')
    const downloading = items.filter((i) => i.status === 'downloading').length
    const waiting = items.filter((i) => i.status === 'waiting').length
    queueTitle.textContent = `${downloading} en cours, ${waiting} en attente`

    queueList.innerHTML = activeItems.map((item) => renderQueueItem(item)).join('')

    // Attach remove/cancel handlers
    queueList.querySelectorAll('[data-remove]').forEach((btn) => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.remove
            const item = state.queue.find((i) => i.id === id)

            // Optimistic removal: remove from UI immediately
            const el = document.getElementById(`item-${id}`)
            if (el) {
                el.style.opacity = '0.4'
                el.style.pointerEvents = 'none'
            }
            state.queue = state.queue.filter((i) => i.id !== id)
            updateCounts()

            await apiDelete(`/api/queue/${id}`)
        })
    })
}

function renderQueueItem(item) {
    const source = item.source || 'unknown'
    const statusLabels = {
        waiting: 'En attente',
        downloading: `${Math.round(item.progress)}%`,
        done: 'Terminé',
        error: 'Erreur',
    }

    const showProgress = item.status === 'downloading'
    const canRemove = item.status === 'waiting' || item.status === 'error' || item.status === 'downloading'

    const thumb = item.thumbnail
        ? `<img class="item-thumbnail" src="${escapeHtml(item.thumbnail)}" alt="" loading="lazy">`
        : `<div class="source-icon ${source}">${SOURCE_ICONS[source] || SOURCE_ICONS.unknown}</div>`

    return `<div class="download-item" id="item-${item.id}">
            <div class="download-item-top">
                ${thumb}
                <div class="download-info">
                    <div class="download-title" title="${escapeHtml(item.title)}">${escapeHtml(item.title)}</div>
                    <div class="download-meta">
                        <span class="status-pill ${item.status}">${statusLabels[item.status]}</span>
                        ${item.speed ? `<span>${item.speed}</span>` : ''}
                        ${item.eta ? `<span>ETA ${item.eta}</span>` : ''}
                        ${item.error ? `<span style="color:var(--error)">${escapeHtml(item.error)}</span>` : ''}
                    </div>
                </div>
                <div class="download-actions">
                    ${canRemove ? `<button class="btn-icon delete" data-remove="${item.id}" title="${item.status === 'downloading' ? 'Annuler' : 'Supprimer'}">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </button>` : ''}
                </div>
            </div>
            ${showProgress ? `
            <div class="progress-container">
                <div class="progress-bar">
                    <div class="progress-fill" id="progress-${item.id}" style="width: ${item.progress}%"></div>
                </div>
                <div class="progress-details">
                    <div class="progress-info">
                        ${item.phase_label ? `<span class="progress-phase">${escapeHtml(item.phase_label)}</span>` : ''}
                        ${item.filename ? `<span>${escapeHtml(item.filename)}</span>` : ''}
                    </div>
                    <span>${Math.round(item.progress)}%</span>
                </div>
            </div>` : ''}
        </div>`
}

function updateItemProgress(id, item) {
    const progressFill = $(`#progress-${id}`)
    if (progressFill) {
        progressFill.style.width = `${item.progress}%`
    }

    const el = $(`#item-${id}`)
    if (!el) return

    const meta = el.querySelector('.download-meta')
    if (meta && item.status === 'downloading') {
        const parts = [`<span class="status-pill downloading">${Math.round(item.progress)}%</span>`]
        if (item.speed) parts.push(`<span>${item.speed}</span>`)
        if (item.eta) parts.push(`<span>ETA ${item.eta}</span>`)
        meta.innerHTML = parts.join('')
    }

    const details = el.querySelector('.progress-details')
    if (details) {
        const phaseHtml = item.phase_label ? `<span class="progress-phase">${escapeHtml(item.phase_label)}</span>` : ''
        const fileHtml = item.filename ? `<span>${escapeHtml(item.filename)}</span>` : ''
        details.innerHTML = `<div class="progress-info">${phaseHtml}${fileHtml}</div><span>${Math.round(item.progress)}%</span>`
    }
}

// === Pop sound on download complete ===
const _popAudio = new Audio('/pop.mp3')
_popAudio.volume = 0.6
function playPop() {
    _popAudio.currentTime = 0
    _popAudio.play().catch(() => {})
}

// === Confetti burst when a download completes ===
function launchConfettiAt(rect) {
    // Create a dedicated full-page canvas with explicit z-index
    // (canvas-confetti's default canvas uses z-index 200 which can be hidden)
    const canvas = document.createElement('canvas')
    canvas.style.cssText = 'position:fixed;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:9999;'
    document.body.appendChild(canvas)

    const fire = confetti.create(canvas, { resize: true, useWorker: false })

    const cx = (rect.left + rect.width / 2) / window.innerWidth
    const cy = (rect.top + rect.height / 2) / window.innerHeight

    const base = {
        origin: { x: cx, y: cy },
        colors: ['#6c5ce7', '#a29bfe', '#27c93f', '#ffd93d', '#ff6b6b', '#74b9ff', '#fd79a8', '#00cec9', '#e17055'],
        gravity: 0.9,
        ticks: 100,
    }

    Promise.all([
        fire({ ...base, particleCount: 70, spread: 360, startVelocity: 32, scalar: 1.0 }),
        new Promise((res) =>
            setTimeout(
                () => fire({ ...base, particleCount: 40, spread: 140, startVelocity: 18, scalar: 0.7 }).then(res),
                110,
            ),
        ),
    ]).then(() => canvas.remove())
}

// === Render library ===
function renderLibrary() {
    const items = state.library

    if (items.length === 0) {
        libraryList.innerHTML = `
            <div class="empty-state">
                <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="var(--text-muted)" stroke-width="1.5" opacity="0.5">
                    <path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>
                </svg>
                <p>Aucun fichier téléchargé</p>
            </div>`
        libraryTitle.textContent = 'Bibliothèque'
        btnClearLibrary.classList.add('hidden')
        return
    }

    libraryTitle.textContent = `${items.length} fichier${items.length > 1 ? 's' : ''}`
    btnClearLibrary.classList.remove('hidden')

    // Group by day
    const groups = {}
    for (const item of items) {
        const key = item.completed_at ? item.completed_at.substring(0, 10) : 'unknown'
        if (!groups[key]) groups[key] = []
        groups[key].push(item)
    }

    const today = new Date().toISOString().substring(0, 10)
    const yesterday = new Date(Date.now() - 86400000).toISOString().substring(0, 10)

    function labelDay(key) {
        if (key === today) return "Aujourd'hui"
        if (key === yesterday) return 'Hier'
        if (key === 'unknown') return 'Date inconnue'
        const d = new Date(key + 'T12:00:00')
        return d.toLocaleDateString('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
    }

    const sortedKeys = Object.keys(groups).sort((a, b) =>
        a === 'unknown' ? 1 : b === 'unknown' ? -1 : b.localeCompare(a)
    )

    libraryList.innerHTML = sortedKeys.map(key => {
        const groupItems = groups[key]
        const ids = JSON.stringify(groupItems.map(i => i.id))
        const header = `<div class="library-date-header">
            <span>${labelDay(key)}</span>
            <div class="library-date-actions">
                <span class="library-date-count">${groupItems.length} fichier${groupItems.length > 1 ? 's' : ''}</span>
                <button class="btn-icon delete btn-delete-day" data-ids='${escapeHtml(ids)}' title="Effacer ce jour">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                        <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                    </svg>
                </button>
            </div>
        </div>`

        const itemsHtml = groupItems.map(item => {
            const source = item.source || 'library'
            const thumb = item.thumbnail
                ? `<img class="item-thumbnail" src="${escapeHtml(item.thumbnail)}" alt="" loading="lazy">`
                : `<div class="source-icon ${source}">${SOURCE_ICONS[source] || SOURCE_ICONS.library}</div>`

            return `<div class="download-item library-item">
                <div class="download-item-top">
                    ${thumb}
                    <div class="download-info">
                        <div class="download-title" title="${escapeHtml(item.filename || item.title)}">${escapeHtml(item.title || item.filename)}</div>
                        <div class="download-meta">
                            <span class="status-pill done">Terminé</span>
                            ${item.filename ? `<span>${escapeHtml(item.filename)}</span>` : ''}
                        </div>
                    </div>
                    <button class="btn btn-ghost btn-sm btn-open-folder" title="Ouvrir dans l'explorateur" data-id="${escapeHtml(item.id)}" style="margin-left:auto;flex-shrink:0">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                        </svg>
                    </button>
                </div>
            </div>`
        }).join('')

        return header + itemsHtml
    }).join('')
}

// === Update counts ===
function updateCounts() {
    const queueActive = state.queue.filter((i) => i.status !== 'done').length
    const libCount = state.library.length

    queueCountBadge.textContent = `${queueActive} en file`

    if (queueActive > 0) {
        tabQueueCount.textContent = queueActive
        tabQueueCount.classList.remove('hidden')
    } else {
        tabQueueCount.classList.add('hidden')
    }

    if (libCount > 0) {
        tabLibraryCount.textContent = libCount
        tabLibraryCount.classList.remove('hidden')
    } else {
        tabLibraryCount.classList.add('hidden')
    }
}

// === WebSocket message handler ===
function handleWSMessage(msg) {
    if (msg.type === 'state') {
        // Detect downloading →?'done transitions BEFORE re-render (for confetti)
        const doneIds = new Set((msg.queue || []).filter((i) => i.status === 'done').map((i) => i.id))
        const justCompleted = state.queue
            .filter((i) => i.status === 'downloading' && doneIds.has(i.id))
            .map((i) => {
                const el = document.getElementById(`item-${i.id}`)
                return el ? el.getBoundingClientRect() : null
            })
            .filter(Boolean)

        state.queue = msg.queue
        state.library = msg.library
        renderQueue()
        renderLibrary()
        updateCounts()

        // Fire confetti + pop sound at captured positions
        if (justCompleted.length > 0) playPop()
        for (const rect of justCompleted) launchConfettiAt(rect)

    } else if (msg.type === 'progress') {
        const item = state.queue.find((i) => i.id === msg.id)
        if (item) {
            // Monotonic: never allow the bar to go backwards in the UI
            item.progress = Math.max(item.progress || 0, msg.progress)
            item.speed = msg.speed
            item.eta = msg.eta
            if (msg.filename) item.filename = msg.filename
            if (msg.phase_label) item.phase_label = msg.phase_label
            if (msg.title && item.title !== msg.title) {
                item.title = msg.title
                const el = $(`#item-${msg.id}`)
                if (el) {
                    const titleEl = el.querySelector('.download-title')
                    if (titleEl) titleEl.textContent = msg.title
                }
            }
            updateItemProgress(msg.id, item)
        }
    }
}

async function refreshState() {
    try {
        const [queueRes, libraryRes] = await Promise.all([
            apiGet('/api/queue'),
            apiGet('/api/library'),
        ])
        state.queue = Array.isArray(queueRes.queue) ? queueRes.queue : []
        state.library = Array.isArray(libraryRes.library) ? libraryRes.library : []
        renderQueue()
        renderLibrary()
        updateCounts()
    } catch {
        // Keep the current UI state; websocket retry/bootstrap may still recover.
    }
}

// === Settings modal ===
async function openSettings() {
    const [res, startupRes] = await Promise.all([
        apiGet('/api/settings'),
        apiGet('/api/startup').catch(() => ({ enabled: false, supported: false })),
    ])
    $('#s-dl-dir').value = res.download_dir || ''
    $('#s-format').value = res.default_format || 'mp3'
    $('#s-quality').value = res.default_quality || '320'
    $('#s-samplerate').value = res.default_samplerate || '48000'
    const startupToggle = $('#s-startup')
    startupToggle.checked = !!startupRes.enabled
    startupToggle.disabled = !startupRes.supported
    $('#s-startup-msg').textContent = ''
    $('#settings-msg').textContent = ''
    $('#settings-msg').className = 'settings-msg'
    $$('.stab').forEach((b) => b.classList.remove('active'))
    $$('.stab-panel').forEach((p) => p.classList.add('hidden'))
    document.querySelector('button[data-stab="storage"]').classList.add('active')
    $('#stab-storage').classList.remove('hidden')
    settingsBackdrop.classList.remove('hidden')
}

function closeSettings() {
    settingsBackdrop.classList.add('hidden')
}


$('#s-dl-browse').addEventListener('click', async () => {
    const msgEl = $('#settings-msg')
    const btn = $('#s-dl-browse')
    const input = $('#s-dl-dir')
    const previous = btn.textContent
    btn.disabled = true
    btn.textContent = 'Ouverture...'
    msgEl.textContent = ''
    msgEl.className = 'settings-msg'
    try {
        const res = await apiPost('/api/settings/pick-folder', { current_dir: input.value.trim() })
        if (res.ok && res.path) {
            input.value = res.path
        } else if (!res.cancelled) {
            msgEl.textContent = res.detail || "Impossible d'ouvrir le selecteur de dossier"
            msgEl.className = 'settings-msg err'
        }
    } catch {
        msgEl.textContent = "Impossible d'ouvrir le selecteur de dossier"
        msgEl.className = 'settings-msg err'
    } finally {
        btn.disabled = false
        btn.textContent = previous
    }
})

$('#settings-close').addEventListener('click', closeSettings)
settingsBackdrop.addEventListener('click', (e) => { if (e.target === settingsBackdrop) closeSettings() })

$('#s-startup').addEventListener('change', async (e) => {
    const msgEl = $('#s-startup-msg')
    msgEl.textContent = ''
    msgEl.className = 'settings-msg'
    try {
        const res = await apiPost('/api/startup', { enabled: e.target.checked })
        if (res.ok) {
            msgEl.textContent = e.target.checked ? '✓ Activé' : '✓ Désactivé'
            msgEl.className = 'settings-msg ok'
        } else {
            e.target.checked = !e.target.checked
            msgEl.textContent = res.detail || 'Erreur'
            msgEl.className = 'settings-msg err'
        }
    } catch {
        e.target.checked = !e.target.checked
        msgEl.textContent = 'Erreur réseau'
        msgEl.className = 'settings-msg err'
    }
})

// Tab switching
$$('.stab').forEach(btn => {
    btn.addEventListener('click', () => {
        $$('.stab').forEach(b => b.classList.remove('active'))
        $$('.stab-panel').forEach(p => p.classList.add('hidden'))
        btn.classList.add('active')
        $(`#stab-${btn.dataset.stab}`).classList.remove('hidden')
    })
})

$('#settings-save').addEventListener('click', async () => {
    const msgEl = $('#settings-msg')
    const body = {
        download_dir: $('#s-dl-dir').value.trim(),
        default_format: $('#s-format').value,
        default_quality: $('#s-quality').value,
        default_samplerate: $('#s-samplerate').value,
    }
    const res = await apiPost('/api/settings', body)
    if (res.ok) {
        selFormat.value = body.default_format
        selQuality.value = body.default_quality
        selSamplerate.value = body.default_samplerate
        settings.format = body.default_format
        settings.quality = body.default_quality
        saveSettings()
        msgEl.textContent = '✓ Enregistré'
        msgEl.className = 'settings-msg ok'
        showToast('Paramètres sauvegardés', 'success')
    } else {
        msgEl.textContent = res.detail || 'Erreur'
        msgEl.className = 'settings-msg err'
    }
})



$$('[data-tab]').forEach((btn) => {
    btn.addEventListener('click', () => {
        $$('[data-tab]').forEach((tab) => tab.classList.remove('active'))
        $$('.panel').forEach((panel) => panel.classList.remove('active'))
        btn.classList.add('active')
        $(`#panel-${btn.dataset.tab}`).classList.add('active')
    })
})

btnSettingsOpen.addEventListener('click', openSettings)

async function initApp() {
    await refreshState()
    connectWS(handleWSMessage)
}

initApp()
