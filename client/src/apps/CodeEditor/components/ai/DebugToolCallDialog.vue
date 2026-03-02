<template>
  <q-dialog v-model="isOpen" persistent>
    <q-card class="debug-tool-call-dialog-card">
      <!-- Header -->
      <q-card-section class="debug-dialog-header row items-center no-wrap">
        <q-icon name="bug_report" size="24px" color="orange" class="q-mr-sm" />
        <div class="text-h6">{{ isSubAgentTool ? 'Sub-Agent Debug' : 'Tool Call Debug' }}</div>
        <q-space />
        <q-btn flat round dense icon="close" @click="close" />
      </q-card-section>

      <q-separator />

      <!-- Tool Call Content -->
      <q-card-section v-if="toolCallData" class="debug-tool-call-content">
        <!-- Tool Name and ID -->
        <div class="tool-call-header-section">
          <div class="row items-center q-gutter-sm">
            <q-chip dense color="teal-3" text-color="grey-9" icon="build" size="md">
              {{ toolCallData.toolName }}
            </q-chip>
            <span class="tool-call-id-text">ID: {{ toolCallData.id?.substring(0, 16) }}...</span>
          </div>
        </div>

        <!-- Arguments Section -->
        <div class="tool-call-section">
          <div class="tool-call-label row items-center justify-between">
            <span>Arguments:</span>
            <q-btn
              flat
              dense
              icon="content_copy"
              size="sm"
              @click="copyToClipboard(JSON.stringify(toolCallData.arguments, null, 2))"
            >
              <q-tooltip>Copy to clipboard</q-tooltip>
            </q-btn>
          </div>
          <pre class="tool-call-content">{{ JSON.stringify(toolCallData.arguments, null, 2) }}</pre>
        </div>

        <!-- Sub-Agent Activity Section (for delegate_task) -->
        <div
          v-if="isSubAgentTool && subAgentStartEvent"
          class="tool-call-section sub-agent-activity-section"
        >
          <div class="tool-call-label">
            <span>Sub-Agent Activity:</span>
          </div>
          <div class="sub-agent-activity-container">
            <SubAgentTimeline
              :start-event="subAgentStartEvent"
              :end-event="subAgentEndEvent"
              :trace-events="allTraceEvents"
              :is-streaming="isStreaming"
              :debug-enabled="true"
              @debug-inspect-tool-call="handleNestedToolInspect"
            />
          </div>
        </div>

        <!-- Result Section -->
        <div v-if="toolCallData.result !== undefined && !isSubAgentTool" class="tool-call-section">
          <div class="tool-call-label row items-center justify-between">
            <span>Result:</span>
            <q-btn flat dense icon="content_copy" size="sm" @click="copyResultToClipboard">
              <q-tooltip>Copy to clipboard</q-tooltip>
            </q-btn>
          </div>
          <pre class="tool-call-content">{{
            typeof toolCallData.result === 'string'
              ? toolCallData.result
              : JSON.stringify(toolCallData.result, null, 2)
          }}</pre>
        </div>

        <!-- Context Summary Section (when result was compressed by LLM) -->
        <div
          v-if="toolCallData.contextSummary && !isSubAgentTool"
          class="tool-call-section context-summary-section"
        >
          <div class="tool-call-label row items-center justify-between">
            <span>Context Summary (compressed by LLM):</span>
            <q-btn
              flat
              dense
              icon="content_copy"
              size="sm"
              @click="copyToClipboard(toolCallData.contextSummary || '')"
            >
              <q-tooltip>Copy to clipboard</q-tooltip>
            </q-btn>
          </div>
          <pre class="tool-call-content context-summary-content">{{ toolCallData.contextSummary }}</pre>
        </div>

        <!-- Error Section -->
        <div v-if="toolCallData.error" class="tool-call-section tool-call-error">
          <div class="tool-call-label row items-center justify-between">
            <span>Error:</span>
            <q-btn
              flat
              dense
              icon="content_copy"
              size="sm"
              @click="copyToClipboard(toolCallData.error || '')"
            >
              <q-tooltip>Copy to clipboard</q-tooltip>
            </q-btn>
          </div>
          <pre class="tool-call-content error-content">{{ toolCallData.error }}</pre>
        </div>

        <!-- Output Section (streaming output) - only show for non-sub-agent tools -->
        <div v-if="toolCallData.output && !isSubAgentTool" class="tool-call-section">
          <div class="tool-call-label row items-center justify-between">
            <span>Streaming Output:</span>
            <q-btn
              flat
              dense
              icon="content_copy"
              size="sm"
              @click="copyToClipboard(toolCallData.output || '')"
            >
              <q-tooltip>Copy to clipboard</q-tooltip>
            </q-btn>
          </div>
          <pre class="tool-call-content">{{ toolCallData.output }}</pre>
        </div>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue';
