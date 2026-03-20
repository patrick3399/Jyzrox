/**
 * Decode a ThumbHash (base64) into an RGBA Uint8Array + width/height.
 * Ported from https://evanw.github.io/thumbhash/
 */
export function thumbHashToRGBA(base64: string): { w: number; h: number; rgba: Uint8Array } {
  const hash = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0))

  const header = hash[0] | (hash[1] << 8) | (hash[2] << 16)
  const l_dc = (header & 63) / 63
  const p_dc = ((header >> 6) & 63) / 31.5 - 1
  const q_dc = ((header >> 12) & 63) / 31.5 - 1
  const l_scale = ((header >> 18) & 31) / 31
  const hasAlpha = (header >> 23) & 1
  const p_scale = ((hash[3] >> 0) & 63) / 63
  const q_scale = ((hash[3] >> 6) | ((hash[4] << 2) & 0x3c)) / 31
  const a_dc = hasAlpha ? (hash[5] & 15) / 15 : 1
  const a_scale = hasAlpha ? ((hash[5] >> 4) & 15) / 15 : 0
  const isLandscape = (hash[4] >> 7) & 1
  const lx = Math.max(3, isLandscape ? (hasAlpha ? 5 : 7) : (hash[4] >> 4) & 7)
  const ly = Math.max(3, isLandscape ? (hash[4] >> 4) & 7 : hasAlpha ? 5 : 7)

  let i = hasAlpha ? 6 : 5
  let bit = 0

  function decodeDC(scale: number, n: number): number[] {
    const ac: number[] = []
    for (let j = 0; j < n; j++) {
      let data = 0
      for (let b = 0; b < 4; b++) {
        data |= ((hash[i] >> bit) & 1) << b
        bit++
        if (bit >= 8) {
          bit = 0
          i++
        }
      }
      ac.push(((data + 0.5) / 16 - 0.5) * scale)
    }
    return ac
  }

  const l_ac = decodeDC(l_scale, lx * ly - 1)
  const p_ac = decodeDC(p_scale, 3 * 3 - 1)
  const q_ac = decodeDC(q_scale, 3 * 3 - 1)
  const a_ac = hasAlpha ? decodeDC(a_scale, 5 * 5 - 1) : []

  const ratio = thumbHashToApproximateAspectRatio(hash)
  const w = Math.round(ratio > 1 ? 32 : 32 * ratio)
  const h = Math.round(ratio > 1 ? 32 / ratio : 32)

  const rgba = new Uint8Array(w * h * 4)

  const fx_l = new Float64Array(lx)
  const fx_p = new Float64Array(3)
  const fx_q = new Float64Array(3)
  const fx_a = hasAlpha ? new Float64Array(5) : null

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let l = l_dc,
        p = p_dc,
        q = q_dc,
        a = a_dc

      for (let cx = 0; cx < lx; cx++) fx_l[cx] = Math.cos((Math.PI / w) * (x + 0.5) * cx)
      for (let cx = 0; cx < 3; cx++) fx_p[cx] = Math.cos((Math.PI / w) * (x + 0.5) * cx)
      for (let cx = 0; cx < 3; cx++) fx_q[cx] = Math.cos((Math.PI / w) * (x + 0.5) * cx)
      if (fx_a) for (let cx = 0; cx < 5; cx++) fx_a[cx] = Math.cos((Math.PI / w) * (x + 0.5) * cx)

      for (let cy = 0; cy < ly; cy++) {
        const fy = Math.cos((Math.PI / h) * (y + 0.5) * cy)
        for (let cx = cy === 0 ? 1 : 0; cx < lx; cx++) l += l_ac[cy * lx + cx - 1] * fx_l[cx] * fy
      }

      for (let cy = 0; cy < 3; cy++) {
        const fy = Math.cos((Math.PI / h) * (y + 0.5) * cy)
        for (let cx = cy === 0 ? 1 : 0; cx < 3; cx++) {
          const f = fx_p[cx] * fy
          p += p_ac[cy * 3 + cx - 1] * f
          q += q_ac[cy * 3 + cx - 1] * f
        }
      }

      if (fx_a) {
        for (let cy = 0; cy < 5; cy++) {
          const fy = Math.cos((Math.PI / h) * (y + 0.5) * cy)
          for (let cx = cy === 0 ? 1 : 0; cx < 5; cx++) a += a_ac[cy * 5 + cx - 1] * fx_a[cx] * fy
        }
      }

      const b = l - (2 / 3) * p
      const r = (3 * l - b + q) / 2
      const g = r - q

      const idx = (y * w + x) * 4
      rgba[idx] = Math.max(0, Math.min(255, Math.round(255 * r)))
      rgba[idx + 1] = Math.max(0, Math.min(255, Math.round(255 * g)))
      rgba[idx + 2] = Math.max(0, Math.min(255, Math.round(255 * b)))
      rgba[idx + 3] = Math.max(0, Math.min(255, Math.round(255 * a)))
    }
  }

  return { w, h, rgba }
}

function thumbHashToApproximateAspectRatio(hash: Uint8Array): number {
  const header = hash[0] | (hash[1] << 8) | (hash[2] << 16)
  const hasAlpha = (header >> 23) & 1
  const isLandscape = (hash[4] >> 7) & 1
  const lx = Math.max(3, isLandscape ? (hasAlpha ? 5 : 7) : (hash[4] >> 4) & 7)
  const ly = Math.max(3, isLandscape ? (hash[4] >> 4) & 7 : hasAlpha ? 5 : 7)
  return lx / ly
}

/**
 * Draw a thumbhash onto a canvas element.
 * Returns a data URL or null if decoding fails.
 */
export function thumbHashToDataURL(base64: string): string | null {
  try {
    const { w, h, rgba } = thumbHashToRGBA(base64)
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    const imageData = ctx.createImageData(w, h)
    imageData.data.set(rgba)
    ctx.putImageData(imageData, 0, 0)
    return canvas.toDataURL()
  } catch {
    return null
  }
}
