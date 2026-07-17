"use client"

import { speak, useKiosk } from "@/components/providers/kiosk-provider"
import { Button } from "@/components/ui/button"
import { CheckCircle, ExternalLink, MessageSquare, Ticket } from "lucide-react"
import { useRouter } from "next/navigation"
import { useEffect } from "react"

export default function AutomaticResponsePage() {
  const { result, hydrated, reset } = useKiosk()
  const router = useRouter()

  useEffect(() => {
    if (hydrated && (!result || result.resolution_type !== "AUTOMATIC")) {
      router.replace("/kiosco")
      return
    }
    if (result) speak(result.speech_text)
  }, [hydrated, result, router])

  function finish() {
    reset()
    router.replace("/kiosco")
  }

  if (!result?.ticket || !result.response) return null

  return (
    <div className="flex flex-1 items-center justify-center px-5 py-10">
      <div className="flex w-full max-w-3xl flex-col items-center gap-7">
        <div className="text-center">
          <div className="mx-auto grid h-20 w-20 place-items-center rounded-full bg-green-500/15">
            <CheckCircle className="h-11 w-11 text-green-400" />
          </div>
          <h1 className="mt-4 text-3xl font-semibold text-green-300">
            Su consulta fue orientada
          </h1>
          <p className="mt-2 text-white/50">
            Respuesta basada en documentos de conocimiento indexados.
          </p>
        </div>

        <section className="flex w-full items-start gap-3">
          <div className="mt-1 grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#1168BD]">
            <MessageSquare className="h-5 w-5" />
          </div>
          <div className="flex-1 rounded-3xl rounded-tl-none border border-white/15 bg-white/[.08] px-6 py-5">
            <p className="text-xs font-semibold uppercase tracking-widest text-[#23A2D9]">
              Orientación automática fundamentada
            </p>
            <p className="mt-3 whitespace-pre-line leading-relaxed text-white/90">
              {result.response}
            </p>
          </div>
        </section>

        {result.citations.length > 0 && (
          <section className="w-full rounded-2xl border border-white/10 bg-white/[.04] p-5">
            <h2 className="text-sm font-semibold uppercase tracking-widest text-white/45">
              Fuentes utilizadas
            </h2>
            <ul className="mt-3 space-y-2">
              {result.citations.map((citation) => (
                <li className="text-sm text-white/65" key={citation.chunk_id}>
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
          </section>
        )}

        <div className="flex items-center gap-3 rounded-xl border border-white/15 bg-white/[.06] px-6 py-4">
          <Ticket className="h-5 w-5 text-[#23A2D9]" />
          <div>
            <p className="text-xs uppercase tracking-wide text-white/45">Referencia trazable</p>
            <p className="font-bold">Ticket #{result.ticket.number}</p>
          </div>
        </div>
        {result.tracking_information && (
          <p className="max-w-2xl text-center text-sm text-white/45">
            {result.tracking_information}
          </p>
        )}
        <Button onClick={finish} size="xl">
          Finalizar
        </Button>
      </div>
    </div>
  )
}
