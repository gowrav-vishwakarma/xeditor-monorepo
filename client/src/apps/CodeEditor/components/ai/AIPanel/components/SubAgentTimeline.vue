<template>
  <div
    class="sub-agent-timeline"
    :class="{ 'sub-agent-running': isRunning, 'sub-agent-error': hasError }"
  >
    <!-- Sub-Agent Header -->
    <div class="sub-agent-header" @click="toggleExpanded">
      <div class="sub-agent-icon">
        <q-spinner-dots v-if="isRunning" size="14px" color="primary" />
        <q-icon v-else-if="hasError" name="error" size="14px" color="negative" />
        <q-icon v-else name="check_circle" size="14px" color="positive" />
      </div>
      <div class="sub-agent-info">
        <span class="sub-agent-name">{{ startEvent.agentName || 'Sub-Agent' }}</span>
        <span class="sub-agent-purpose">{{ startEvent.purpose }}</span>
      </div>
      <q-icon :name="isExpanded ? 'expand_less' : 'expand_more'" size="16px" class="expand-icon" />
      <q-btn
        v-if="debugEnabled"
        flat
        dense
        round
        size="xs"
        icon="bug_report"
        color="orange"
        class="sub-agent-debug-btn"
        @click.stop="$emit('debug-inspect-sub-agent', startEvent.id)"
      >
        <q-tooltip :delay="300">Inspect sub-agent activity</q-tooltip>
      </q-btn>
    </div>

    <!-- Expanded Content -->
    <div v-if="isExpanded" class="sub-agent-content">
      <!-- Nested Timeline Items -->
      <div
        v-for="item in childItems"
        :key="item.id"
        class="sub-agent-item"
        :class="`sub-agent-item-${item.type}`"
      >
        <!-- Thinking Item -->
        <template v-if="item.type === 'thinking'">
          <div class="thinking-item" :class="{ 'thinking-active': isThinkingActive(item) }">
            <div class="thinking-header" @click="toggleThinking(item.id)">
              <q-icon
                name="psychology"
                size="12px"
                class="q-mr-xs"
                :class="{ 'thinking-icon-animated': isThinkingActive(item) }"
              />
              <span>{{ isThinkingActive(item) ? 'Thinking...' : 'Thinking' }}</span>
              <q-icon
                :name="expandedThinking.has(item.id) ? 'expand_less' : 'expand_more'"
                size="12px"
                class="q-ml-auto"
              />
            </div>
            <div v-if="expandedThinking.has(item.id)" class="thinking-content">
              {{ item.content }}
            </div>
          </div>
        </template>

        <!-- Tool Call Item -->
        <template v-else-if="item.type === 'tool_call'">
          <div class="tool-call-item" :class="getToolCallStatus(item.id)">
            <div class="tool-call-icon">
              <q-spinner-dots v-if="isToolRunning(item.id)" size="12px" color="primary" />
              <q-icon v-else-if="hasToolError(item.id)" name="error" size="12px" color="negative" />
              <q-icon v-else name="check_circle" size="12px" color="positive" />
            </div>
            <div class="tool-call-content">
              <span class="tool-name">{{ item.toolName }}</span>
              <span v-if="hasBriefArgs(item.arguments)" class="tool-args">
                {{ formatBriefArgs(item.arguments) }}
              </span>
            </div>
            <q-btn
              v-if="debugEnabled"
              flat
              dense
              round
              size="xs"
              icon="bug_report"
              color="orange"
              class="tool-call-debug-btn"
              @click.stop="$emit('debug-inspect-tool-call', item.id)"
            >
              <q-tooltip :delay="300">Inspect tool call</q-tooltip>
            </q-btn>
          </div>
        </template>

        <!-- Assistant Message Item -->
        <template v-else-if="item.type === 'assistant_message'">
          <div class="assistant-message-item">
            <div
              class="assistant-message-content"
              v-html="formatMessage(item.content, isRunning)"
            ></div>
          </div>
        </template>

        <!-- Nested Sub-Agent (recursive) -->
        <template v-else-if="item.type === 'sub_agent_start'">
          <SubAgentTimeline
            :start-event="item"
            :end-event="getSubAgentEndEvent(item.id)"
            :trace-events="traceEvents"
            :is-streaming="isStreaming"
            :debug-enabled="debugEnabled"
            @debug-inspect-tool-call="$emit('debug-inspect-tool-call', $event)"
            @debug-inspect-sub-agent="$emit('debug-inspect-sub-agent', $event)"
          />
        </template>
      </div>

      <!-- Sub-Agent Result Summary -->
      <div v-if="endEvent && endEvent.result" class="sub-agent-result">
        <q-icon name="lightbulb" size="14px" color="amber" class="q-mr-xs" />
        <span class="result-label">Result:</span>
        <span class="result-preview">{{ truncateResult(endEvent.result) }}</span>
      </div>

      <!-- Sub-Agent Token Usage -->
      <div v-if="endEvent?.usage" class="sub-agent-usage">
        <q-icon name="token" size="12px" class="q-mr-xs" />
        <span>{{ formatTokens(endEvent.usage.totalTokens) }} tokens</span>
        <span v-if="endEvent.modelSnapshot?.family" class="usage-family">
          ({{ endEvent.modelSnapshot.family }})
        </span>
      </div>

      <!-- Sub-Agent Error -->
      <div v-if="endEvent && endEvent.error" class="sub-agent-error-message">
        <q-icon name="error" size="14px" color="negative" class="q-mr-xs" />
        <span>{{ endEvent.error }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useMessageFormatting } from '../composables/useMessageFormatting';
