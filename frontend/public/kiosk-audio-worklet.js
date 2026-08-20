// Audio for the kiosk's spoken channel, in both directions.
//
// Everything here is PCM16 mono at 24 kHz, which is what the transcription session accepts
// and what the text-to-speech model returns. One format end to end means no resampling and
// no decoder: bytes off the socket go straight to the speaker, and a stream cut short by an
// interruption is still playable up to the cut.

// 20 ms at 24 kHz. Small enough that turn detection reacts promptly, large enough that the
// socket is not carrying a message per render quantum.
const FRAME_SAMPLES = 480

class KioskMicProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.pending = new Int16Array(FRAME_SAMPLES)
    this.filled = 0
  }

  process(inputs) {
    const channel = inputs[0]?.[0]
    if (!channel) return true

    for (let index = 0; index < channel.length; index += 1) {
      // Clamp before scaling: a sample above 1.0 would wrap to a loud negative otherwise,
      // which the recogniser hears as a click.
      const sample = Math.max(-1, Math.min(1, channel[index]))
      this.pending[this.filled] = sample < 0 ? sample * 0x8000 : sample * 0x7fff
      this.filled += 1

      if (this.filled === FRAME_SAMPLES) {
        const frame = this.pending.slice()
        this.port.postMessage(frame.buffer, [frame.buffer])
        this.filled = 0
      }
    }
    return true
  }
}

class KioskPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super()
    this.queue = []
    this.offset = 0
    this.port.onmessage = (event) => {
      // `flush` is barge-in. Dropping the queue rather than fading it out is deliberate:
      // the customer has started talking, and the kiosk finishing its sentence over them is
      // the behaviour this whole channel exists to avoid.
      if (event.data === "flush") {
        this.queue = []
        this.offset = 0
        return
      }
      this.queue.push(new Int16Array(event.data))
    }
  }

  process(_inputs, outputs) {
    const output = outputs[0][0]
    if (!output) return true

    for (let index = 0; index < output.length; index += 1) {
      const chunk = this.queue[0]
      if (!chunk) {
        output[index] = 0
        continue
      }
      output[index] = chunk[this.offset] / 0x8000
      this.offset += 1
      if (this.offset >= chunk.length) {
        this.queue.shift()
        this.offset = 0
      }
    }
    return true
  }
}

registerProcessor("kiosk-mic", KioskMicProcessor)
registerProcessor("kiosk-player", KioskPlayerProcessor)
