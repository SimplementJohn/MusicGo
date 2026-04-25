// MusicGo background service worker
// Handles API calls from content.js (bypasses CORS restrictions)

const MUSICGO = 'http://localhost:8080'

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type !== 'musicgo_download') return

    const { url, format, quality } = msg

    fetch(`${MUSICGO}/api/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url })
    })
    .then(r => {
        if (!r.ok) throw new Error(`Serveur MusicGo introuvable (${r.status})`)
        return r.json()
    })
    .then(data => {
        if (!data.tracks || data.tracks.length === 0) throw new Error('Aucune piste trouvée')
        return fetch(`${MUSICGO}/api/queue/add`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tracks: data.tracks, format, quality, samplerate: '0' })
        })
    })
    .then(r => r.json())
    .then(() => sendResponse({ success: true }))
    .catch(err => sendResponse({ success: false, error: err.message }))

    return true // keep message channel open for async
})
