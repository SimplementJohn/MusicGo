/** Toast notification system */

export function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container')
    const toast = document.createElement('div')
    toast.className = `toast ${type}`
    toast.textContent = message
    container.appendChild(toast)
    setTimeout(() => {
        toast.style.animation = 'toastOut 0.3s ease forwards'
        setTimeout(() => toast.remove(), 300)
    }, 3500)
}
