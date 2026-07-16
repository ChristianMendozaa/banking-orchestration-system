'use client'

import { useState, useEffect } from 'react'

export function Clock() {
  const [time, setTime] = useState('')
  const [date, setDate] = useState('')

  useEffect(() => {
    const update = () => {
      const now = new Date()
      setTime(
        now.toLocaleTimeString('es-BO', {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        })
      )
      setDate(
        now.toLocaleDateString('es-BO', {
          weekday: 'long',
          year: 'numeric',
          month: 'long',
          day: 'numeric',
        })
      )
    }
    update()
    const id = setInterval(update, 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="text-center">
      <p className="text-6xl font-bold text-white tabular-nums tracking-tight">{time}</p>
      <p className="text-lg text-white/60 mt-2 capitalize">{date}</p>
    </div>
  )
}
