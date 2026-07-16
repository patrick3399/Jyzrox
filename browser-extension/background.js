const IMAGE_MENU = 'jyzrox-send-image'
const URL_MENU = 'jyzrox-send-url'

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: IMAGE_MENU, title: 'Send image to Jyzrox', contexts: ['image'] })
  chrome.contextMenus.create({ id: URL_MENU, title: 'Send to Jyzrox', contexts: ['page', 'link'] })
})

async function settings() {
  const stored = await chrome.storage.sync.get({ baseUrl: '' })
  const baseUrl = String(stored.baseUrl || '').replace(/\/$/, '')
  if (!baseUrl) throw new Error('Set the Jyzrox URL in the extension options first.')
  return { baseUrl }
}

async function csrfHeader(baseUrl) {
  const cookie = await chrome.cookies.get({ url: baseUrl, name: 'csrf_token' })
  return cookie?.value ? { 'X-CSRF-Token': cookie.value } : {}
}

async function sendImage(url, pageUrl) {
  const { baseUrl } = await settings()
  const source = await fetch(url, { credentials: 'include' })
  if (!source.ok) throw new Error(`Image download failed: HTTP ${source.status}`)
  const blob = await source.blob()
  const pathname = new URL(url).pathname
  const filename = decodeURIComponent(pathname.split('/').pop() || 'web-clip.jpg')
  const form = new FormData()
  form.set('file', blob, filename)
  form.set('source_url', pageUrl || url)
  form.set('title', filename)
  const response = await fetch(`${baseUrl}/api/import/web-clip`, {
    method: 'POST',
    credentials: 'include',
    headers: await csrfHeader(baseUrl),
    body: form,
  })
  if (!response.ok) throw new Error(`Jyzrox import failed: HTTP ${response.status}`)
}

async function sendUrl(url) {
  const { baseUrl } = await settings()
  const response = await fetch(`${baseUrl}/api/download/quick`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(await csrfHeader(baseUrl)) },
    body: JSON.stringify({ url }),
  })
  if (!response.ok) throw new Error(`Jyzrox enqueue failed: HTTP ${response.status}`)
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const operation = info.menuItemId === IMAGE_MENU
    ? sendImage(info.srcUrl, tab?.url)
    : sendUrl(info.linkUrl || info.pageUrl || tab?.url)
  operation.then(
    () => chrome.notifications.create({ type: 'basic', iconUrl: chrome.runtime.getURL('icon.svg'), title: 'Jyzrox', message: 'Sent successfully.' }),
    (error) => chrome.notifications.create({ type: 'basic', iconUrl: chrome.runtime.getURL('icon.svg'), title: 'Jyzrox', message: error.message || String(error) }),
  )
})

chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage())
