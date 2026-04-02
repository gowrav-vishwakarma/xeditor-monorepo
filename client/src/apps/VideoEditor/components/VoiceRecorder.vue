<template>
  <div class="voice-recorder">
    <div class="recorder-display q-pa-md q-mb-md bg-grey-2 rounded-borders text-center">
      <!-- Waveform canvas -->
      <canvas ref="waveformCanvas" width="400" height="80" class="waveform-canvas" />

      <div class="text-h5 q-mt-sm">{{ formatTime(recordingTime) }}</div>
      <div class="text-caption text-grey">
        {{ isRecording ? 'Recording...' : hasRecording ? 'Recording ready' : 'Press record to start' }}
      </div>
    </div>

    <div class="row justify-center q-gutter-md">
      <q-btn
        v-if="!isRecording && !hasRecording"
        round
        color="negative"
        icon="fiber_manual_record"
        size="lg"
        @click="startRecording"
      />
      <q-btn
        v-if="isRecording"
        round
        color="grey"
        icon="stop"
        size="lg"
        @click="stopRecording"
      />
      <q-btn
        v-if="hasRecording && !isRecording"
        round
        :color="isPlaying ? 'warning' : 'primary'"
        :icon="isPlaying ? 'stop' : 'play_arrow'"
        size="lg"
        @click="togglePlayback"
      />
      <q-btn
        v-if="hasRecording && !isRecording"
        round
        color="negative"
        icon="delete"
        size="md"
        @click="discardRecording"
      />
    </div>

    <div v-if="hasRecording && !isRecording" class="row justify-center q-gutter-md q-mt-lg">
      <q-btn flat label="Cancel" @click="emit('cancel')" />
      <q-btn color="primary" icon="save" label="Save Voice" @click="saveRecording" />
    </div>

    <div v-if="errorMessage" class="text-negative text-center q-mt-md">
      {{ errorMessage }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onBeforeUnmount } from 'vue';

const emit = defineEmits<{
  recorded: [blob: Blob];
  cancel: [];
}>();

const waveformCanvas = ref<HTMLCanvasElement | null>(null);
const isRecording = ref(false);
const isPlaying = ref(false);
const hasRecording = ref(false);
const recordingTime = ref(0);
const errorMessage = ref('');

let mediaRecorder: MediaRecorder | null = null;
let audioChunks: Blob[] = [];
let recordedBlob: Blob | null = null;
let audioUrl: string | null = null;
let audioElement: HTMLAudioElement | null = null;
let timerInterval: ReturnType<typeof setInterval> | null = null;
let analyser: AnalyserNode | null = null;
let animationFrame: number | null = null;
let audioContext: AudioContext | null = null;

async function startRecording(): Promise<void> {
  errorMessage.value = '';
  audioChunks = [];

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

    audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(stream);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);

    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunks.push(e.data);
    };
    mediaRecorder.onstop = () => {
      recordedBlob = new Blob(audioChunks, { type: 'audio/wav' });
      audioUrl = URL.createObjectURL(recordedBlob);
      hasRecording.value = true;
      stream.getTracks().forEach((t) => t.stop());
    };

    mediaRecorder.start();
    isRecording.value = true;
    recordingTime.value = 0;

    timerInterval = setInterval(() => {
      recordingTime.value += 0.1;
    }, 100);

    drawWaveform();
  } catch (e) {
    errorMessage.value = 'Could not access microphone. Check browser permissions.';
    console.error('Microphone error:', e);
  }
}

function stopRecording(): void {
  if (mediaRecorder && isRecording.value) {
    mediaRecorder.stop();
    isRecording.value = false;
    if (timerInterval) clearInterval(timerInterval);
    if (animationFrame) cancelAnimationFrame(animationFrame);
  }
}

function togglePlayback(): void {
  if (!audioUrl) return;

  if (isPlaying.value && audioElement) {
    audioElement.pause();
    audioElement.currentTime = 0;
    isPlaying.value = false;
    return;
  }

  audioElement = new Audio(audioUrl);
  audioElement.onended = () => { isPlaying.value = false; };
  void audioElement.play();
  isPlaying.value = true;
}

function discardRecording(): void {
  hasRecording.value = false;
  recordedBlob = null;
  recordingTime.value = 0;
  if (audioUrl) {
    URL.revokeObjectURL(audioUrl);
    audioUrl = null;
  }
  clearCanvas();
}

function saveRecording(): void {
  if (recordedBlob) {
    emit('recorded', recordedBlob);
  }
}

function drawWaveform(): void {
  if (!analyser || !waveformCanvas.value) return;
  const canvas = waveformCanvas.value;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const bufferLength = analyser.frequencyBinCount;
  const dataArray = new Uint8Array(bufferLength);

  function draw(): void {
    if (!isRecording.value || !analyser || !ctx) return;
    animationFrame = requestAnimationFrame(draw);

    analyser.getByteTimeDomainData(dataArray);

    ctx.fillStyle = '#f5f5f5';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#1976d2';
    ctx.beginPath();

    const sliceWidth = canvas.width / bufferLength;
    let x = 0;
    for (let i = 0; i < bufferLength; i++) {
      const v = (dataArray[i] ?? 128) / 128.0;
      const y = (v * canvas.height) / 2;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
      x += sliceWidth;
    }
    ctx.lineTo(canvas.width, canvas.height / 2);
    ctx.stroke();
  }

  draw();
}

function clearCanvas(): void {
  if (!waveformCanvas.value) return;
  const ctx = waveformCanvas.value.getContext('2d');
  if (ctx) {
    ctx.fillStyle = '#f5f5f5';
    ctx.fillRect(0, 0, waveformCanvas.value.width, waveformCanvas.value.height);
  }
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 10);
  return `${m}:${s.toString().padStart(2, '0')}.${ms}`;
}

onBeforeUnmount(() => {
  if (timerInterval) clearInterval(timerInterval);
  if (animationFrame) cancelAnimationFrame(animationFrame);
  if (audioElement) audioElement.pause();
  if (audioUrl) URL.revokeObjectURL(audioUrl);
  if (audioContext) void audioContext.close();
  if (mediaRecorder && isRecording.value) mediaRecorder.stop();
});
</script>

<style scoped lang="scss">
.voice-recorder {
  max-width: 500px;
  margin: 0 auto;
}

.waveform-canvas {
  width: 100%;
  height: 80px;
  border-radius: 4px;
  background: #f5f5f5;
}
</style>