import type {
  TraceEvent,
  TraceEventSubAgentStart,
  TraceEventSubAgentEnd,
  TraceEventToolResult,
  TraceEventThinking,
} from 'src/apps/CodeEditor/core/types';

const props = defineProps<{
  startEvent: TraceEventSubAgentStart;
  endEvent?: TraceEventSubAgentEnd | undefined;
  traceEvents: TraceEvent[];
  isStreaming?: boolean | undefined;
  debugEnabled?: boolean | undefined;
}>();

defineEmits<{
  'debug-inspect-tool-call': [toolCallId: string];
  'debug-inspect-sub-agent': [subAgentId: string];
}>();

const { formatMessage } = useMessageFormatting();

// State
const isExpanded = ref(true);
const expandedThinking = ref<Set<string>>(new Set());

// Computed
const isRunning = computed(() => {
  return props.isStreaming && !props.endEvent;
});

const hasError = computed(() => {
  // Only treat as error if error is explicitly set to a truthy string value
  return !!(
    props.endEvent?.error &&
    typeof props.endEvent.error === 'string' &&
    props.endEvent.error.trim().length > 0
  );
});

// Get child items (events that belong to this sub-agent)
const childItems = computed(() => {
  const subAgentId = props.startEvent.id;

  // Filter events that have this sub-agent as their parentId
  // Exclude the start event itself, sub_agent_end, and tool_result (handled separately)
  return props.traceEvents
    .filter((e) => {
      if (e.type === 'sub_agent_start' && e.id === subAgentId) return false;
      if (e.type === 'sub_agent_end') return false;
      if (e.type === 'tool_result') return false;
      if (e.type === 'tool_chunk') return false;
      if (e.type === 'file_change') return false;
      if (e.type === 'context_retrieval') return false;
      if (e.type === 'context_compression') return false;
      return e.parentId === subAgentId;
    })
    .sort((a, b) => a.timestamp - b.timestamp);
});

// Get tool results map for quick lookup
const toolResults = computed(() => {
  const results = new Map<string, TraceEventToolResult>();
  for (const event of props.traceEvents) {
    if (event.type === 'tool_result') {
      results.set(event.toolCallId, event);
    }
  }
  return results;
});

// Methods
function toggleExpanded() {
  isExpanded.value = !isExpanded.value;
}

function toggleThinking(id: string) {
  if (expandedThinking.value.has(id)) {
    expandedThinking.value.delete(id);
  } else {
    expandedThinking.value.add(id);
  }
  expandedThinking.value = new Set(expandedThinking.value);
}

function isThinkingActive(item: TraceEventThinking): boolean {
  if (!isRunning.value) return false;
  const thinkingEvents = props.traceEvents.filter(
    (e) => e.type === 'thinking' && e.parentId === props.startEvent.id,
  );
  const lastThinking = thinkingEvents[thinkingEvents.length - 1];
  return lastThinking?.id === item.id;
}

function isToolRunning(toolCallId: string): boolean {
  return isRunning.value && !toolResults.value.has(toolCallId);
}

function hasToolError(toolCallId: string): boolean {
  const result = toolResults.value.get(toolCallId);
  return !!result?.error;
}

function getToolCallStatus(toolCallId: string): string {
  if (isToolRunning(toolCallId)) return 'tool-running';
  if (!props.isStreaming && !toolResults.value.has(toolCallId)) return 'tool-error';
  if (hasToolError(toolCallId)) return 'tool-error';
  return 'tool-complete';
}

function hasBriefArgs(args: Record<string, unknown> | undefined): boolean {
  return args ? Object.keys(args).length > 0 : false;
}

function formatBriefArgs(args: Record<string, unknown> | undefined): string {
  if (!args) return '';
  const MAX_VALUE_LENGTH = 25;
  const parts: string[] = [];
  for (const [key, value] of Object.entries(args)) {
    let displayValue = '';
    if (typeof value === 'string') {
      displayValue =
        value.length > MAX_VALUE_LENGTH ? value.slice(0, MAX_VALUE_LENGTH - 3) + '...' : value;
      displayValue = `"${displayValue}"`;
    } else if (typeof value === 'number' || typeof value === 'boolean') {
      displayValue = String(value);
    } else if (value === null) {
      displayValue = 'null';
    } else if (value === undefined) {
      displayValue = 'undefined';
    } else {
      // Arrays, objects, and other types - use JSON.stringify
      const str = JSON.stringify(value);
      displayValue =
        str.length > MAX_VALUE_LENGTH ? str.slice(0, MAX_VALUE_LENGTH - 3) + '...' : str;
    }
    parts.push(`${key}=${displayValue}`);
  }
  return parts.join(' ');
}

