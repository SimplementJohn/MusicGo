/** Utility functions */

export function escapeHtml(text) {
    const div = document.createElement('div')
    div.textContent = text || ''
    return div.innerHTML
}

export function formatDate(isoStr) {
    try {
        const d = new Date(isoStr)
        const now = new Date()
        const diff = now - d

        if (diff < 60000) return "A l'instant"
        if (diff < 3600000) return `Il y a ${Math.floor(diff / 60000)} min`
        if (diff < 86400000) return `Il y a ${Math.floor(diff / 3600000)}h`

        return d.toLocaleDateString('fr-FR', {
            day: 'numeric',
            month: 'short',
            hour: '2-digit',
            minute: '2-digit',
        })
    } catch {
        return ''
    }
}

export function detectSource(url) {
    const u = url.toLowerCase()
    if (u.includes('youtube.com') || u.includes('youtu.be')) return 'youtube'
    if (u.includes('spotify.com') || u.includes('open.spotify')) return 'spotify'
    if (u.includes('soundcloud.com')) return 'soundcloud'
    if (u.includes('tiktok.com') || u.includes('vm.tiktok')) return 'tiktok'
    if (u.includes('deezer.com') || u.includes('deezer.page')) return 'deezer'
    if (u.includes('music.apple.com')) return 'applemusic'
    if (/\.(mp3|flac|wav|ogg|aac|m4a|wma)(\?|$)/.test(u)) return 'direct'
    return 'unknown'
}
