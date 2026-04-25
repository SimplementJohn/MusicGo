;(function () {
    'use strict'

    const MUSICGO_URL = 'http://localhost:3000'
    let popup = null
    let injected = false

    // ── Helpers ──────────────────────────────────────────────────────────────

    function isWatchPage() {
        return location.pathname === '/watch' && location.search.includes('v=')
    }

    function getVideoInfo() {
        const title =
            document.querySelector('ytd-watch-metadata h1 yt-formatted-string')?.textContent?.trim() ||
            document.querySelector('#above-the-fold #title h1 yt-formatted-string')?.textContent?.trim() ||
            document.title.replace(/\s*[-–—|]\s*YouTube\s*$/, '').trim() ||
            'Vidéo YouTube'
        return { url: location.href, title }
    }

    function esc(s) {
        return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')
    }

    // ── Find action buttons row (below video title) ───────────────────────────

    function getActionTarget() {
        return (
            document.querySelector('ytd-watch-metadata #top-level-buttons-computed') ||
            document.querySelector('#below ytd-menu-renderer #top-level-buttons-computed') ||
            document.querySelector('#above-the-fold ytd-menu-renderer #top-level-buttons-computed')
        )
    }

    // ── Action button (styled like YouTube's "Partager") ──────────────────────

    function createNavBtn() {
        const btn = document.createElement('button')
        btn.id = 'musicgo-nav-btn'
        btn.title = 'Télécharger avec MusicGo'
        btn.innerHTML = `
            <span class="mg-btn-icon">
                <svg viewBox="0 0 40 40" width="16" height="16">
                    <circle cx="20" cy="20" r="18" fill="none" stroke="currentColor" stroke-width="2.5"/>
                    <circle cx="20" cy="20" r="6" fill="currentColor"/>
                    <path d="M26 12 L26 24" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>
                    <path d="M26 12 L32 10 L32 16 L26 18" fill="currentColor" opacity="0.9"/>
                </svg>
            </span>
            <span class="mg-btn-label">MusicGo</span>`
        return btn
    }

    // ── Popup ─────────────────────────────────────────────────────────────────

    function buildPopup() {
        const { url, title } = getVideoInfo()
        const el = document.createElement('div')
        el.id = 'musicgo-popup'

        // Position popup always above the button
        const btn = document.getElementById('musicgo-nav-btn')
        if (btn) {
            const rect = btn.getBoundingClientRect()
            el.style.top       = (rect.top - 8 + window.scrollY) + 'px'
            el.style.left      = rect.left + 'px'
            el.style.transform = 'translateY(-100%)'
        }

        el.innerHTML = `
            <div class="mg-header">
                <svg viewBox="0 0 40 40" width="18" height="18">
                    <circle cx="20" cy="20" r="18" fill="none" stroke="#a78bfa" stroke-width="2.5"/>
                    <circle cx="20" cy="20" r="6" fill="#a78bfa"/>
                    <path d="M26 12 L26 24" stroke="#a78bfa" stroke-width="2.5" stroke-linecap="round"/>
                    <path d="M26 12 L32 10 L32 16 L26 18" fill="#a78bfa" opacity="0.8"/>
                </svg>
                <span>MusicGo</span>
                <button class="mg-close">✕</button>
            </div>
            <div class="mg-title" title="${esc(title)}">${esc(title)}</div>
            <div class="mg-row">
                <label>Format</label>
                <select id="mg-format">
                    <option value="mp3" selected>MP3</option>
                    <option value="flac">FLAC</option>
                    <option value="m4a">M4A</option>
                    <option value="opus">OPUS</option>
                </select>
            </div>
            <div class="mg-row">
                <label>Qualité</label>
                <select id="mg-quality">
                    <option value="320" selected>320 kbps</option>
                    <option value="256">256 kbps</option>
                    <option value="192">192 kbps</option>
                    <option value="128">128 kbps</option>
                </select>
            </div>
            <button class="mg-dl-btn" id="mg-dl-btn">
                <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.5">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="7 10 12 15 17 10"/>
                    <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
                Télécharger
            </button>

            <div id="mg-status"></div>`

        el.querySelector('.mg-close').addEventListener('click', closePopup)

        el.querySelector('#mg-dl-btn').addEventListener('click', () => {
            const format   = el.querySelector('#mg-format').value
            const quality  = el.querySelector('#mg-quality').value
            const statusEl = el.querySelector('#mg-status')
            const dlBtn    = el.querySelector('#mg-dl-btn')

            dlBtn.disabled    = true
            dlBtn.textContent = 'Envoi…'
            statusEl.textContent = ''
            statusEl.className   = ''

            chrome.runtime.sendMessage(
                { type: 'musicgo_download', url, format, quality },
                (response) => {
                    dlBtn.disabled = false
                    dlBtn.innerHTML = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.5">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                        <polyline points="7 10 12 15 17 10"/>
                        <line x1="12" y1="15" x2="12" y2="3"/>
                    </svg> Télécharger`
                    if (response?.success) {
                        statusEl.textContent = '✓ Ajouté à la file MusicGo !'
                        statusEl.className   = 'mg-success'
                    } else {
                        statusEl.textContent = response?.error || 'Erreur — MusicGo est-il lancé ?'
                        statusEl.className   = 'mg-error'
                    }
                }
            )
        })

        return el
    }

    function closePopup() {
        popup?.remove()
        popup = null
    }

    function togglePopup() {
        if (popup) { closePopup(); return }
        popup = buildPopup()
        document.documentElement.appendChild(popup)
    }

    // Close popup on outside click
    document.addEventListener('click', (e) => {
        if (popup && !popup.contains(e.target) && e.target.closest('#musicgo-nav-btn') === null) closePopup()
    }, true)

    // ── Injection ─────────────────────────────────────────────────────────────

    function tryInject() {
        if (!isWatchPage()) {
            document.getElementById('musicgo-nav-btn')?.remove()
            closePopup()
            injected = false
            return
        }

        if (document.getElementById('musicgo-nav-btn')) { injected = true; return }

        const target = getActionTarget()
        if (!target) return

        const btn = createNavBtn()
        btn.addEventListener('click', (e) => { e.stopPropagation(); e.preventDefault(); togglePopup() })

        // Insert as first button in the action bar
        target.insertBefore(btn, target.firstChild)
        injected = true
    }

    // ── SPA navigation ───────────────────────────────────────────────────────

    let lastUrl = location.href
    let pollTimer = null

    window.addEventListener('yt-navigate-finish', () => {
        lastUrl = location.href
        injected = false
        document.getElementById('musicgo-nav-btn')?.remove()
        closePopup()
        setTimeout(tryInject, 800)
    })

    new MutationObserver(() => {
        if (location.href !== lastUrl) {
            lastUrl = location.href
            injected = false
            clearTimeout(pollTimer)
            pollTimer = setTimeout(tryInject, 600)
        }
    }).observe(document.documentElement, { childList: true, subtree: true })

    // Initial injection with retry
    function initialInject(attempts = 0) {
        tryInject()
        if (!injected && attempts < 20) {
            setTimeout(() => initialInject(attempts + 1), 500)
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => initialInject())
    } else {
        initialInject()
    }
})()
