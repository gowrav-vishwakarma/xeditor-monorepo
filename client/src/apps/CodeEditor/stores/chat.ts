import { defineStore } from 'pinia';
import { ref, computed, watch } from 'vue';
import type {
  ChatSession,
  ChatSessionId,
  ChatSessionSummary,
  ChatTurn,
  ContextItem,
  ProjectId,
  TraceEventFileChange,
  SessionTokenStats,
  ContextUsage,
} from '../core/types';
import { useProjectStore } from './project';
import { useLocalCompanionStore } from '../../../stores/localCompanion';
import { useAiConfigStore } from './aiConfig';

export const useChatStore = defineStore('chat', () => {
  const projectStore = useProjectStore();
  const companionStore = useLocalCompanionStore();

  const currentSession = ref<ChatSession | null>(null);
  const sessions = ref<ChatSessionSummary[]>([]);
  const isLoading = ref(false);

  const hasCurrentSession = computed(() => currentSession.value !== null);
  const currentTurnCount = computed(() => currentSession.value?.turns.length ?? 0);

  // Session token totals - computed from all turns
  const sessionTokenStats = computed<SessionTokenStats>(() => {
    const stats: SessionTokenStats = {
      totalTokens: 0,
      promptTokens: 0,
      completionTokens: 0,
      byFamily: {},
    };

    if (!currentSession.value) return stats;

    for (const turn of currentSession.value.turns) {
      const usage = turn.usage;
      if (usage) {
        stats.totalTokens += usage.totalTokens;
        stats.promptTokens += usage.promptTokens;
        stats.completionTokens += usage.completionTokens;
      }

      // Track per-family usage
      const family = turn.modelSnapshot?.family || turn.modelId.split('-')[0] || 'unknown';
      if (usage) {
        if (!stats.byFamily[family]) {
          stats.byFamily[family] = {
            totalTokens: 0,
            promptTokens: 0,
            completionTokens: 0,
          };
        }
        stats.byFamily[family].totalTokens += usage.totalTokens;
        stats.byFamily[family].promptTokens += usage.promptTokens;
        stats.byFamily[family].completionTokens += usage.completionTokens;
      }
    }

    return stats;
  });

  // Last turn's context usage - useful for showing current context fill
  const lastTurnContextUsage = computed<ContextUsage | null>(() => {
    if (!currentSession.value || currentSession.value.turns.length === 0) return null;
    const lastTurn = currentSession.value.turns[currentSession.value.turns.length - 1];
    return lastTurn?.contextUsage || null;
  });

  // ─────────────────────────────────────────────────────────────────────────
  // Initialization
  // ─────────────────────────────────────────────────────────────────────────

  async function initialize(projectId: ProjectId | null): Promise<void> {
    if (!projectId) {
      sessions.value = [];
      currentSession.value = null;
      return;
    }

    isLoading.value = true;
    try {
      const response = await companionStore.request<{
        success: boolean;
        chats?: Array<{
          id: string;
          projectId: string;
          title: string;
          createdAt: number;
          updatedAt: number;
          turnCount: number;
        }>;
        error?: string;
      }>('chat_list', { projectId });

      if (response.success && response.chats) {
        sessions.value = response.chats.map((chat) => ({
          id: chat.id,
          projectId: chat.projectId,
          title: chat.title,
          createdAt: chat.createdAt,
          updatedAt: chat.updatedAt,
          turnCount: chat.turnCount,
        }));
      }
    } catch (error) {
      console.error('Failed to load chats:', error);
      sessions.value = [];
    } finally {
      isLoading.value = false;
    }
  }

  // Watch for project changes and reload sessions
  watch(
    () => projectStore.activeProjectId,
    async (projectId) => {
      await initialize(projectId);
      // Clear current session when switching projects
      currentSession.value = null;
    },
  );

  // ─────────────────────────────────────────────────────────────────────────
  // Session Management
  // ─────────────────────────────────────────────────────────────────────────

  async function createSession(projectId: ProjectId, title?: string): Promise<ChatSession> {
    const response = await companionStore.request<{
      success: boolean;
      chat?: {
        id: string;
        projectId: string;
        title: string;
        createdAt: number;
        updatedAt: number;
        turns: unknown[];
      };
      error?: string;
    }>('chat_create', { projectId, title });

    if (!response.success || !response.chat) {
      throw new Error(response.error || 'Failed to create chat');
    }

    const chat = response.chat;
    const session: ChatSession = {
      id: chat.id,
      projectId: chat.projectId,
      title: chat.title,
      createdAt: chat.createdAt,
      updatedAt: chat.updatedAt,
      turns: convertTurns(chat.turns),
    };

    currentSession.value = session;
    await initialize(projectId);

    return session;
  }

  async function loadSession(sessionId: ChatSessionId): Promise<void> {
    const projectId = projectStore.activeProjectId;
    if (!projectId) {
      throw new Error('No active project');
    }

    const response = await companionStore.request<{
      success: boolean;
      chat?: {
        id: string;
        projectId: string;
        title: string;
        createdAt: number;
        updatedAt: number;
        turns: unknown[];
      };
      error?: string;
    }>('chat_load', { projectId, chatId: sessionId });

    if (!response.success || !response.chat) {
      throw new Error(response.error || `Chat session not found: ${sessionId}`);
    }

    const chat = response.chat;
    currentSession.value = {
      id: chat.id,
      projectId: chat.projectId,
      title: chat.title,
      createdAt: chat.createdAt,
      updatedAt: chat.updatedAt,
      turns: convertTurns(chat.turns),
    };
  }

  async function renameSession(sessionId: ChatSessionId, title: string): Promise<void> {
    const projectId = projectStore.activeProjectId;
    if (!projectId) {
      throw new Error('No active project');
    }

    const response = await companionStore.request<{
      success: boolean;
      chat?: {
        id: string;
        projectId: string;
        title: string;
        createdAt: number;
        updatedAt: number;
        turns: unknown[];
      };
      error?: string;
    }>('chat_rename', { projectId, chatId: sessionId, title });

    if (!response.success) {
      throw new Error(response.error || 'Failed to rename chat');
    }

    // Update current session if it's the one being renamed
    if (currentSession.value?.id === sessionId && response.chat) {
      currentSession.value.title = response.chat.title;
      currentSession.value.updatedAt = response.chat.updatedAt;
    }

    await initialize(projectId);
  }

  async function deleteSessionById(sessionId: ChatSessionId): Promise<void> {
    const projectId = projectStore.activeProjectId;
    if (!projectId) {
      throw new Error('No active project');
    }

    const response = await companionStore.request<{
      success: boolean;
      error?: string;
    }>('chat_delete', { projectId, chatId: sessionId });

    if (!response.success) {
      throw new Error(response.error || 'Failed to delete chat');
    }

    // Clear current session if it's the one being deleted
    if (currentSession.value?.id === sessionId) {
      currentSession.value = null;
    }

    await initialize(projectId);
  }

  function clearCurrentSession(): void {
    currentSession.value = null;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Message Sending (with streaming events)
  // ─────────────────────────────────────────────────────────────────────────

  async function sendMessage(
    message: string,
    context: ContextItem[],
    onEvent?: (eventType: string, data: unknown) => void,
  ): Promise<void> {
    const projectId = projectStore.activeProjectId;
    if (!projectId) {
      throw new Error('No active project');
    }

    // Ensure we have a current session
    if (!currentSession.value) {
      await createSession(projectId);
    }

    if (!currentSession.value) {
      throw new Error('Failed to create or load current session');
    }

    const aiConfig = useAiConfigStore();
    const activeModel = aiConfig.activeModel;
    if (!activeModel) {
      throw new Error('No active model selected');
    }

    // Prepare model config for backend
    // Ensure contextWindow is included (default to 0 if not set)
    const modelConfig = {
      id: activeModel.id,
      provider: activeModel.provider,
      family: activeModel.family,
      version: activeModel.version,
      contextWindow: activeModel.contextWindow ?? 0, // Include contextWindow for context usage tracking
      connection: activeModel.connection,
      localCompanion: activeModel.localCompanion,
      setId: aiConfig.activeSetId,
      hfToken: companionStore.huggingFaceToken || undefined,
      providerParams: activeModel.providerParams,
      extraPayload: activeModel.extraPayload,
    };

    // Stream chat message
    await companionStore.streamRequest(
      'chat_message',
      {
        projectId,
        chatId: currentSession.value.id,
        message,
        context: context.map((item) => ({
          id: item.id,
          type: item.type,
          content: item.content,
          metadata: item.metadata,
        })),
        mode: aiConfig.activeMode,
        model: modelConfig,
        debug: aiConfig.debugEnabled,
      },
      (event: { eventType: string; data: unknown }) => {
        const { eventType, data } = event;

        // Handle different event types
        switch (eventType) {
          case 'thinking_start':
            // UI can show thinking indicator
            onEvent?.(eventType, data);
            break;

          case 'thinking_chunk':
            // Append thinking content
            onEvent?.(eventType, data);
            break;

          case 'thinking_end':
            // Hide/collapse thinking
            onEvent?.(eventType, data);
            break;

          case 'content_chunk':
            // Append response content
            onEvent?.(eventType, data);
            break;

          case 'tool_start':
            // Show tool execution card
            onEvent?.(eventType, data);
            break;

          case 'tool_chunk':
            // Stream tool output
            onEvent?.(eventType, data);
            break;

          case 'tool_result':
            // Update tool card with result
            onEvent?.(eventType, data);
            break;

          case 'file_change':
            // Handle file change event (for diff preview)
            onEvent?.(eventType, data);
            break;

          case 'sub_agent_start':
            // Handle sub-agent start event (for delegate_task nested tool calls)
            onEvent?.(eventType, data);
            break;

          case 'sub_agent_end':
            // Handle sub-agent end event
            onEvent?.(eventType, data);
            break;

          case 'context_compression':
            onEvent?.(eventType, data);
            break;

          case 'turn_complete':
            // Reload session to get updated turn
            void loadSession(currentSession.value!.id);
            onEvent?.(eventType, data);
            break;

          case 'error':
            // Show error
            onEvent?.(eventType, data);
            break;
        }
      },
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Helper Functions
  // ─────────────────────────────────────────────────────────────────────────

  function convertTurns(turns: unknown[]): ChatTurn[] {
    return turns.map((turn: unknown) => {
      const t = turn as {
        id: string;
        timestamp: number;
        mode: string;
        modelId: string;
        userMessage: string;
        userContext?: unknown[];
        assistantMessage: string;
        includeInContext?: boolean;
        meta?: {
          thinking?: string;
          systemPrompt?: string;
          usage?: {
            promptTokens?: number;
            completionTokens?: number;
            totalTokens?: number;
            cachedTokens?: number;
            reasoningTokens?: number;
          };
          usageBreakdown?: {
            main: { promptTokens?: number; completionTokens?: number; totalTokens?: number };
            subAgents: { promptTokens?: number; completionTokens?: number; totalTokens?: number };
            total: { promptTokens?: number; completionTokens?: number; totalTokens?: number };
            llmCallCount?: number;
          };
          contextUsage?: {
            usedPromptTokens?: number;
            contextWindow?: number;
            fillPercent?: number;
          };
          modelSnapshot?: {
            id?: string;
            provider?: string;
            family?: string;
            version?: string;
            contextWindow?: number;
          };
          traceEvents?: unknown[];
          error?: string | undefined;
          artifacts?: Array<{
            path: string;
            type: string;
            name: string;
            toolCallId?: string;
          }>;
        };
        toolCalls?: Array<{
          id: string;
          tool: string;
          args: unknown;
          result?: unknown;
          error?: string;
          includeInContext?: boolean;
          tcId?: string;
          contextSummary?: string;
        }>;
      };

      // Convert traceEvents, ensuring file_change events are properly typed
      const rawTraceEvents = t.meta?.traceEvents || [];
      const traceEvents: ChatTurn['traceEvents'] = rawTraceEvents.map((event: unknown) => {
        const e = event as Record<string, unknown>;
        // If it's already a file_change event, ensure it has the right shape
        if (e.type === 'file_change') {
          return {
            type: 'file_change' as const,
            id: typeof e.id === 'string' ? e.id : `file_change_${Date.now()}`,
            timestamp: typeof e.timestamp === 'number' ? e.timestamp : t.timestamp,
            toolCallId: typeof e.toolCallId === 'string' ? e.toolCallId : '',
            path: typeof e.path === 'string' ? e.path : '',
            changeType: (typeof e.changeType === 'string' ? e.changeType : 'modified') as
              | 'created'
              | 'modified'
              | 'deleted',
            ...(typeof e.beforeContent === 'string' && { beforeContent: e.beforeContent }),
            ...(typeof e.afterContent === 'string' && { afterContent: e.afterContent }),
          } as TraceEventFileChange;
        }
        return e as unknown as ChatTurn['traceEvents'][number];
      });

      // Check if traceEvents already has thinking/tool_call events (from server persistence)
      const hasPersistedThinking = traceEvents.some((e) => e.type === 'thinking');
      const hasPersistedToolCalls = traceEvents.some((e) => e.type === 'tool_call');

      const chatTurn: ChatTurn = {
        id: t.id,
        timestamp: t.timestamp,
        mode: t.mode,
        modelId: t.modelId,
        userMessage: t.userMessage,
        assistantMessage: t.assistantMessage,
        systemPrompt: t.meta?.systemPrompt || '',
        contextItems: (t.userContext || []) as ContextItem[],
        traceEvents,
        error: t.meta?.error,
      };

      // Add usage if present
      if (t.meta?.usage) {
        chatTurn.usage = {
          promptTokens: t.meta.usage.promptTokens || 0,
          completionTokens: t.meta.usage.completionTokens || 0,
          totalTokens: t.meta.usage.totalTokens || 0,
          ...(t.meta.usage.cachedTokens !== undefined && {
            cachedTokens: t.meta.usage.cachedTokens,
          }),
          ...(t.meta.usage.reasoningTokens !== undefined && {
            reasoningTokens: t.meta.usage.reasoningTokens,
          }),
        };
      }

      // Add usage breakdown if present
      if (t.meta?.usageBreakdown) {
        const ub = t.meta.usageBreakdown;
        chatTurn.usageBreakdown = {
          main: {
            promptTokens: ub.main?.promptTokens || 0,
            completionTokens: ub.main?.completionTokens || 0,
            totalTokens: ub.main?.totalTokens || 0,
          },
          subAgents: {
            promptTokens: ub.subAgents?.promptTokens || 0,
            completionTokens: ub.subAgents?.completionTokens || 0,
            totalTokens: ub.subAgents?.totalTokens || 0,
          },
          total: {
            promptTokens: ub.total?.promptTokens || 0,
            completionTokens: ub.total?.completionTokens || 0,
            totalTokens: ub.total?.totalTokens || 0,
          },
          ...(ub.llmCallCount !== undefined && { llmCallCount: ub.llmCallCount }),
        };
      }

      // Add context usage if present
      if (t.meta?.contextUsage) {
        chatTurn.contextUsage = {
          usedPromptTokens: t.meta.contextUsage.usedPromptTokens || 0,
          contextWindow: t.meta.contextUsage.contextWindow || 0,
          fillPercent: t.meta.contextUsage.fillPercent || 0,
        };
      }

      // Add model snapshot if present
      if (t.meta?.modelSnapshot) {
        chatTurn.modelSnapshot = {
          id: t.meta.modelSnapshot.id || '',
          provider: t.meta.modelSnapshot.provider || '',
          family: t.meta.modelSnapshot.family || '',
          ...(t.meta.modelSnapshot.version && { version: t.meta.modelSnapshot.version }),
          contextWindow: t.meta.modelSnapshot.contextWindow || 0,
        };
      }

      // Only add thinking/tool_call events if they're not already persisted (backwards compatibility)
      if (!hasPersistedThinking && t.meta?.thinking) {
        // Fallback: old format with single thinking string
        chatTurn.traceEvents.push({
          type: 'thinking',
          id: `thinking-${t.id}`,
          timestamp: t.timestamp,
          content: t.meta.thinking,
          includeInContext: false, // Thinking is never sent to LLM
        });
      }

      // Add tool_result events for status indicators (even if tool_call is persisted)
      // This ensures we have completion status for UI
      if (t.toolCalls) {
        for (const toolCall of t.toolCalls) {
          // Only add tool_call if not already persisted
          if (!hasPersistedToolCalls) {
            const toolCallEvent: Extract<ChatTurn['traceEvents'][number], { type: 'tool_call' }> = {
              type: 'tool_call',
              id: toolCall.id,
              timestamp: t.timestamp,
              toolName: toolCall.tool,
              arguments: toolCall.args as Record<string, unknown>,
              output: '',
            };
            // Populate output from result or error
            if (toolCall.error) {
              toolCallEvent.output = `Error: ${toolCall.error}`;
            } else if (toolCall.result !== undefined && toolCall.result !== null) {
              if (typeof toolCall.result === 'string') {
                toolCallEvent.output = toolCall.result;
              } else if (
                typeof toolCall.result === 'number' ||
                typeof toolCall.result === 'boolean' ||
                typeof toolCall.result === 'bigint'
              ) {
                toolCallEvent.output = String(toolCall.result);
              } else {
                // For objects, arrays, and other complex types, use JSON.stringify
                toolCallEvent.output = JSON.stringify(toolCall.result, null, 2);
              }
            }
            chatTurn.traceEvents.push(toolCallEvent);
          }

          // Always add tool_result for status (check if already exists first)
          const existingResult = chatTurn.traceEvents.find((e) => {
            if (e.type === 'tool_result') {
              return e.toolCallId === toolCall.id;
            }
            return false;
          });
          if (!existingResult) {
            const toolResultEvent: Extract<
              ChatTurn['traceEvents'][number],
              { type: 'tool_result' }
            > = {
              type: 'tool_result',
              id: `result-${toolCall.id}`,
              timestamp: t.timestamp,
              toolCallId: toolCall.id,
              result: toolCall.result,
              ...(toolCall.tcId && { tcId: toolCall.tcId }),
              ...(toolCall.contextSummary && { contextSummary: toolCall.contextSummary }),
            };
            if (toolCall.error) {
              toolResultEvent.error = toolCall.error;
            }
            chatTurn.traceEvents.push(toolResultEvent);
          }
        }
        // Cross-reference: propagate contextSummary from toolCalls to matching tool_result trace events
        for (const toolCall of t.toolCalls) {
          if (toolCall.contextSummary) {
            const matchingResult = chatTurn.traceEvents.find(
              (e) => e.type === 'tool_result' && e.toolCallId === toolCall.id,
            );
            if (matchingResult && matchingResult.type === 'tool_result') {
              matchingResult.contextSummary = toolCall.contextSummary;
            }
          }
        }
      }

      // Add artifacts if present in meta
      if (t.meta?.artifacts && Array.isArray(t.meta.artifacts)) {
        chatTurn.artifacts = t.meta.artifacts.map((artifact) => ({
          path: artifact.path,
          type: artifact.type,
          name: artifact.name,
          ...(artifact.toolCallId && { toolCallId: artifact.toolCallId }),
        }));
      }

      return chatTurn;
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Truncation (for edit and resend)
  // ─────────────────────────────────────────────────────────────────────────

  async function truncateFromTurn(turnId: string): Promise<void> {
    const projectId = projectStore.activeProjectId;
    if (!projectId) {
      throw new Error('No active project');
    }

    if (!currentSession.value) {
      throw new Error('No active chat session');
    }

    const response = await companionStore.request<{
      success: boolean;
      chat?: {
        id: string;
        projectId: string;
        title: string;
        createdAt: number;
        updatedAt: number;
        turns: unknown[];
      };
      error?: string;
    }>('chat_truncate', {
      projectId,
      chatId: currentSession.value.id,
      turnId,
    });

    if (!response.success || !response.chat) {
      throw new Error(response.error || 'Failed to truncate chat');
    }

    // Update current session with truncated data
    const chat = response.chat;
    currentSession.value = {
      id: chat.id,
      projectId: chat.projectId,
      title: chat.title,
      createdAt: chat.createdAt,
      updatedAt: chat.updatedAt,
      turns: convertTurns(chat.turns),
    };

    // Refresh session list
    await initialize(projectId);
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Cleanup
  // ─────────────────────────────────────────────────────────────────────────

  async function cleanupProjectSessions(projectId: ProjectId): Promise<void> {
    // Backend handles chat deletion when project is deleted
    // Just clear local state
    if (currentSession.value?.projectId === projectId) {
      currentSession.value = null;
    }
    await initialize(projectId);
  }

  return {
    // State
    currentSession,
    sessions,
    isLoading,

    // Computed
    hasCurrentSession,
    currentTurnCount,
    sessionTokenStats,
    lastTurnContextUsage,

    // Actions
    initialize,
    createSession,
    loadSession,
    renameSession,
    deleteSessionById,
    clearCurrentSession,
    sendMessage,
    truncateFromTurn,
    cleanupProjectSessions,
  };
});
