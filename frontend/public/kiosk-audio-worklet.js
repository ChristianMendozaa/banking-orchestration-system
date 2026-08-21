// Audio for the kiosk's spoken channel, in both directions.
//
// Everything here is PCM16 mono at 24 kHz, which is what the transcription session accepts
// and what the text-to-speech model returns. One format end to end means no resampling and
// no decoder: bytes off the socket go straight to the speaker, and a stream cut short by an
// interruption is still playable up to the cut.

// Everything on the wire is 24 kHz, whatever the audio hardware happens to run at.
const TARGET_RATE = 24000

// The rate this context actually got. The page asks for 24 kHz so that no resampling is
// needed, but a browser is free to ignore that and hand back the hardware rate instead --
// and then 24 kHz samples clocked at 48 kHz play at twice the speed and an octave up, while
// the microphone labels 48 kHz audio as 24 kHz on its way to the recogniser. Reading the rate
// back rather than trusting the request is what turns that from a silent corruption into a
// conversion. When the request was honoured, `RATE_RATIO` is exactly 1 and every cursor below
// advances in whole samples, as it always did.
const CONTEXT_RATE =
  typeof sampleRate === "number" && sampleRate > 0 ? sampleRate : TARGET_RATE
const RATE_RATIO = CONTEXT_RATE / TARGET_RATE

// 20 ms at 24 kHz. Small enough that turn detection reacts promptly, large enough that the
// socket is not carrying a message per render quantum.
const FRAME_SAMPLES = 480

// Roughly 50 ms at 24 kHz with 128-sample quanta. The main thread drives the on-screen text
// from these reports, so they have to be frequent enough to read as speech and rare enough
// not to flood the message port.
const PROGRESS_INTERVAL_SAMPLES = 1200

// 250 ms at 24 kHz. Speech is generated far faster than it plays, so this fills almost
// immediately; what it buys is a cushion for the moments it does not. Without one, playback
// began on the first frame to arrive and any hitch anywhere -- a late websocket frame, a
// React render holding the main thread past the next quantum -- landed as digital silence in
// the middle of a word. A quarter of a second of lead is inaudible at the start of a sentence
// and covers a hitch that otherwise chops it.
const PREROLL_SAMPLES = 6000

class KioskMicProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.pending = new Int16Array(FRAME_SAMPLES)
    this.filled = 0
    // Where in the incoming quantum the next outgoing sample comes from. Fractional only
    // when the context is not running at 24 kHz; it carries across quanta so a conversion
    // that lands mid-sample does not restart, which would put a click at every boundary.
    this.cursor = 0
  }

  process(inputs) {
    const channel = inputs[0]?.[0]
    if (!channel) return true

    while (this.cursor < channel.length) {
      // Clamp before scaling: a sample above 1.0 would wrap to a loud negative otherwise,
      // which the recogniser hears as a click.
      const sample = Math.max(-1, Math.min(1, channel[Math.floor(this.cursor)]))
      this.pending[this.filled] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
      this.filled += 1
      this.cursor += RATE_RATIO

      if (this.filled === FRAME_SAMPLES) {
        const frame = this.pending.slice()
        this.port.postMessage(frame.buffer, [frame.buffer])
        this.filled = 0
      }
    }
    this.cursor -= channel.length
    return true
  }
}

/**
 * The speaker side, and the only place in the system that knows what a person actually
 * heard.
 *
 * Speech arrives far faster than it plays -- a fifteen-second line lands here in well under
 * a second -- so "the last byte was sent" says nothing about whether the line was heard.
 * Everything downstream of that mistake (text that runs ahead of the voice, an audio context
 * torn down over a full queue, a barge-in that flushes the wrong line) is fixed by the two
 * things this processor now does: it keeps the queue split per line, and it reports back.
 */
class KioskPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    // Items are either { speechId, samples } or { speechId, end: true }. The end marker is
    // what lets this side tell "the line finished" from "the next chunk has not arrived
    // yet", which is not knowable from the queue being empty.
    this.queue = []
    this.offset = 0
    this.played = new Map()
    this.queued = new Map()
    this.sinceReport = 0
    this.empty = true
    // Lines whose end marker has arrived, and lines that have started playing. Between them
    // they answer "may this line start?" -- it may once it has a cushion, or once the whole
    // of it is here and there is nothing left to wait for.
    this.ended = new Set()
    this.started = new Set()
    // Lines that have received audio and not yet been retired. An empty queue means nothing
    // is *ready*, which is not the same as nothing being *owed*; this is what tells the two
    // apart.
    this.open = new Set()
    this.port.onmessage = (event) => this.receive(event.data)
  }

  receive(message) {
    if (!message || typeof message !== "object") return
    if (message.type === "chunk") {
      const samples = new Int16Array(message.buffer)
      this.queue.push({ speechId: message.speechId, samples })
      this.queued.set(
        message.speechId,
        (this.queued.get(message.speechId) ?? 0) + samples.length,
      )
      this.empty = false
      this.open.add(message.speechId)
      return
    }
    if (message.type === "end") {
      this.queue.push({ speechId: message.speechId, end: true })
      this.ended.add(message.speechId)
      return
    }
    if (message.type === "flush") {
      this.flush(message.speechId ?? null)
    }
  }

  /**
   * Barge-in. Dropping the queue rather than fading it out is deliberate: the customer has
   * started talking, and the kiosk finishing its sentence over them is the behaviour this
   * whole channel exists to avoid.
   *
   * `speechId` scopes it to one line. A cancel for a line that already finished streaming
   * used to wipe the queue wholesale, which silenced the line *after* it -- the one the
   * customer was waiting for.
   */
  flush(speechId) {
    const head = this.queue[0]
    const dropped = new Set()
    if (speechId === null) {
      for (const item of this.queue) dropped.add(item.speechId)
      for (const id of this.open) dropped.add(id)
      this.queue = []
    } else {
      this.queue = this.queue.filter((item) => {
        if (item.speechId !== speechId) return true
        dropped.add(item.speechId)
        return false
      })
      // A line whose audio has all been played but whose end marker is still in flight owns
      // nothing in the queue and would survive the filter above -- and then keep the player
      // from ever reporting itself drained, because it is still owed an ending that the
      // cancellation means will never come.
      if (this.open.has(speechId)) dropped.add(speechId)
    }
    if (this.queue[0] !== head) this.offset = 0
    for (const id of dropped) this.endLine(id, true)
    this.report()
  }

  addPlayed(speechId, speakerSamples) {
    // Converted back to source samples: the counters are compared against how much of the
    // line arrived, which is measured at 24 kHz however fast the speaker is running.
    const count = speakerSamples / RATE_RATIO
    this.played.set(speechId, (this.played.get(speechId) ?? 0) + count)
    this.sinceReport += count
  }

  endLine(speechId, cancelled) {
    this.played.delete(speechId)
    this.queued.delete(speechId)
    this.ended.delete(speechId)
    this.started.delete(speechId)
    this.open.delete(speechId)
    this.port.postMessage({ type: "ended", speechId, cancelled })
  }

  report() {
    this.sinceReport = 0
    for (const [speechId, playedSamples] of this.played) {
      this.port.postMessage({
        type: "progress",
        speechId,
        playedSamples,
        queuedSamples: this.queued.get(speechId) ?? playedSamples,
      })
    }
  }

  /**
   * Whether a line that has not started yet has enough of itself here to begin.
   *
   * Either a cushion, or the whole line: a sentence shorter than the pre-roll would other-
   * wise wait for audio that is never coming.
   */
  readyToStart(speechId) {
    if (this.ended.has(speechId)) return true
    const queued = this.queued.get(speechId) ?? 0
    const played = this.played.get(speechId) ?? 0
    return queued - played >= PREROLL_SAMPLES
  }

  process(_inputs, outputs) {
    const output = outputs[0][0]
    if (!output) return true

    // Samples emitted in this quantum, batched per line so the counters are touched once
    // rather than once per sample.
    let runId = null
    let runCount = 0

    for (let index = 0; index < output.length; index += 1) {
      let item = this.queue[0]
      while (item && item.end) {
        if (runCount) {
          this.addPlayed(runId, runCount)
          runId = null
          runCount = 0
        }
        this.queue.shift()
        this.offset = 0
        this.endLine(item.speechId, false)
        item = this.queue[0]
      }
      if (!item) {
        output[index] = 0
        continue
      }
      // Priming. Hold a line that has not started until it has a cushion, emitting silence
      // rather than the first fragment to arrive. Only lines that have not started are held:
      // once a sentence is being spoken a late frame is a gap to ride out, and pausing to
      // rebuild the buffer mid-word would sound worse than the gap it avoided. The check
      // lives here rather than above the loop so the line *after* an interruption gets the
      // same cushion the first one did.
      if (!this.started.has(item.speechId)) {
        if (!this.readyToStart(item.speechId)) {
          for (; index < output.length; index += 1) output[index] = 0
          break
        }
        this.started.add(item.speechId)
      }
      if (item.speechId !== runId) {
        if (runCount) this.addPlayed(runId, runCount)
        runId = item.speechId
        runCount = 0
      }
      output[index] = item.samples[Math.floor(this.offset)] / 0x8000
      this.offset += 1 / RATE_RATIO
      runCount += 1
      if (this.offset >= item.samples.length) {
        this.queue.shift()
        this.offset = 0
      }
    }
    if (runCount) this.addPlayed(runId, runCount)

    if (this.sinceReport >= PROGRESS_INTERVAL_SAMPLES) this.report()
    // The edge, not the level: the main thread waits on this before it is allowed to close
    // the audio context, so it must fire exactly once per drain.
    //
    // `open` is the half that was missing. An empty queue used to be read as "everything has
    // been said", but it is equally the sound of the next frame not having arrived yet --
    // and every consumer of this message treats it as the end of speech: captions stop
    // deferring, the pending server state is applied, and every waiter on `drain()` resolves,
    // which is what let a follow-up window start counting down while the customer was still
    // being spoken to. A line is only finished when its end marker has been consumed.
    if (this.queue.length === 0 && this.open.size === 0 && !this.empty) {
      this.empty = true
      this.report()
      this.port.postMessage({ type: "drained" })
    }
    return true
  }
}

registerProcessor("kiosk-mic", KioskMicProcessor)
registerProcessor("kiosk-player", KioskPlayerProcessor)
