import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"

// The worklet runs in a scope of its own with no module system, so the test supplies the two
// globals it is written against and reads back what it registers.
type Processor = {
  posted: unknown[]
  port: { onmessage: ((event: { data: unknown }) => void) | null }
  process: (inputs: unknown[], outputs: Float32Array[][]) => boolean
}

const registered = new Map<string, new () => Processor>()

class StubAudioWorkletProcessor {
  posted: unknown[] = []
  port: {
    onmessage: ((event: { data: unknown }) => void) | null
    postMessage: (data: unknown) => void
  }

  constructor() {
    this.port = {
      onmessage: null,
      postMessage: (data: unknown) => this.posted.push(data),
    }
  }
}

beforeAll(async () => {
  vi.stubGlobal("AudioWorkletProcessor", StubAudioWorkletProcessor)
  vi.stubGlobal("registerProcessor", (name: string, ctor: new () => Processor) => {
    registered.set(name, ctor)
  })
  // @ts-expect-error -- a worklet is a script, not a module: it has no exports and
  // registers its processors as a side effect of being loaded, exactly as the browser
  // loads it from `/kiosk-audio-worklet.js`.
  await import("../public/kiosk-audio-worklet.js")
})

/** One line's worth of PCM16 at a constant amplitude, so the source is audible in the output. */
function pcm(value: number, length: number): ArrayBuffer {
  const samples = new Int16Array(length)
  samples.fill(Math.round(value * 0x8000))
  return samples.buffer
}

let player: Processor
let send: (message: Record<string, unknown>) => void

beforeEach(() => {
  player = new (registered.get("kiosk-player")!)()
  send = (message) => player.port.onmessage!({ data: message })
})

function render(frames = 1): Float32Array {
  const channel = new Float32Array(128 * frames)
  for (let frame = 0; frame < frames; frame += 1) {
    const slice = new Float32Array(128)
    player.process([], [[slice]])
    channel.set(slice, frame * 128)
  }
  return channel
}

