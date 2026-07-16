const input = document.querySelector('#baseUrl')
const status = document.querySelector('#status')

chrome.storage.sync.get({ baseUrl: '' }).then(({ baseUrl }) => { input.value = baseUrl })
document.querySelector('#save').addEventListener('click', async () => {
  const baseUrl = input.value.trim().replace(/\/$/, '')
  if (!/^https?:\/\//.test(baseUrl)) {
    status.textContent = 'Enter a valid HTTP(S) URL.'
    return
  }
  await chrome.storage.sync.set({ baseUrl })
  status.textContent = 'Saved.'
})