import { useQuasar } from 'quasar';
import SubAgentTimeline from './AIPanel/components/SubAgentTimeline.vue';
import type {
  TraceEvent,
  TraceEventToolCall,
  TraceEventToolResult,
  TraceEventSubAgentStart,
  TraceEventSubAgentEnd,
} from 'src/apps/CodeEditor/core/types';

interface Props {
  modelValue: boolean;
  toolCall: TraceEventToolCall | null;
  toolResult: TraceEventToolResult | null;
  allTraceEvents?: TraceEvent[];
  isStreaming?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  allTraceEvents: () => [],
  isStreaming: false,
});

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void;
  (e: 'inspect-nested-tool', toolCallId: string): void;
}>();

const $q = useQuasar();

const isOpen = ref(props.modelValue);

const toolCallData = computed(() => {
  if (!props.toolCall) return null;

  return {
    id: props.toolCall.id,
    toolName: props.toolCall.toolName,
    arguments: props.toolCall.arguments,
    output: props.toolCall.output,
    result: props.toolResult?.result,
    error: props.toolResult?.error,
    contextSummary: props.toolResult?.contextSummary,
  };
});

// Check if this is a delegate_task (sub-agent) tool
const isSubAgentTool = computed(() => {
  return props.toolCall?.toolName === 'delegate_task';
});

// Find the sub-agent start event for this tool call
const subAgentStartEvent = computed((): TraceEventSubAgentStart | undefined => {
  if (!isSubAgentTool.value || !props.toolCall) return undefined;

  return props.allTraceEvents.find(
    (e) => e.type === 'sub_agent_start' && e.parentId === props.toolCall?.id,
  ) as TraceEventSubAgentStart | undefined;
});

// Find the sub-agent end event
const subAgentEndEvent = computed((): TraceEventSubAgentEnd | undefined => {
  if (!subAgentStartEvent.value) return undefined;

  return props.allTraceEvents.find(
    (e) => e.type === 'sub_agent_end' && e.agentStartId === subAgentStartEvent.value?.id,
  ) as TraceEventSubAgentEnd | undefined;
});

watch(
  () => props.modelValue,
  (val) => {
    isOpen.value = val;
  },
);

watch(isOpen, (val) => {
  emit('update:modelValue', val);
});

function close() {
  isOpen.value = false;
}

function copyToClipboard(text: string) {
  void navigator.clipboard.writeText(text).then(() => {
    $q.notify({
      type: 'positive',
      message: 'Copied to clipboard',
      position: 'bottom',
      timeout: 1500,
    });
  });
}

function copyResultToClipboard() {
  if (!toolCallData.value) return;
  const result = toolCallData.value.result;
  const text = typeof result === 'string' ? result : JSON.stringify(result, null, 2);
  copyToClipboard(text);
}

function handleNestedToolInspect(toolCallId: string) {
  emit('inspect-nested-tool', toolCallId);
}
</script>

<style scoped>
.debug-tool-call-dialog-card {
  width: 100%;
  max-width: 800px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}

.debug-dialog-header {
  background: #fafafa;
}

.debug-tool-call-content {
  flex: 1;
  overflow: auto;
  padding: 16px;
}

.tool-call-header-section {
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid #e0e0e0;
}

.tool-call-id-text {
  font-size: 12px;
  color: #888;
  font-family: 'Fira Code', 'Monaco', 'Consolas', monospace;
}

.tool-call-section {
  margin-bottom: 16px;
}

.tool-call-label {
  font-size: 13px;
  font-weight: 600;
  color: #666;
  margin-bottom: 8px;
}

.tool-call-content {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px;
  margin: 0;
  border-radius: 6px;
  font-family: 'Fira Code', 'Monaco', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
}

.tool-call-error .error-content {
  color: #ff6b6b;
}

/* Context summary - amber styling to indicate compression */
.context-summary-section .tool-call-label {
  color: #f57f17;
}

.context-summary-content {
  background: #fff8e1;
  color: #5d4037;
  border: 1px solid #ffe082;
}

.tool-call-section:last-child {
  margin-bottom: 0;
}

/* Sub-agent activity section */
.sub-agent-activity-section {
  margin-top: 8px;
}

.sub-agent-activity-container {
  max-height: 400px;
  overflow-y: auto;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 8px;
  background: #fafafa;
}
</style>
