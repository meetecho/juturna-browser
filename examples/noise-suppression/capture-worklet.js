// Cuts the microphone into blocks of 480 samples (10 ms at 48 kHz), the frame of
// denoise_dfn. Each block goes to the pipeline through the MessagePort of
// `input.port()`, and a copy comes back to the page for the recording.
class Capture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.block = new Float32Array(480);
    this.filled = 0;
    this.pipeline = null;
    this.port.onmessage = ({ data }) => { this.pipeline = data.pipeline; };
  }

  process(inputs) {
    const channel = inputs[0][0];
    if (!channel || !this.pipeline) return true;

    for (let i = 0; i < channel.length; i++) {
      this.block[this.filled++] = channel[i];
      if (this.filled < 480) continue;

      const block = this.block;
      const copy = block.slice();
      this.block = new Float32Array(480);
      this.filled = 0;

      // t: the audio clock when the block was complete, read back by the page
      // on the cleaned block, which travels the same clock
      this.pipeline.postMessage({
        kind: 'audio',
        payload: {
          audio: block, sampling_rate: sampleRate, channels: 1, start: (currentFrame + i + 1 - 480) / sampleRate
        },
        meta: { t: currentTime }
      }, [block.buffer]);
      this.port.postMessage(copy, [copy.buffer]);
    }
    return true;
  }
}

registerProcessor('capture', Capture);
