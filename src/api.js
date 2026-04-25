/** API helper functions */

const getToken = () => localStorage.getItem('musicgo_token') || ''

async function parseJsonSafe(res) {
    const text = await res.text()
    if (!text) return {}
    try {
        return JSON.parse(text)
    } catch {
        return { error: text.slice(0, 200) }
    }
}

async function request(path, options = {}) {
    const headers = { 'X-Token': getToken(), ...(options.headers || {}) }
    if (options.body && !headers['Content-Type']) {
        headers['Content-Type'] = 'application/json'
    }
    let res
    try {
        res = await fetch(path, { ...options, headers })
    } catch (e) {
        // Erreur réseau: throw pour que les catchers UI affichent "serveur inaccessible"
        throw new Error('Serveur inaccessible')
    }
    const data = await parseJsonSafe(res)
    // Pas de throw sur 4xx/5xx: le body contient {error} ou {detail}.
    // Les callers lisent res.ok / res.error / res.detail comme avant.
    data._status = res.status
    data._ok = res.ok
    return data
}

export async function apiPost(path, body) {
    return request(path, { method: 'POST', body: JSON.stringify(body || {}) })
}

export async function apiDelete(path) {
    return request(path, { method: 'DELETE' })
}

export async function apiGet(path) {
    return request(path, { method: 'GET' })
}