describe("kiosk-player", () => {
  it("keeps the line queued behind an interrupted one", () => {
    // The bug this exists to prevent: a `speech.cancel` for a line that had already
    // finished streaming used to empty the whole queue, silencing the sentence the customer
    // was actually waiting for -- the ticket, right after they typed their CI.
    send({ type: "chunk", speechId: "a", buffer: pcm(0.5, 128) })
    send({ type: "end", speechId: "a" })
    send({ type: "chunk", speechId: "b", buffer: pcm(-0.5, 128) })
    send({ type: "end", speechId: "b" })
    send({ type: "flush", speechId: "a" })

    expect(render()[0]).toBeCloseTo(-0.5, 3)
  })

  it("restarts cleanly when the line being played is the one dropped", () => {
    send({ type: "chunk", speechId: "a", buffer: pcm(0.5, 256) })
    send({ type: "end", speechId: "a" })
    render()
    send({ type: "chunk", speechId: "b", buffer: pcm(-0.5, 128) })
    send({ type: "end", speechId: "b" })
    send({ type: "flush", speechId: "a" })

    // Half-way through `a` when it was dropped, so `b` has to start from its own first
    // sample rather than inheriting the offset.
    expect(render()[0]).toBeCloseTo(-0.5, 3)
  })

  it("reports a line as ended only once its last sample has been heard", () => {
    send({ type: "chunk", speechId: "a", buffer: pcm(0.5, 64) })
    send({ type: "end", speechId: "a" })

    render()

    expect(player.posted).toContainEqual({
      type: "ended",
      speechId: "a",
      cancelled: false,
    })
    expect(player.posted).toContainEqual({ type: "drained" })
  })

  it("announces a dropped line as cancelled, so its text stops where it was cut", () => {
    send({ type: "chunk", speechId: "a", buffer: pcm(0.5, 128) })
    send({ type: "end", speechId: "a" })
    send({ type: "flush", speechId: "a" })

    expect(player.posted).toContainEqual({
      type: "ended",
      speechId: "a",
      cancelled: true,
    })
  })

  it("reports how much of a line has been heard, which paces the text on screen", () => {
    send({ type: "chunk", speechId: "a", buffer: pcm(0.5, 24_000) })
    render(12)

    const progress = player.posted.filter(
      (message) => (message as { type: string }).type === "progress",
    ) as { speechId: string; playedSamples: number; queuedSamples: number }[]
    expect(progress.length).toBeGreaterThan(0)
    expect(progress.at(-1)).toMatchObject({ speechId: "a", queuedSamples: 24_000 })
    expect(progress.at(-1)!.playedSamples).toBeGreaterThanOrEqual(1_200)
    expect(progress.at(-1)!.playedSamples).toBeLessThanOrEqual(12 * 128)
  })

  it("waits for a cushion before starting a line, rather than playing the first fragment", () => {
    // Playback used to begin on the first frame to arrive, so any hitch between then and the
    // next one -- a late websocket frame, a React render holding the main thread -- was
    // silence in the middle of a word. A line now waits until it has enough of itself to ride
    // one out.
    send({ type: "chunk", speechId: "a", buffer: pcm(0.5, 128) })

    expect(render()[0]).toBe(0)

    // Once the cushion is there it plays, from its own first sample.
    send({ type: "chunk", speechId: "a", buffer: pcm(0.5, 6_000) })
    expect(render()[0]).toBeCloseTo(0.5, 3)
  })

  it("starts a line shorter than the cushion as soon as all of it is here", () => {
    // Otherwise a short sentence waits for audio that is never coming.
    send({ type: "chunk", speechId: "a", buffer: pcm(0.5, 128) })
    send({ type: "end", speechId: "a" })

    expect(render()[0]).toBeCloseTo(0.5, 3)
  })

  it("does not report a drain when a line has merely run out of buffer", () => {
    // An empty queue is equally "everything has been said" and "the next frame has not
    // arrived yet". Reporting the second as the first ended the sentence everywhere it
    // mattered: captions stopped deferring, the pending server state was applied, and every
    // waiter on `drain()` resolved -- which let the follow-up window start counting down
    // while the customer was still being spoken to.
    send({ type: "chunk", speechId: "a", buffer: pcm(0.5, 6_000) })
    render(60)

    expect(
      player.posted.filter((message) => (message as { type: string }).type === "drained"),
    ).toHaveLength(0)

    // The end marker is what makes it real.
    send({ type: "end", speechId: "a" })
    render()

    expect(
      player.posted.filter((message) => (message as { type: string }).type === "drained"),
    ).toHaveLength(1)
  })

  it("stays silent, and says so once, when there is nothing left to play", () => {
    send({ type: "chunk", speechId: "a", buffer: pcm(0.5, 64) })
    send({ type: "end", speechId: "a" })
    render(3)

    const drains = player.posted.filter(
      (message) => (message as { type: string }).type === "drained",
    )
    // The main thread waits on this edge before closing the audio context, so a repeat
    // would let a later teardown fire against a queue that had refilled.
    expect(drains).toHaveLength(1)
  })
})

describe("kiosk-player at a rate the browser chose for us", () => {
  // The page asks for a 24 kHz context so that nothing needs converting. A browser may hand
  // back the hardware rate anyway, and then 24 kHz samples clocked at 48 kHz play twice as
  // fast and an octave up. The worklet reads the rate it actually got rather than trusting
  // the request, so the same bytes come out at the right pitch.
  let fastPlayer: Processor

  beforeAll(async () => {
    vi.resetModules()
    vi.stubGlobal("sampleRate", 48_000)
    registered.delete("kiosk-player")
    // @ts-expect-error -- see the note on the first import.
    await import("../public/kiosk-audio-worklet.js")
    fastPlayer = new (registered.get("kiosk-player")!)()
  })

  it("holds each source sample for two output samples at double the rate", () => {
    const send48 = (message: Record<string, unknown>) =>
      fastPlayer.port.onmessage!({ data: message })
    const ramp = new Int16Array(64)
    for (let index = 0; index < ramp.length; index += 1) ramp[index] = index * 256
    send48({ type: "chunk", speechId: "a", buffer: ramp.buffer })
    send48({ type: "end", speechId: "a" })

    const channel = new Float32Array(128)
    fastPlayer.process([], [[channel]])

    // Each source sample is emitted twice, so 64 samples fill the whole 128-sample quantum
    // instead of racing through it in half the time.
    expect(channel[0]).toBeCloseTo(channel[1], 5)
    expect(channel[2]).toBeCloseTo(channel[3], 5)
    expect(channel[2]).toBeGreaterThan(channel[0])
    expect(channel[126]).toBeGreaterThan(channel[0])
  })
})
