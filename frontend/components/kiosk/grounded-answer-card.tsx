import type { FlowResult } from "@/lib/types"
import { ExternalLink, MessageSquare } from "lucide-react"

export function GroundedAnswerCard({ result }: { result: FlowResult | null }) {
  if (result?.resolution_type !== "AUTOMATIC" || !result.response) return null

  return (
    <section className="w-full max-w-3xl space-y-4" aria-live="polite">
      <div className="flex items-start gap-3">
        <div className="mt-1 grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#1168BD]">
          <MessageSquare className="h-5 w-5" />
        </div>
        <div className="flex-1 rounded-3xl rounded-tl-none border border-white/15 bg-white/[.08] px-6 py-5">
          <p className="text-xs font-semibold uppercase tracking-widest text-[#23A2D9]">
            Orientación para ti
          </p>
          <p className="mt-3 whitespace-pre-line leading-relaxed text-white/90">
            {result.response}
          </p>
        </div>
      </div>

      {result.citations.length > 0 && (
        <div className="rounded-2xl border border-white/10 bg-white/[.04] p-5">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-white/70">
            Información consultada
          </h2>
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
        </div>
      )}

      <p className="text-center text-sm text-white/70">
        {result.conversation_can_continue
          ? `Puedes hacer otra consulta. Quedan ${result.remaining_turns} turnos en esta atención.`
          : "Esta atención llegó a su límite y se cerrará al terminar la respuesta."}
      </p>
    </section>
  )
}
