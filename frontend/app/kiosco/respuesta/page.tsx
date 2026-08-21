"use client"

import { CompletionStatus } from "@/components/kiosk/completion-status"
import { useKiosk } from "@/components/providers/kiosk-provider"
import { MessageSquare, XCircle } from "lucide-react"

/**
 * The one thing the kiosk says that ends the conversation without a case: a request it has
 * no way to serve at all.
 *
 * A question it *did* answer no longer lands here. That used to be a screen of its own with
 * a ticket number and a countdown, which told someone who asked about branch hours that
 * their visit was over; the answer is now part of the conversation they were already having.
 */
export default function DeclinedRequestPage() {
  const { analysis, voiceError, completionSeconds } = useKiosk()

  if (analysis?.next_action !== "DECLINE") return null

  return (
    <div className="flex flex-1 items-center justify-center px-5 py-10">
      <div className="flex w-full max-w-3xl flex-col items-center gap-7">
        <div className="text-center">
          <div className="mx-auto grid h-20 w-20 place-items-center rounded-full bg-white/10">
            <XCircle className="h-11 w-11 text-white/70" />
          </div>
          <h1 className="mt-4 text-3xl font-semibold text-white">
            No puedo ayudarte con eso aquí
          </h1>
        </div>

        <section className="flex w-full items-start gap-3">
          <div className="mt-1 grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#1168BD]">
            <MessageSquare className="h-5 w-5" />
          </div>
          <div className="flex-1 rounded-3xl rounded-tl-none border border-white/15 bg-white/[.08] px-6 py-5">
            <p className="whitespace-pre-line leading-relaxed text-white/90">
              {analysis.speech_text}
            </p>
          </div>
        </section>

        <CompletionStatus
          completionSeconds={completionSeconds}
          readingMessage="Estoy leyendo esta respuesta."
          voiceError={voiceError}
        />
      </div>
    </div>
  )
}
