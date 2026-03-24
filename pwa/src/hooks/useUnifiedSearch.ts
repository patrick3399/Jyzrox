'use client'

import { useState, useMemo, useEffect, useCallback, useRef } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { parseQuery, updateFilter } from '@/lib/queryParser'

export function useUnifiedSearch() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const [rawQuery, setRawQuery] = useState(searchParams.get('q') ?? '')
  const [inputValue, setInputValue] = useState(rawQuery)

  // Derived parsed filters
  const parsed = useMemo(() => parseQuery(rawQuery), [rawQuery])

  // URL sync (debounce 500ms)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      const params = new URLSearchParams()
      if (rawQuery) params.set('q', rawQuery)
      const qs = params.toString()
      router.replace(qs ? `/library?${qs}` : '/library', { scroll: false })
    }, 500)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [rawQuery, router])

  // Filter mutation (from UI dropdowns)
  const setFilter = useCallback((key: string, value: string | null) => {
    setRawQuery((prev) => {
      const updated = updateFilter(prev, key, value)
      setInputValue(updated)
      return updated
    })
  }, [])

  // Commit search from input (e.g. on Enter)
  const commitSearch = useCallback((value: string) => {
    setRawQuery(value)
  }, [])

  // Input change handler (doesn't commit until Enter)
  const handleInputChange = useCallback((value: string) => {
    setInputValue(value)
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
