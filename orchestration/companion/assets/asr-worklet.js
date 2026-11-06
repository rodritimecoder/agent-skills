/* Mic -> 16 kHz mono s16le, in 128 ms chunks, with the peak of each chunk.
 *
 * The live ASR endpoint takes PCM, not WebM, so the conversion has to happen
 * before the audio leaves the page. A worklet runs on the audio thread, which
 * means a slow POST on the main thread cannot drop frames here; chunks queue
 * in the port instead.
 */

const TARGET_RATE = 16000;
const CHUNK = 2048; // 128 ms at 16 kHz

class PCM16 extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.ratio = (options.processorOptions?.rate || sampleRate) / TARGET_RATE;
    this.buf = new Int16Array(CHUNK);
    this.n = 0;
    this.peak = 0;
    this.pos = 0; // fractional read position, carried across blocks
    this.prev = 0; // last source sample of the previous block
    this.port.onmessage = (ev) => {
      if (ev.data === "flush") this.flush();
    };
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;

    if (Math.abs(this.ratio - 1) < 0.001) {
      for (let i = 0; i < channel.length; i++) this.push(channel[i]);
      return true;
    }

    let pos = this.pos;
    while (pos < channel.length) {
      const i0 = Math.floor(pos);
      const frac = pos - i0;
      const s0 = i0 === 0 ? this.prev : channel[i0];
      const s1 = i0 + 1 < channel.length ? channel[i0 + 1] : s0;
      this.push(s0 + (s1 - s0) * frac);
      pos += this.ratio;
    }
    this.pos = pos - channel.length;
    this.prev = channel[channel.length - 1];
    return true;
  }

  push(value) {
    const clamped = value > 1 ? 1 : value < -1 ? -1 : value;
    const magnitude = clamped < 0 ? -clamped : clamped;
    if (magnitude > this.peak) this.peak = magnitude;
    this.buf[this.n++] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    if (this.n === CHUNK) this.flush();
  }

  flush() {
    if (!this.n) return;
    const pcm = this.buf.slice(0, this.n);
    this.port.postMessage({ pcm, peak: this.peak }, [pcm.buffer]);
    this.n = 0;
    this.peak = 0;
  }
}

registerProcessor("pcm16", PCM16);
