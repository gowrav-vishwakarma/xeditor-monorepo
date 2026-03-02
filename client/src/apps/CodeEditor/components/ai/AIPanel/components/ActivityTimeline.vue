<template>
  <div class="activity-timeline">
    <!-- Timeline Items -->
    <div
      v-for="item in timelineItems"
      :key="item.id"
      class="timeline-item"
      :class="`timeline-item-${item.type}`"
    >
      <!-- Thinking Item -->
      <template v-if="item.type === 'thinking'">
        <div class="thinking-item" :class="{ 'thinking-active': isThinkingActive(item) }">
          <div class="thinking-header" @click="toggleThinking(item.id)">
            <q-icon
              name="psychology"
              size="14px"
              class="q-mr-xs"
              :class="{ 'thinking-icon-animated': isThinkingActive(item) }"
            />
            <span>{{ isThinkingActive(item) ? 'Thinking...' : 'Thinking' }}</span>
            <q-icon
              :name="expandedThinking.has(item.id) ? 'expand_less' : 'expand_more'"
              size="14px"
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
        <div class="tool-call-wrapper">
          <div class="tool-call-item" :class="getToolCallStatus(item.id)">
            <div class="tool-call-icon">
              <q-spinner-dots v-if="isToolRunning(item.id)" size="14px" color="primary" />
              <q-icon v-else-if="hasToolError(item.id)" name="error" size="14px" color="negative" />
              <q-icon v-else name="check_circle" size="14px" color="positive" />
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
              <q-tooltip :delay="300">Inspect tool call debug info</q-tooltip>
            </q-btn>
          </div>

          <!-- Nested Sub-Agent Timeline for delegate_task -->
          <template v-if="item.toolName === 'delegate_task'">
            <div v-if="getDelegateTaskStartEvent(item.id)" class="delegate-task-nested">
              <SubAgentTimeline
                :start-event="getDelegateTaskStartEvent(item.id)!"
                :end-event="getSubAgentEndEvent(getDelegateTaskStartEvent(item.id)!.id)"
                :trace-events="traceEvents"
                :is-streaming="isStreaming"
                :debug-enabled="debugEnabled"
                @debug-inspect-tool-call="$emit('debug-inspect-tool-call', $event)"
                @debug-inspect-sub-agent="$emit('debug-inspect-sub-agent', $event)"
              />
            </div>
          </template>
        </div>
      </template>

      <!-- Context Compression Item -->
      <template v-else-if="item.type === 'context_compression'">
        <div class="context-compression-item">
          <q-icon name="compress" size="14px" class="q-mr-xs" />
          <span>Context compressed: {{ item.updates.length }} tool result{{ item.updates.length !== 1 ? 's' : '' }} summarized</span>
        </div>
      </template>

      <!-- Assistant Message Item -->
      <template v-else-if="item.type === 'assistant_message'">
        <div class="assistant-message-item">
          <div
            class="assistant-message-content"
            v-html="formatMessage(item.content, isStreaming)"
          ></div>
        </div>
      </template>
    </div>

    <!-- Current Activity Indicator (during streaming) -->
    <div v-if="isStreaming && currentActivity" class="current-activity">
      <q-spinner-dots size="14px" color="primary" />
      <span>{{ currentActivity }}</span>
    </div>

    <!-- Loading indicator when no events and streaming -->
    <div
      v-if="isStreaming && timelineItems.length === 0 && !messageContent"
      class="loading-indicator"
    >
      <q-spinner-dots size="24px" color="primary" />
      <span>Generating response...</span>
    </div>

    <!-- Message Content (rendered at the end, only if no assistant_message events exist) -->
    <div
      v-if="messageContent && !hasAssistantMessageEvents"
      class="message-content"
      v-html="formattedMessage"
    ></div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useMessageFormatting } from '../composables/useMessageFormatting';
import SubAgentTimeline from './SubAgentTimeline.vue';
import type {
  TraceEvent,
  TraceEventToolCall,
  TraceEventToolResult,
  TraceEventThinking,
  TraceEventAssistantMessage,
  TraceEventContextCompression,
  TraceEventSubAgentStart,
  TraceEventSubAgentEnd,
} from 'src/apps/CodeEditor/core/types';