function getSubAgentEndEvent(startId: string): TraceEventSubAgentEnd | undefined {
  return props.traceEvents.find((e) => e.type === 'sub_agent_end' && e.agentStartId === startId) as
    | TraceEventSubAgentEnd
    | undefined;
}

function truncateResult(result: unknown): string {
  const str = typeof result === 'string' ? result : JSON.stringify(result);
  const MAX_LENGTH = 150;
  return str.length > MAX_LENGTH ? str.slice(0, MAX_LENGTH) + '...' : str;
}

function formatTokens(n: number): string {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n.toString();
}
</script>

<style scoped>
.sub-agent-timeline {
  background: #f8f4ff;
  border-radius: 8px;
  border: 1px solid #e1bee7;
  overflow: hidden;
  margin: 4px 0;
}

.sub-agent-timeline.sub-agent-running {
  border-color: #9c27b0;
  animation: sub-agent-pulse 2s ease-in-out infinite;
}

.sub-agent-timeline.sub-agent-error {
  border-color: #f44336;
  background: #fff5f5;
}

@keyframes sub-agent-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.85;
  }
}

.sub-agent-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  cursor: pointer;
  user-select: none;
}

.sub-agent-header:hover {
  background: rgba(0, 0, 0, 0.03);
}

.sub-agent-icon {
  flex-shrink: 0;
  width: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.sub-agent-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sub-agent-name {
  font-weight: 600;
  font-size: 12px;
  color: #6a1b9a;
}

.sub-agent-purpose {
  font-size: 11px;
  color: #666;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.expand-icon {
  flex-shrink: 0;
  color: #999;
}

.sub-agent-debug-btn {
  opacity: 0.6;
  transition: opacity 0.2s ease;
  flex-shrink: 0;
}

.sub-agent-debug-btn:hover {
  opacity: 1;
}

.sub-agent-content {
  padding: 0 10px 10px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-top: 1px solid #e1bee7;
}

/* Nested items use smaller styling */
.sub-agent-item {
  margin-left: 8px;
  padding-left: 8px;
  border-left: 2px solid #e1bee7;
}

.thinking-item {
  background: #f3e5f5;
  border-radius: 4px;
  border: 1px solid #ce93d8;
  font-size: 11px;
}

.thinking-header {
  display: flex;
  align-items: center;
  padding: 4px 8px;
  cursor: pointer;
  color: #6a1b9a;
}

.thinking-content {
  padding: 4px 8px;
  font-size: 11px;
  color: #4a148c;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 150px;
  overflow-y: auto;
}

.tool-call-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: #ffffff;
  border-radius: 4px;
  border: 1px solid #e0e0e0;
  font-size: 11px;
}

.tool-call-item.tool-running {
  border-color: #1976d2;
  background: #e3f2fd;
}

.tool-call-item.tool-complete {
  border-color: #4caf50;
  background: #e8f5e9;
}

.tool-call-item.tool-error {
  border-color: #f44336;
  background: #ffebee;
}

.tool-call-icon {
  flex-shrink: 0;
  width: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.tool-call-content {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}

.tool-name {
  font-weight: 600;
  color: #1565c0;
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
}

.tool-args {
  color: #666;
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 10px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-call-debug-btn {
  opacity: 0.6;
  flex-shrink: 0;
}

.assistant-message-item {
  padding: 4px 0;
}

.assistant-message-content {
  font-size: 12px;
  color: #333;
  line-height: 1.5;
}

.sub-agent-result {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  padding: 8px;
  background: #fff8e1;
  border-radius: 4px;
  border: 1px solid #ffe082;
  font-size: 11px;
  margin-top: 4px;
}

.result-label {
  font-weight: 600;
  color: #f57c00;
  flex-shrink: 0;
}

.result-preview {
  color: #666;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sub-agent-usage {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  font-size: 11px;
  color: #888;
  margin-top: 4px;
}

.usage-family {
  color: #999;
}

.sub-agent-error-message {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px;
  background: #ffebee;
  border-radius: 4px;
  border: 1px solid #ef9a9a;
  font-size: 11px;
  color: #c62828;
  margin-top: 4px;
}

.thinking-icon-animated {
  animation: thinking-spin 3s linear infinite;
}

@keyframes thinking-spin {
  0% {
    transform: rotate(0deg);
  }
  25% {
    transform: rotate(15deg);
  }
  75% {
    transform: rotate(-15deg);
  }
  100% {
    transform: rotate(0deg);
  }
}
</style>
