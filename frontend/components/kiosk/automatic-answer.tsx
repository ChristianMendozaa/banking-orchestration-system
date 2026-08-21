"use client"

import type { FlowResult } from "@/lib/types"
import { CheckCircle, ExternalLink } from "lucide-react"

/**
 * An answer the kiosk found in the approved corpus, shown inside the conversation.
 *
 * There is deliberately no ticket here. A case and a closed ticket are still recorded on
 * the backend -- that is what the operational reporting counts -- but a person who asked
 * what time the branch opens did not ask to be put in a queue, and handing them a reference
 * number reads as the conversation being over when it is not.
 */
export function AutomaticAnswer({
  result,
  // False where the answer is already on screen as it is spoken -- the voice transcript
  // reveals it word by word, so restating it below would be the same text twice.
  showAnswer = true,
}: {
  result: FlowResult
  showAnswer?: boolean
}) {
  if (!result.response) return null

  return (
    <section
      aria-label="Respuesta del asistente"
      className="w-full max-w-3xl space-y-3"
    >
      <div
        className="rounded-3xl border border-green-400/25 bg-green-400/[.07] px-6 py-5"
        hidden={!showAnswer}
      >
        <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-green-300">
          <CheckCircle className="h-4 w-4" />
          Esta es mi orientación
        </p>
        <p className="mt-3 whitespace-pre-line leading-relaxed text-white/90">
          {result.response}
        </p>
      </div>

      {result.citations.length > 0 && (
        <details className="rounded-2xl border border-white/10 bg-white/[.04] px-5 py-4">
          <summary className="cursor-pointer text-sm font-semibold uppercase tracking-widest text-white/70">
            Información consultada
          </summary>
          <ul className="mt-3 space-y-2">
            {result.citations.map((citation) => (
              <li className="text-sm text-white/75" key={citation.chunk_id}>
                {citation.source_url ? (
                  <a
                    className="inline-flex items-center gap-2 text-[#7DD3FC] underline-offset-4 hover:underline"
                    href={citation.source_url}
                    rel="noreferrer"
                    target="_blank"
                  >
                    {citation.title}, página {citation.page}
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                ) : (
                  <span>
                    {citation.title}, página {citation.page}
                  </span>
                )}
                {citation.section && <span> · {citation.section}</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
