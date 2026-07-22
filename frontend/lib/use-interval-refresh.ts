"use client"

import { useEffect, useRef } from "react"

export function useIntervalRefresh(callback: () => void, intervalMs?: number): void {
  const callbackRef = useRef(callback)

  useEffect(() => {
    callbackRef.current = callback
  }, [callback])

  useEffect(() => {
    if (!intervalMs) return
    const timer = window.setInterval(() => callbackRef.current(), intervalMs)
    return () => window.clearInterval(timer)
  }, [intervalMs])
}
