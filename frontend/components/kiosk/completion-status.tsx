import { Timer } from "lucide-react"

interface CompletionStatusProps {
  completionSeconds: number | null
  readingMessage: string
  voiceError: string | null
}

export function CompletionStatus({
  completionSeconds,
  readingMessage,
  voiceError,
}: CompletionStatusProps) {
  const countdown =
    completionSeconds === null
      ? null
      : `La pantalla volverá al inicio en ${completionSeconds} segundos.`
  const messages = voiceError
    ? [voiceError, countdown]
    : [countdown ?? readingMessage]

  return (
    <p
      className={`flex items-center gap-2 text-sm ${
        voiceError ? "text-yellow-200/80" : "text-white/45"
      }`}
      role="status"
    >
      <Timer className="h-4 w-4 shrink-0" />
      {messages.filter(Boolean).join(" ")}
    </p>
  )
}
