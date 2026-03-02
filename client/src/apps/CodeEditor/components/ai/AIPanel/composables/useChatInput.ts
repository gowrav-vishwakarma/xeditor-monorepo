import { ref, computed, watch, type Ref } from 'vue';
import type { QInput } from 'quasar';
import { useQuasar } from 'quasar';
import { useProjectStore } from '../../../../stores/project';
import { useChatStore } from '../../../../stores/chat';
import { useEditorStore } from '../../../../stores/editor';
import { ContextManager } from '../../../../core/context/ContextManager';
import { useMention } from './useMention';
import { useTraceEvents } from './useTraceEvents';
import type { TraceEvent, EditorTab, ChatSessionId } from 'src/apps/CodeEditor/core/types';
import { isPreviewable, getFileExtension } from '../../../../config/previewable';
import type { PendingQuestion, Question, QuestionSkippedData } from '../types/questions';
import { QUESTION_SKIPPED_MARKER as SKIP_MARKER } from '../types/questions';

// Markers for command confirmation messages
export const COMMAND_APPROVED_MARKER = '<!--COMMAND_APPROVED-->';
export const COMMAND_SKIPPED_MARKER = '<!--COMMAND_SKIPPED-->';

export interface PendingCommand {
  command: string;
  id: string;
}

export interface PendingTurn {
  userMessage: string;
  assistantMessage: string;
  currentThinkingIdByParent: Record<string, string | null>; // Track thinking event IDs per parentId
  currentAssistantMessageIdByParent: Record<string, string | null>; // Track assistant_message IDs per parentId
  traceEvents: TraceEvent[];
  currentActivity: string | undefined; // Current activity description (e.g., "Executing read_file...")
  error: string | undefined;
}