const props = defineProps<{
  traceEvents: TraceEvent[];
  messageContent?: string | undefined;
  currentActivity?: string | undefined;
  isStreaming?: boolean | undefined;
  debugEnabled?: boolean | undefined;
}>();

defineEmits<{
  'debug-inspect-tool-call': [toolCallId: string];
  'debug-inspect-sub-agent': [subAgentId: string];
}>();

const { formatMessage } = useMessageFormatting();

// Track which thinking blocks are expanded
const expandedThinking = ref<Set<string>>(new Set());

// Filter and sort timeline items (thinking, tool_call, assistant_message, sorted by timestamp)
// Use stable sort with original index as tie-breaker to preserve insertion order when timestamps match
// Only include top-level items (those without parentId)
const timelineItems = computed(() => {
  // Map items with their original indices
  const itemsWithIndex = props.traceEvents
    .map((e, index) => ({ event: e, index }))
    .filter(
      (
        item,
      ): item is {
        event: TraceEventThinking | TraceEventToolCall | TraceEventAssistantMessage | TraceEventContextCompression;
        index: number;
      } => {
        const event = item.event;

        // Check if event has parentId property and it's set (for filtering top-level events)
        const hasParentId = 'parentId' in event && event.parentId !== undefined;
        const isTopLevel = !hasParentId;
        if (
          event.type === 'thinking' ||
          event.type === 'tool_call' ||
          event.type === 'assistant_message' ||
          event.type === 'context_compression'
        ) {
          return isTopLevel;
        }
        return false;
      },
    );

  // Sort by timestamp, then by original index (stable sort)
  itemsWithIndex.sort((a, b) => {
    const timeDiff = a.event.timestamp - b.event.timestamp;
    if (timeDiff !== 0) return timeDiff;
    return a.index - b.index; // Tie-breaker: preserve insertion order
  });

  // Extract just the events
  return itemsWithIndex.map(({ event }) => event);
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

// Check if a thinking block is currently active (streaming)
function isThinkingActive(item: TraceEventThinking): boolean {
  if (!props.isStreaming) return false;
  // It's active if it's the last thinking event and we're still streaming
  const thinkingEvents = props.traceEvents.filter((e) => e.type === 'thinking');
  const lastThinking = thinkingEvents[thinkingEvents.length - 1];
  return lastThinking?.id === item.id;
}

// Toggle thinking block expansion
function toggleThinking(id: string) {
  if (expandedThinking.value.has(id)) {
    expandedThinking.value.delete(id);
  } else {
    expandedThinking.value.add(id);
  }
  // Force reactivity
  expandedThinking.value = new Set(expandedThinking.value);
}

// Tool call status helpers
function isToolRunning(toolCallId: string): boolean {
  return props.isStreaming && !toolResults.value.has(toolCallId);
}

function hasToolError(toolCallId: string): boolean {
  const result = toolResults.value.get(toolCallId);
  return !!result?.error;
}

function hasToolResult(toolCallId: string): boolean {
  return toolResults.value.has(toolCallId);
}

// Check if delegate_task has completed via sub_agent_end event
function hasSubAgentEndForToolCall(toolCallId: string): boolean {
  // For delegate_task, check if there's a sub_agent_end event with this tool call as parentId
  return props.traceEvents.some(
    (e) => e.type === 'sub_agent_end' && 'parentId' in e && e.parentId === toolCallId && !e.error, // Only count as success if no error
  );
}

function getToolCallStatus(toolCallId: string): string {
  if (isToolRunning(toolCallId)) return 'tool-running';

  // Check for tool_result first
  if (hasToolResult(toolCallId)) {
    if (hasToolError(toolCallId)) return 'tool-error';
    return 'tool-complete';
  }

  // For delegate_task, check if sub-agent completed successfully
  if (hasSubAgentEndForToolCall(toolCallId)) {
    return 'tool-complete';
  }

  // If not streaming and no tool_result or sub_agent_end exists, treat as error
  if (!props.isStreaming) return 'tool-error';

  return 'tool-running';
}

// Format brief arguments for display
function hasBriefArgs(args: Record<string, unknown> | undefined): boolean {
  if (!args) return false;
  // Return true if any arguments exist
  return Object.keys(args).length > 0;
}

function formatBriefArgs(args: Record<string, unknown> | undefined): string {
  if (!args) return '';

  const MAX_VALUE_LENGTH = 30;
  const formattedParts: string[] = [];

  for (const [key, value] of Object.entries(args)) {
    let displayValue = '';

    if (typeof value === 'string') {
      // Truncate long strings
      displayValue =
        value.length > MAX_VALUE_LENGTH ? value.slice(0, MAX_VALUE_LENGTH - 3) + '...' : value;
      // Quote strings for readability
      displayValue = `"${displayValue}"`;
    } else if (Array.isArray(value)) {
      // Handle arrays
      const str = JSON.stringify(value);
      displayValue =
        str.length > MAX_VALUE_LENGTH ? str.slice(0, MAX_VALUE_LENGTH - 3) + '...' : str;
    } else if (typeof value === 'object' && value !== null) {
      // Handle objects
      const str = JSON.stringify(value);
      displayValue =
        str.length > MAX_VALUE_LENGTH ? str.slice(0, MAX_VALUE_LENGTH - 3) + '...' : str;
    } else {
      // Handle primitives (number, boolean, null, undefined)
      displayValue = String(value);
    }

    formattedParts.push(`${key}=${displayValue}`);
  }

  return formattedParts.join(' ');
}

// Check if there are any assistant_message events (to suppress legacy messageContent)
const hasAssistantMessageEvents = computed(() => {
  return props.traceEvents.some((e) => e.type === 'assistant_message');
});

// Format message content
const formattedMessage = computed(() => {
  return props.messageContent ? formatMessage(props.messageContent, props.isStreaming) : '';
});

// Get sub-agent end event for a given start event ID
function getSubAgentEndEvent(startId: string): TraceEventSubAgentEnd | undefined {
  return props.traceEvents.find((e) => e.type === 'sub_agent_end' && e.agentStartId === startId) as
    | TraceEventSubAgentEnd
    | undefined;
}

// Computed map of tool call IDs to their sub-agent start events (reactive)
// Using object instead of Map for better Vue reactivity
const delegateTaskStartEvents = computed(() => {
  const map: Record<string, TraceEventSubAgentStart> = {};
  for (const event of props.traceEvents) {
    if (event.type === 'sub_agent_start' && event.parentId) {
      // TypeScript narrows event to TraceEventSubAgentStart after the type check
      map[event.parentId] = event;
    }
  }
  return map;
});

// Helper function to get sub-agent start event for a tool call
// This accesses the computed property so Vue tracks the dependency
function getDelegateTaskStartEvent(toolCallId: string): TraceEventSubAgentStart | undefined {
  // Access computed value to ensure Vue tracks the dependency
  const events = delegateTaskStartEvents.value;
  return events[toolCallId];
}
</script>

<style scoped>
.activity-timeline {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* Thinking Item */
.thinking-item {
  background: #f3e5f5;
  border-radius: 6px;
  border: 1px solid #e1bee7;
  overflow: hidden;
}

.thinking-item.thinking-active {
  border-color: #9c27b0;
  animation: thinking-pulse 2s ease-in-out infinite;
}

@keyframes thinking-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.7;
  }
}

.thinking-header {
  display: flex;
  align-items: center;
  padding: 8px 10px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  color: #6a1b9a;
  user-select: none;
}

.thinking-header:hover {
  background: rgba(0, 0, 0, 0.03);
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

.thinking-content {
  padding: 0 10px 10px 10px;
  font-size: 12px;
  color: #4a148c;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
}

/* Tool Call Item */
.tool-call-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #ffffff;
  border-radius: 6px;
  border: 1px solid #e0e0e0;
  font-size: 12px;
  position: relative;
}

.tool-call-wrapper {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.delegate-task-nested {
  margin-left: 22px; /* align under tool icon */
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
  width: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.tool-call-content {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.tool-name {
  font-weight: 600;
  color: #1565c0;
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
}

.tool-args {
  color: #666;
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-call-debug-btn {
  opacity: 0.6;
  transition: opacity 0.2s ease;
  margin-left: auto;
  flex-shrink: 0;
}

.tool-call-debug-btn:hover {
  opacity: 1;
}

.tool-call-item:hover .tool-call-debug-btn {
  opacity: 0.8;
}

/* Context Compression Item */
.context-compression-item {
  display: flex;
  align-items: center;
  padding: 4px 10px;
  background: #fff8e1;
  border-radius: 6px;
  border: 1px solid #ffe082;
  font-size: 11px;
  color: #f57f17;
  font-weight: 500;
}

/* Assistant Message Item */
.assistant-message-item {
  margin: 8px 0;
}

.assistant-message-content {
  color: #333333;
  line-height: 1.6;
  font-size: 13px;
  word-break: break-word;
  overflow-wrap: break-word;
}

/* Share deep styles between message-content and assistant-message-content */
.assistant-message-content :deep(code),
.message-content :deep(code) {
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
  background: #f0f4f8;
  color: #d63384;
  word-break: break-all;
}

.assistant-message-content :deep(pre),
.message-content :deep(pre) {
  background: #1e1e1e;
  border-radius: 8px;
  padding: 12px 16px;
  margin: 12px 0;
  overflow-x: auto;
  position: relative;
}

.assistant-message-content :deep(pre code),
.message-content :deep(pre code) {
  background: transparent;
  color: #d4d4d4;
  padding: 0;
  font-size: 12px;
  line-height: 1.5;
  display: block;
  white-space: pre;
  word-break: normal;
}

/* Headers for assistant-message-content */
.assistant-message-content :deep(h1) {
  font-size: 1.25em !important;
  font-weight: 600 !important;
  line-height: 1.4 !important;
  margin: 10px 0 6px 0 !important;
  padding-bottom: 3px !important;
  border-bottom: 1px solid #e8e8e8;
  color: #1a1a1a;
}

.assistant-message-content :deep(h2) {
  font-size: 1.15em !important;
  font-weight: 600 !important;
  line-height: 1.4 !important;
  margin: 8px 0 4px 0 !important;
  color: #1a1a1a;
}

.assistant-message-content :deep(h3) {
  font-size: 1.1em !important;
  font-weight: 600 !important;
  line-height: 1.4 !important;
  margin: 6px 0 4px 0 !important;
  color: #1a1a1a;
}

.assistant-message-content :deep(h4),
.assistant-message-content :deep(h5),
.assistant-message-content :deep(h6) {
  font-size: 1.05em !important;
  font-weight: 600 !important;
  line-height: 1.4 !important;
  margin: 6px 0 3px 0 !important;
  color: #333;
}

/* Current Activity */
.current-activity {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: #fff3e0;
  border-radius: 6px;
  border: 1px solid #ffcc80;
  font-size: 12px;
  color: #e65100;
}

/* Loading Indicator */
.loading-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #757575;
  font-size: 13px;
  padding: 8px 0;
}

/* Message Content */
.message-content {
  color: #333333;
  line-height: 1.6;
  font-size: 13px;
  word-break: break-word;
  overflow-wrap: break-word;
  margin-top: 8px;
}

/* Inline code */
.message-content :deep(code) {
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
  background: #f0f4f8;
  color: #d63384;
  word-break: break-all;
}

/* Code blocks */
.message-content :deep(pre) {
  background: #1e1e1e;
  border-radius: 8px;
  padding: 12px 16px;
  margin: 12px 0;
  overflow-x: auto;
  position: relative;
}

.message-content :deep(pre code) {
  background: transparent;
  color: #d4d4d4;
  padding: 0;
  font-size: 12px;
  line-height: 1.5;
  display: block;
  white-space: pre;
  word-break: normal;
}

/* Syntax highlighting overrides for dark code blocks */
.message-content :deep(pre code .hljs-keyword) {
  color: #569cd6;
}

.message-content :deep(pre code .hljs-string) {
  color: #ce9178;
}

.message-content :deep(pre code .hljs-comment) {
  color: #6a9955;
}

.message-content :deep(pre code .hljs-function) {
  color: #dcdcaa;
}

.message-content :deep(pre code .hljs-number) {
  color: #b5cea8;
}

.message-content :deep(pre code .hljs-class) {
  color: #4ec9b0;
}

.message-content :deep(pre code .hljs-variable) {
  color: #9cdcfe;
}

.message-content :deep(pre code .hljs-attr) {
  color: #9cdcfe;
}

.message-content :deep(pre code .hljs-built_in) {
  color: #4ec9b0;
}

.message-content :deep(pre code .hljs-title) {
  color: #dcdcaa;
}

.message-content :deep(pre code .hljs-params) {
  color: #9cdcfe;
}

/* Strong/Bold */
.message-content :deep(strong) {
  font-weight: 600;
  color: #1a1a1a;
}

/* Emphasis/Italic */
.message-content :deep(em) {
  font-style: italic;
}

/* Headers */
.message-content :deep(h1) {
  font-size: 1.25em !important;
  font-weight: 600 !important;
  line-height: 1.4 !important;
  margin: 10px 0 6px 0 !important;
  padding-bottom: 3px !important;
  border-bottom: 1px solid #e8e8e8;
  color: #1a1a1a;
}

.message-content :deep(h2) {
  font-size: 1.15em !important;
  font-weight: 600 !important;
  line-height: 1.4 !important;
  margin: 8px 0 4px 0 !important;
  color: #1a1a1a;
}

.message-content :deep(h3) {
  font-size: 1.1em !important;
  font-weight: 600 !important;
  line-height: 1.4 !important;
  margin: 6px 0 4px 0 !important;
  color: #1a1a1a;
}

.message-content :deep(h4),
.message-content :deep(h5),
.message-content :deep(h6) {
  font-size: 1.05em !important;
  font-weight: 600 !important;
  line-height: 1.4 !important;
  margin: 6px 0 3px 0 !important;
  color: #333;
}

/* Paragraphs */
.message-content :deep(p) {
  margin: 8px 0;
}

.message-content :deep(p:first-child) {
  margin-top: 0;
}

.message-content :deep(p:last-child) {
  margin-bottom: 0;
}

/* Lists */
.message-content :deep(ul),
.message-content :deep(ol) {
  margin: 8px 0;
  padding-left: 24px;
}

.message-content :deep(li) {
  margin: 4px 0;
}

.message-content :deep(li > ul),
.message-content :deep(li > ol) {
  margin: 4px 0;
}

/* Blockquotes */
.message-content :deep(blockquote) {
  margin: 12px 0;
  padding: 8px 16px;
  border-left: 4px solid #7b1fa2;
  background: #faf5fc;
  color: #555;
  font-style: italic;
}

.message-content :deep(blockquote p) {
  margin: 0;
}

/* Tables */
.message-content :deep(table) {
  border-collapse: collapse;
  margin: 12px 0;
  overflow-x: auto;
  display: block;
}

.message-content :deep(th),
.message-content :deep(td) {
  border: 1px solid #e0e0e0;
  padding: 8px 12px;
  text-align: left;
}

.message-content :deep(th) {
  background: #f5f5f5;
  font-weight: 600;
}

.message-content :deep(tr:nth-child(even)) {
  background: #fafafa;
}

/* Links */
.message-content :deep(a) {
  color: #1976d2;
  text-decoration: none;
}

.message-content :deep(a:hover) {
  text-decoration: underline;
}

/* Horizontal rule */
.message-content :deep(hr) {
  border: none;
  border-top: 1px solid #e0e0e0;
  margin: 16px 0;
}

/* Images */
.message-content :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 4px;
  margin: 8px 0;
}

/* Code Block Wrapper with Header */
.message-content :deep(.code-block-wrapper) {
  margin: 12px 0;
  border-radius: 8px;
  overflow: hidden;
  background: #1e1e1e;
  border: 1px solid #333;
}

.message-content :deep(.code-block-wrapper.is-streaming) {
  border-color: #7b1fa2;
}

.message-content :deep(.code-block-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: #2d2d2d;
  border-bottom: 1px solid #333;
}

.message-content :deep(.code-language) {
  font-size: 11px;
  font-weight: 500;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.message-content :deep(.code-copy-btn) {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: none;
  background: transparent;
  color: #888;
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.2s ease;
}

.message-content :deep(.code-copy-btn:hover) {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.message-content :deep(.code-copy-btn:active) {
  background: rgba(255, 255, 255, 0.2);
}

.message-content :deep(.code-block-wrapper pre) {
  margin: 0;
  border-radius: 0;
  border: none;
}
</style>
