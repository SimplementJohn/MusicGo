/** WebSocket connection manager */

let ws = null
let reconnectTimer = null
let heartbeatInterval = null

export function connectWS(onMessage) {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${protocol}://${location.host}/ws`)

    ws.onopen = () => {
        if (reconnectTimer) {
            clearTimeout(reconnectTimer)
            reconnectTimer = null
        }
    }

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data)
        onMessage(msg)
    }

    ws.onclose = () => {
        clearInterval(heartbeatInterval)
        reconnectTimer = setTimeout(() => connectWS(onMessage), 2000)
    }

    ws.onerror = () => {
        ws.close()
    }

    // Heartbeat every 30s
    heartbeatInterval = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }))
        }
    }, 30000)
}