export function useChatInput(chatInputRef: Ref<InstanceType<typeof QInput> | null>) {
  const projectStore = useProjectStore();
  const chatStore = useChatStore();
  const editorStore = useEditorStore();
  const $q = useQuasar();
  const contextManager = new ContextManager();
  const { generateTraceId } = useTraceEvents();

  const userInput = ref('');
  const isLoading = ref(false);
  const pendingTurn = ref<PendingTurn | null>(null);
  // Store pending questions per chat ID
  const pendingQuestionsByChatId = ref<Record<ChatSessionId, PendingQuestion>>({});
  // Store pending commands per chat ID
  const pendingCommandsByChatId = ref<Record<ChatSessionId, PendingCommand>>({});

  // Computed: get pending question for current chat
  const pendingQuestion = computed<PendingQuestion | null>(() => {
    const currentChatId = chatStore.currentSession?.id;
    if (!currentChatId) return null;
    return pendingQuestionsByChatId.value[currentChatId] || null;
  });

  // Computed: get pending command for current chat
  const pendingCommand = computed<PendingCommand | null>(() => {
    const currentChatId = chatStore.currentSession?.id;
    if (!currentChatId) return null;
    return pendingCommandsByChatId.value[currentChatId] || null;
  });

  const mention = useMention(chatInputRef);

  const hasProject = computed(() => projectStore.hasConnectedFolders);

  function onChatKeydown(event: KeyboardEvent) {
    if (mention.showMentionMenu.value && mention.filteredMentions.value.length > 0) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        mention.mentionSelectedIndex.value =
          (mention.mentionSelectedIndex.value + 1) % mention.filteredMentions.value.length;
        return;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        mention.mentionSelectedIndex.value =
          (mention.mentionSelectedIndex.value - 1 + mention.filteredMentions.value.length) %
          mention.filteredMentions.value.length;
        return;
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault();
        const selected = mention.filteredMentions.value[mention.mentionSelectedIndex.value];
        if (selected) {
          userInput.value = mention.insertMention(selected, userInput.value);
        }
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        mention.showMentionMenu.value = false;
        return;
      }
    }

    // Default Enter behavior: send message
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  }

  function onChatInput() {
    mention.updateMentionState(userInput.value);
  }

  function stopGeneration() {
    // TODO: Implement cancellation via companion store
    isLoading.value = false;
  }

  /**
   * Convert an absolute system path to editor's folder-based path format: {folderId}/{relativePath}
   * Returns null if the path is not under any project folder.
   */
  function convertAbsolutePathToEditorPath(absolutePath: string): string | null {
    if (!projectStore.activeProject) {
      return null;
    }

    // Normalize the absolute path (handle both / and \ separators)
    const normalizedAbsolutePath = absolutePath.replace(/\\/g, '/');

    // Check each project folder to see if the absolute path is under it
    for (const folder of projectStore.activeProject.folders) {
      const normalizedFolderPath = folder.systemPath.replace(/\\/g, '/');

      // Check if the absolute path starts with the folder's system path
      if (
        normalizedAbsolutePath.startsWith(normalizedFolderPath + '/') ||
        normalizedAbsolutePath === normalizedFolderPath
      ) {
        // Calculate relative path
        const relativePath =
          normalizedAbsolutePath === normalizedFolderPath
            ? ''
            : normalizedAbsolutePath.slice(normalizedFolderPath.length + 1);

        // Return in editor format: {folderId}/{relativePath}
        return relativePath ? `${folder.id}/${relativePath}` : folder.id;
      }
    }

    // Path is not under any project folder
    return null;
  }

  /**
   * Open a file by absolute path, even if it's outside project folders.
   * Reads the file content directly and creates a tab.
   */
  async function openFileByAbsolutePath(absolutePath: string): Promise<void> {
    try {
      // Check if file is already open (by absolute path)
      const existingTab = editorStore.tabs.find((tab) => tab.filePath === absolutePath);
      if (existingTab) {
        editorStore.setActiveTab(existingTab.id);
        return;
      }

      // Read file content using editor I/O (full content, no chunking)
      const content = await projectStore.readAbsoluteFileForEditor(absolutePath);

      // Determine language from extension
      const extension = absolutePath.split('.').pop()?.toLowerCase();
      const languageMap: Record<string, string> = {
        ts: 'typescript',
        tsx: 'typescript',
        js: 'javascript',
        jsx: 'javascript',
        vue: 'html',
        py: 'python',
        rs: 'rust',
        go: 'go',
        java: 'java',
        cpp: 'cpp',
        c: 'c',
        json: 'json',
        yaml: 'yaml',
        yml: 'yaml',
        md: 'markdown',
        html: 'html',
        css: 'css',
        scss: 'scss',
        sql: 'sql',
        sh: 'shell',
        xml: 'xml',
        svg: 'xml',
      };

      const language = languageMap[extension || ''] || 'plaintext';
      const fileName = absolutePath.split('/').pop() || absolutePath;

      // Determine initial view mode: preview for previewable files, code otherwise
      const fileExtension = getFileExtension(absolutePath);
      const initialViewMode: 'code' | 'preview' = isPreviewable(fileExtension) ? 'preview' : 'code';

      // Create tab manually
      const tab: EditorTab = {
        id: `tab-${Date.now()}-${Math.random()}`,
        filePath: absolutePath,
        fileName,
        content,
        originalContent: content,
        isDirty: false,
        language,
        viewMode: initialViewMode,
      };

      editorStore.tabs.push(tab);
      editorStore.setActiveTab(tab.id);
    } catch (error) {
      console.error('Error opening file by absolute path:', error);
      throw error;
    }
  }

  async function sendMessage() {
    if (!userInput.value.trim() || isLoading.value || !hasProject.value) return;

    const projectId = projectStore.activeProjectId;
    if (!projectId) {
      throw new Error('No active project');
    }

    // Ensure we have a current session
    if (!chatStore.currentSession) {
      await chatStore.createSession(projectId);
    }

    const currentChatId = chatStore.currentSession?.id;
    if (!currentChatId) {
      throw new Error('No active chat session');
    }

    let query = userInput.value.trim();
    userInput.value = '';

    // Check for implicit skip: if there's a pending question and user is sending a normal message
    const currentPendingQuestion = pendingQuestion.value;
    if (currentPendingQuestion && !query.startsWith('<!--QUESTION_RESPONSE-->')) {
      // User is implicitly skipping by sending a new message
      // Bundle the skipped question + user message into a structured payload
      const skippedData: QuestionSkippedData = {
        type: 'question_skipped',
        ...(currentPendingQuestion.title && { title: currentPendingQuestion.title }),
        questions: currentPendingQuestion.questions,
        user_message: query,
      };
      query = `${SKIP_MARKER}${JSON.stringify(skippedData)}`;

      // Clear pending question for this chat
      delete pendingQuestionsByChatId.value[currentChatId];
    }

    // Check for implicit skip: if there's a pending command and user is sending a normal message
    const currentPendingCommand = pendingCommand.value;
    if (currentPendingCommand && !query.startsWith('<!--COMMAND_')) {
      // User is implicitly skipping by sending a new message
      // Format: <!--COMMAND_SKIPPED-->{"id":"hash","command":"...","user_message":"..."}
      const skipData = {
        id: currentPendingCommand.id,
        command: currentPendingCommand.command,
        user_message: query,
      };
      query = `${COMMAND_SKIPPED_MARKER}${JSON.stringify(skipData)}`;

      // Clear pending command for this chat
      delete pendingCommandsByChatId.value[currentChatId];
    }

    isLoading.value = true;

    // Initialize pending turn for UI feedback
    pendingTurn.value = {
      userMessage: query,
      assistantMessage: '',
      currentThinkingIdByParent: {},
      currentAssistantMessageIdByParent: {},
      traceEvents: [] as TraceEvent[],
      currentActivity: undefined,
      error: undefined,
    };

    try {
      // Get context and capture trace events
      const currentFileContext = await contextManager.getCurrentFileContext();
      const event1: TraceEvent = {
        type: 'context_retrieval',
        id: generateTraceId(),
        timestamp: Date.now(),
        contextType: 'current_file',
        items: currentFileContext,
      };
      if (pendingTurn.value) pendingTurn.value.traceEvents.push(event1);

      const selectedCodeContext = await contextManager.getSelectedCodeContext();
      const event2: TraceEvent = {
        type: 'context_retrieval',
        id: generateTraceId(),
        timestamp: Date.now(),
        contextType: 'selected_code',
        items: selectedCodeContext,
      };
      if (pendingTurn.value) pendingTurn.value.traceEvents.push(event2);

      const context = [...currentFileContext, ...selectedCodeContext];
      const rankedContext = await contextManager.rankContext(context, query);
      const event3: TraceEvent = {
        type: 'context_retrieval',
        id: generateTraceId(),
        timestamp: Date.now(),
        contextType: 'ranked',
        items: rankedContext,
      };
      if (pendingTurn.value) pendingTurn.value.traceEvents.push(event3);

      const limitedContext = await contextManager.limitContext(rankedContext, 4000);
      const event4: TraceEvent = {
        type: 'context_retrieval',
        id: generateTraceId(),
        timestamp: Date.now(),
        contextType: 'limited',
        items: limitedContext,
      };
      if (pendingTurn.value) pendingTurn.value.traceEvents.push(event4);

      // Send message via chat store (handles streaming)
      await chatStore.sendMessage(query, limitedContext, (eventType, data) => {
        if (!pendingTurn.value) return;

        switch (eventType) {
          case 'thinking_start': {
            const parentKey =
              ((data as Record<string, unknown>)?.parentId as string | undefined) ?? 'root';
            // Create a NEW thinking trace event for each thinking block
            // But reuse existing one if we already have an active thinking event (safeguard against rapid events)
            if (!pendingTurn.value.currentThinkingIdByParent[parentKey]) {
              const newThinkingId = generateTraceId();
              const newEvent: Extract<TraceEvent, { type: 'thinking' }> = {
                type: 'thinking',
                id: newThinkingId,
                timestamp: Date.now(),
                content: '',
                includeInContext: false, // Thinking is never sent to LLM
                ...(parentKey !== 'root' && { parentId: parentKey }),
              };
              pendingTurn.value.traceEvents.push(newEvent);
              pendingTurn.value.currentThinkingIdByParent[parentKey] = newThinkingId;
            }
            // If currentThinkingId already exists, reuse it (don't create duplicate)
            break;
          }

          case 'thinking_chunk': {
            const parentKey =
              ((data as Record<string, unknown>)?.parentId as string | undefined) ?? 'root';
            // Append to the current thinking trace event
            const thinkingData = data as { content: string };
            const currentId = pendingTurn.value.currentThinkingIdByParent[parentKey];

            if (currentId) {
              const thinkingEvent = pendingTurn.value.traceEvents.find(
                (e) => e.type === 'thinking' && e.id === currentId,
              ) as Extract<TraceEvent, { type: 'thinking' }> | undefined;

              if (thinkingEvent) {
                thinkingEvent.content += thinkingData.content;
              }
            }
            break;
          }

          case 'thinking_end': {
            const parentKey =
              ((data as Record<string, unknown>)?.parentId as string | undefined) ?? 'root';
            // Clear current thinking ID - next thinking_start will create a new event
            pendingTurn.value.currentThinkingIdByParent[parentKey] = null;
            break;
          }

          case 'content_chunk': {
            const parentKey =
              ((data as Record<string, unknown>)?.parentId as string | undefined) ?? 'root';
            // Append response content
            const contentData = data as { content: string };
            pendingTurn.value.assistantMessage += contentData.content;
            // Clear current activity when we start receiving final content
            pendingTurn.value.currentActivity = undefined;

            // Create or append to assistant_message trace event
            if (!pendingTurn.value.currentAssistantMessageIdByParent[parentKey]) {
              const newAssistantMessageId = generateTraceId();
              const newEvent: Extract<TraceEvent, { type: 'assistant_message' }> = {
                type: 'assistant_message',
                id: newAssistantMessageId,
                timestamp: Date.now(),
                content: '',
                ...(parentKey !== 'root' && { parentId: parentKey }),
              };
              pendingTurn.value.traceEvents.push(newEvent);
              pendingTurn.value.currentAssistantMessageIdByParent[parentKey] =
                newAssistantMessageId;
            }

            // Append chunk to current assistant_message event
            const currentId = pendingTurn.value.currentAssistantMessageIdByParent[parentKey];
            if (currentId) {
              const assistantMessageEvent = pendingTurn.value.traceEvents.find(
                (e) => e.type === 'assistant_message' && e.id === currentId,
              ) as Extract<TraceEvent, { type: 'assistant_message' }> | undefined;

              if (assistantMessageEvent) {
                assistantMessageEvent.content += contentData.content;
              }
            }
            break;
          }

          case 'step_start': {
            const parentKey =
              ((data as Record<string, unknown>)?.parentId as string | undefined) ?? 'root';
            // Agent is starting a new iteration (processing tool result)
            // Reset assistant message ID - next text will be a new segment
            pendingTurn.value.currentAssistantMessageIdByParent[parentKey] = null;
            pendingTurn.value.currentActivity = 'Processing tool result...';
            break;
          }

          case 'tool_start': {
            const parentKey =
              ((data as Record<string, unknown>)?.parentId as string | undefined) ?? 'root';
            // Reset assistant message ID when tool starts - next text will be a new segment
            pendingTurn.value.currentAssistantMessageIdByParent[parentKey] = null;

            // Show tool execution card
            const toolStartData = data as {
              tool: string;
              args: unknown;
              id: string;
              parentId?: string;
            };
            pendingTurn.value.currentActivity = `Executing ${toolStartData.tool}...`;
            // Add to trace events
            pendingTurn.value.traceEvents.push({
              type: 'tool_call',
              id: toolStartData.id,
              timestamp: Date.now(),
              toolName: toolStartData.tool,
              arguments: toolStartData.args as Record<string, unknown>,
              output: '', // Initialize output for streaming
              ...(toolStartData.parentId && { parentId: toolStartData.parentId }),
            });
            break;
          }

          case 'tool_chunk': {
            // Accumulate streaming tool output
            const toolChunkData = data as { id: string; content: string };
            const toolCallEvent = pendingTurn.value.traceEvents.find(
              (e) => e.type === 'tool_call' && e.id === toolChunkData.id,
            ) as Extract<TraceEvent, { type: 'tool_call' }> | undefined;

            if (toolCallEvent) {
              // Accumulate output
              toolCallEvent.output = (toolCallEvent.output || '') + toolChunkData.content;
            }
            break;
          }

          case 'tool_result': {
            // Update tool card with result
            const toolResultData = data as {
              tool: string;
              result?: unknown;
              error?: string;
              id: string;
              parentId?: string;
            };
            const toolResultEvent: Extract<TraceEvent, { type: 'tool_result' }> = {
              type: 'tool_result',
              id: `result-${toolResultData.id}`,
              timestamp: Date.now(),
              toolCallId: toolResultData.id,
              result: toolResultData.result,
              ...(toolResultData.parentId && { parentId: toolResultData.parentId }),
            };
            if (toolResultData.error) {
              toolResultEvent.error = toolResultData.error;
            }
            pendingTurn.value.traceEvents.push(toolResultEvent);
            pendingTurn.value.currentActivity = undefined;

            // Update corresponding tool_call event output with final result/error
            const toolCallEvent = pendingTurn.value.traceEvents.find(
              (e) => e.type === 'tool_call' && e.id === toolResultData.id,
            ) as Extract<TraceEvent, { type: 'tool_call' }> | undefined;

            if (toolCallEvent) {
              if (toolResultData.error) {
                // Include error message in output
                toolCallEvent.output = `Error: ${toolResultData.error}`;
              } else if (toolResultData.result !== undefined && toolResultData.result !== null) {
                // Format result as string for output field
                if (typeof toolResultData.result === 'string') {
                  toolCallEvent.output = toolResultData.result;
                } else if (
                  typeof toolResultData.result === 'number' ||
                  typeof toolResultData.result === 'boolean' ||
                  typeof toolResultData.result === 'bigint'
                ) {
                  toolCallEvent.output = String(toolResultData.result);
                } else {
                  // For objects, arrays, and other complex types, use JSON.stringify
                  toolCallEvent.output = JSON.stringify(toolResultData.result, null, 2);
                }
              }
            }

            // Check for ask_question action
            const result = toolResultData.result as Record<string, unknown> | undefined;
            if (result && result.action === 'ask_question') {
              const currentChatId = chatStore.currentSession?.id;
              if (currentChatId) {
                const questionData: PendingQuestion = {
                  questions: result.questions as Question[],
                };
                if (result.title && typeof result.title === 'string') {
                  questionData.title = result.title;
                }
                // Store pending question for the current chat
                pendingQuestionsByChatId.value[currentChatId] = questionData;
              }
            }

            // Check for confirm_command action
            if (result && result.action === 'confirm_command') {
              const currentChatId = chatStore.currentSession?.id;
              if (currentChatId) {
                const commandData: PendingCommand = {
                  command: result.command as string,
                  id: result.id as string,
                };
                // Store pending command for the current chat
                pendingCommandsByChatId.value[currentChatId] = commandData;
              }
            }

            // Check for open_in_editor action (e.g., from create_plan tool)
            if (result && result.action === 'open_in_editor') {
              const filePath = result.plan_file_path as string | undefined;
              if (filePath && typeof filePath === 'string') {
                // Convert absolute path to editor format
                const editorPath = convertAbsolutePathToEditorPath(filePath);

                if (editorPath) {
                  // File is under a project folder - open it using normal flow
                  void editorStore.openFile(editorPath).catch((error) => {
                    console.error('Error opening plan file:', error);
                    $q.notify({
                      type: 'negative',
                      message: `Failed to open plan file: ${filePath}`,
                      position: 'top',
                      timeout: 3000,
                    });
                  });
                } else {
                  // File is outside project folders (e.g., .xeditor directory)
                  // Read it directly and create a tab
                  void openFileByAbsolutePath(filePath).catch((error) => {
                    console.error('Error opening plan file:', error);
                    $q.notify({
                      type: 'negative',
                      message: `Failed to open plan file: ${filePath}`,
                      caption: error instanceof Error ? error.message : 'Unknown error',
                      position: 'top',
                      timeout: 5000,
                    });
                  });
                }
              }
            }
            break;
          }

          case 'file_change': {
            // Handle file change event for diff preview
            const fileChangeData = data as {
              path: string;
              changeType: 'created' | 'modified' | 'deleted';
              beforeContent?: string;
              afterContent?: string;
              toolCallId: string;
            };
            const fileChangeEvent: Extract<TraceEvent, { type: 'file_change' }> = {
              type: 'file_change',
              id: generateTraceId(),
              timestamp: Date.now(),
              toolCallId: fileChangeData.toolCallId,
              path: fileChangeData.path,
              changeType: fileChangeData.changeType,
              ...(fileChangeData.beforeContent !== undefined && {
                beforeContent: fileChangeData.beforeContent,
              }),
              ...(fileChangeData.afterContent !== undefined && {
                afterContent: fileChangeData.afterContent,
              }),
            };
            pendingTurn.value.traceEvents.push(fileChangeEvent);
            break;
          }

          case 'sub_agent_start': {
            // Handle sub-agent start event
            const subAgentStartData = data as {
              id: string;
              parentId?: string;
              agentName: string;
              purpose: string;
              input?: Record<string, unknown>;
            };
            const subAgentStartEvent: Extract<TraceEvent, { type: 'sub_agent_start' }> = {
              type: 'sub_agent_start',
              id: subAgentStartData.id,
              timestamp: Date.now(),
              agentName: subAgentStartData.agentName,
              purpose: subAgentStartData.purpose,
              // Conditionally add optional properties
              ...(subAgentStartData.parentId !== undefined && {
                parentId: subAgentStartData.parentId,
              }),
              ...(subAgentStartData.input !== undefined && { input: subAgentStartData.input }),
            };
            pendingTurn.value.traceEvents.push(subAgentStartEvent);
            pendingTurn.value.currentActivity = `Sub-agent researching: ${subAgentStartData.purpose}`;
            break;
          }

          case 'sub_agent_end': {
            // Handle sub-agent end event
            const subAgentEndData = data as {
              id: string;
              parentId?: string;
              agentStartId: string;
              result?: unknown;
              error?: string;
            };
            const subAgentEndEvent: Extract<TraceEvent, { type: 'sub_agent_end' }> = {
              type: 'sub_agent_end',
              id: subAgentEndData.id,
              timestamp: Date.now(),
              agentStartId: subAgentEndData.agentStartId,
              // Conditionally add optional properties
              ...(subAgentEndData.parentId !== undefined && { parentId: subAgentEndData.parentId }),
              ...(subAgentEndData.result !== undefined && { result: subAgentEndData.result }),
              ...(subAgentEndData.error !== undefined && { error: subAgentEndData.error }),
            };
            pendingTurn.value.traceEvents.push(subAgentEndEvent);
            pendingTurn.value.currentActivity = undefined;
            break;
          }

          case 'context_compression': {
            const compressionData = data as {
              id: string;
              updates: Array<{ tcId: string; summary: string }>;
            };
            const compressionEvent: Extract<TraceEvent, { type: 'context_compression' }> = {
              type: 'context_compression',
              id: compressionData.id,
              timestamp: Date.now(),
              updates: compressionData.updates,
            };
            pendingTurn.value.traceEvents.push(compressionEvent);
            break;
          }

          case 'turn_complete': {
            // Set isLoading to false to re-enable input
            isLoading.value = false;
            // Reload session to get updated turn, then clear pendingTurn after reload completes
            // This prevents duplicate rendering where both pendingTurn and saved turn are visible
            chatStore
              .loadSession(chatStore.currentSession!.id)
              .then(() => {
                // Clear pendingTurn after session reload completes to avoid duplicates
                pendingTurn.value = null;
              })
              .catch((error) => {
                console.error('Failed to reload session after turn complete:', error);
                // Still clear pendingTurn even if reload fails
                pendingTurn.value = null;
              });
            break;
          }

          case 'error': {
            // Show error as system message
            const errorData = data as { message: string };
            pendingTurn.value.error = errorData.message;
            break;
          }
        }
      });

      // Scrolling is handled automatically by ChatMessages component
      // when pendingTurn changes or assistantMessage updates
    } catch (error) {
      console.error('Error sending message:', error);
      const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';

      if (pendingTurn.value) {
        pendingTurn.value.error = errorMessage;
      }
    } finally {
      // Ensure cleanup (may already be done in turn_complete handler)
      isLoading.value = false;
      pendingTurn.value = null;
    }
  }

  // Watch userInput for @ mention detection
  watch(
    () => userInput.value,
    () => {
      mention.updateMentionState(userInput.value);
    },
  );

  /**
   * Submit answers to a pending question and send as user message
   */
  async function submitQuestionAnswers(answers: Record<string, string[]>) {
    const currentPendingQuestion = pendingQuestion.value;
    if (!currentPendingQuestion) return;

    const currentChatId = chatStore.currentSession?.id;
    if (!currentChatId) return;

    // Format answers as a structured response with full question prompts
    const responses: Array<{ question: string; answers: string[] }> = [];
    for (const q of currentPendingQuestion.questions) {
      const answer = answers[q.id] || [];
      // Map option IDs to labels for readability
      const labels = answer
        .map((optId) => {
          const opt = q.options.find((o) => o.id === optId);
          return opt?.label || optId;
        })
        .filter(Boolean);

      if (labels.length > 0) {
        responses.push({
          question: q.prompt,
          answers: labels,
        });
      }
    }

    // Create a structured JSON message that can be detected and rendered nicely
    const structuredResponse = {
      type: 'question_response',
      title: currentPendingQuestion.title || 'Questions',
      responses,
    };
    const answerText = `<!--QUESTION_RESPONSE-->${JSON.stringify(structuredResponse)}`;

    // Clear pending question for this chat
    delete pendingQuestionsByChatId.value[currentChatId];

    // Set as user input and send
    userInput.value = answerText;
    await sendMessage();
  }

  /**
   * Skip the pending question without answering
   */
  function skipQuestion() {
    const currentPendingQuestion = pendingQuestion.value;
    if (!currentPendingQuestion) return;

    const currentChatId = chatStore.currentSession?.id;
    if (!currentChatId) return;

    // Create structured skipped question payload
    const skippedData: QuestionSkippedData = {
      type: 'question_skipped',
      ...(currentPendingQuestion.title && { title: currentPendingQuestion.title }),
      questions: currentPendingQuestion.questions,
      user_message: 'Proceed without answering.',
    };
    const skipText = `${SKIP_MARKER}${JSON.stringify(skippedData)}`;

    // Clear pending question for this chat
    delete pendingQuestionsByChatId.value[currentChatId];

    // Set as user input and send
    userInput.value = skipText;
    void sendMessage();
  }

  /**
   * Confirm and approve a pending command.
   * Sends a structured message that the server will use to execute the command
   * directly and feed the result to the LLM (no extra LLM call for the tool).
   */
  async function confirmCommand(id: string) {
    const currentPendingCommand = pendingCommand.value;
    if (!currentPendingCommand || currentPendingCommand.id !== id) return;

    const currentChatId = chatStore.currentSession?.id;
    if (!currentChatId) return;

    // Clear pending command for this chat
    delete pendingCommandsByChatId.value[currentChatId];

    // Send structured approval message that server will parse
    // Format: <!--COMMAND_APPROVED-->{"id":"hash","command":"..."}
    const approvalData = {
      id: currentPendingCommand.id,
      command: currentPendingCommand.command,
    };
    userInput.value = `${COMMAND_APPROVED_MARKER}${JSON.stringify(approvalData)}`;
    await sendMessage();
  }

  /**
   * Skip the pending command without executing.
   * Sends a structured message indicating the command was skipped.
   */
  function skipCommand() {
    const currentPendingCommand = pendingCommand.value;
    if (!currentPendingCommand) return;

    const currentChatId = chatStore.currentSession?.id;
    if (!currentChatId) return;

    // Clear pending command for this chat
    delete pendingCommandsByChatId.value[currentChatId];

    // Send structured skip message
    const skipData = {
      id: currentPendingCommand.id,
      command: currentPendingCommand.command,
    };
    userInput.value = `${COMMAND_SKIPPED_MARKER}${JSON.stringify(skipData)}`;
    void sendMessage();
  }

  return {
    userInput,
    isLoading,
    pendingTurn,
    pendingQuestion,
    pendingCommand,
    hasProject,
    mention,
    onChatKeydown,
    onChatInput,
    sendMessage,
    stopGeneration,
    submitQuestionAnswers,
    skipQuestion,
    confirmCommand,
    skipCommand,
  };
}
