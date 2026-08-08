'use client'

import { useState, useMemo, useEffect, useCallback, useRef } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { libraryBrowseIdentityKey } from '@/lib/browse/library'
import { parseQuery, updateFilter } from '@/lib/queryParser'

export function useUnifiedSearch() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const inputDebounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const incomingQuery = searchParams.get('q') ?? ''
  const lastUrlQueryRef = useRef(incomingQuery)
  const hasOutboundIntentRef = useRef(false)

  const [rawQuery, setRawQuery] = useState(incomingQuery)
  const [inputValue, setInputValue] = useState(rawQuery)

  // Derived parsed filters
  const parsed = useMemo(() => parseQuery(rawQuery), [rawQuery])

  // Browser history is authoritative. It also cancels local work that was
  // waiting to update the URL so an old debounce cannot overwrite back/forward.
  useEffect(() => {
    if (incomingQuery === lastUrlQueryRef.current) return
    lastUrlQueryRef.current = incomingQuery
    hasOutboundIntentRef.current = false
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (inputDebounceRef.current) clearTimeout(inputDebounceRef.current)
    setRawQuery(incomingQuery)
    setInputValue(incomingQuery)
  }, [incomingQuery])

  // Only explicit local mutations own an outbound URL update. Mount and
  // incoming URL synchronization must never echo back through router.replace.
  useEffect(() => {
    if (!hasOutboundIntentRef.current) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      hasOutboundIntentRef.current = false
      if (
        libraryBrowseIdentityKey(rawQuery) === libraryBrowseIdentityKey(lastUrlQueryRef.current)
      ) {
        return
      }
      const params = new URLSearchParams()
      if (rawQuery) params.set('q', rawQuery)
      const qs = params.toString()
      lastUrlQueryRef.current = rawQuery
      router.replace(qs ? `/library?${qs}` : '/library', { scroll: false })
    }, 500)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [rawQuery, router])

  // Filter mutation (from UI dropdowns)
  const setFilter = useCallback((key: string, value: string | null) => {
    hasOutboundIntentRef.current = true
    setRawQuery((prev) => {
      const updated = updateFilter(prev, key, value)
      setInputValue(updated)
      return updated
    })
  }, [])

  // Commit search from input (e.g. on Enter)
  const commitSearch = useCallback((value: string) => {
    if (inputDebounceRef.current) clearTimeout(inputDebounceRef.current)
    hasOutboundIntentRef.current = true
    setRawQuery(value)
  }, [])

  // Input change handler. Debounced commit keeps clearing/searching responsive
  // without requiring Enter after every edit.
  const handleInputChange = useCallback((value: string) => {
    setInputValue(value)
    if (inputDebounceRef.current) clearTimeout(inputDebounceRef.current)
    inputDebounceRef.current = setTimeout(() => {
      hasOutboundIntentRef.current = true
      setRawQuery(value)
    }, 300)
  }, [])

  useEffect(() => {
    return () => {
      if (inputDebounceRef.current) clearTimeout(inputDebounceRef.current)
    }
  }, [])

  // Select mode state (not stored in query)
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  return {
    rawQuery,
    inputValue,
    parsed,
    setFilter,
    commitSearch,
    handleInputChange,
    selectMode,
    setSelectMode,
    selectedIds,
    setSelectedIds,
  }
}
