// Core Type Definitions

// Built-in modes (for reference/documentation)
export type BuiltInMode = 'plan' | 'ask' | 'agent' | 'debug';
// Mode can be built-in or custom string
export type Mode = string;

export type ProjectId = string;
export type ProjectFolderId = string;

export type FolderPermissionState = PermissionState | 'unknown';

export interface ProjectFolderRecord {
  id: ProjectFolderId;
  name: string;
  /** Full filesystem path from local companion (e.g., /home/user/project) */
  systemPath: string;
  addedAt: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Embedding Model Types
// ─────────────────────────────────────────────────────────────────────────────

export type EmbeddingModelId =
  | 'microsoft/codebert-base'
  | 'sentence-transformers/all-MiniLM-L6-v2'
  | 'BAAI/bge-small-en'
  | 'thenlper/gte-small';

export interface ProjectSettings {
  embeddingModelId?: EmbeddingModelId;
}

export interface ProjectRecord {
  id: ProjectId;
  name: string;
  createdAt: number;
  updatedAt: number;
  folders: ProjectFolderRecord[];
  settings?: ProjectSettings;
}

export interface ProjectSummary {
  id: ProjectId;
  name: string;
  folderCount: number;
  updatedAt: number;
}

export interface FolderRuntimeState {
  folderId: ProjectFolderId;
  permission: FolderPermissionState;
  connected: boolean;
  lastCheckedAt: number;
  error?: string | undefined;
}

// ─────────────────────────────────────────────────────────────────────────────
// Model Provider & Connection Types
// ─────────────────────────────────────────────────────────────────────────────

export type ModelProviderId =
  | 'openai'
  | 'anthropic'
  | 'ollama'
  | 'lmstudio'
  | 'vllm'
  | 'sglang'
  | 'openai_compatible'
  | 'kimi'
  | 'local_companion';

export type LocalCompanionRunner = 'vllm';

export type ModelAuthType = 'none' | 'bearer' | 'header' | 'query_param' | 'multi_header';

export interface ModelAuthNone {
  type: 'none';
}

export interface ModelAuthBearer {
  type: 'bearer';
  apiKey?: string; // Optional: stored by local companion in ~/.xeditor/models.json
}

export interface ModelAuthHeader {
  type: 'header';
  headerName: string;
  value?: string; // Optional: stored by local companion in ~/.xeditor/models.json
}

export interface ModelAuthQueryParam {
  type: 'query_param';
  paramName: string;
  value?: string; // Optional: stored by local companion in ~/.xeditor/models.json
}

export interface ModelAuthMultiHeader {
  type: 'multi_header';
  headers: Array<{ name: string; value?: string }>; // Optional values stored by local companion in ~/.xeditor/models.json
}

export type ModelAuth =
  | ModelAuthNone
  | ModelAuthBearer
  | ModelAuthHeader
  | ModelAuthQueryParam
  | ModelAuthMultiHeader;

// ─────────────────────────────────────────────────────────────────────────────
// Provider Preset Types
// ─────────────────────────────────────────────────────────────────────────────

export interface ProviderPresetAuthDefault {
  helpText?: string;
  headerName?: string;
  headers?: Array<{ name: string; required?: boolean; helpText?: string }>;
}

export interface ProviderPresetValidation {
  header?: {
    requiredHeaderName?: string;
    errorMessage?: string;
  };
}

/**
 * Provider definition returned from server.
 * Used to populate the Provider dropdown in ModelEditorDialog.
 */
export interface ProviderDefinition {
  id: ModelProviderId;
  label: string;
}

/**
 * Schema field for provider-specific parameters.
 * Used to dynamically render UI controls in ModelEditorDialog.
 */
export interface ProviderParameterSchemaField {
  /** Unique identifier (supports dot notation for nesting, e.g., "reasoning.enabled") */
  id: string;
  /** Display label */
  label: string;
  /** Field type */
  type: 'boolean' | 'select' | 'number' | 'string';
  /** Options for select type */
  options?: Array<{ value: string | number | boolean; label: string }>;
  /** Default value */
  default?: unknown;
  /** Optional help text */
  helpText?: string;
  /** Conditional visibility based on another field's value */
  dependsOn?: {
    field: string;
    value: unknown;
  };
}

export interface ProviderPreset {
  id?: string;
  provider: ModelProviderId;
  family: string;
  supportedAuthTypes: ModelAuthType[];
  defaultAuthType: ModelAuthType;
  authDefaults: Partial<Record<ModelAuthType, ProviderPresetAuthDefault>>;
  recommendedHeaders?: Record<string, string>;
  validation?: ProviderPresetValidation;
  /** Schema for provider-specific parameters (rendered as UI controls) */
  parameterSchema?: ProviderParameterSchemaField[];
  /** Default values for provider parameters */
  parameterDefaults?: Record<string, unknown>;
}

export interface ProviderPresetsResponse {
  success: boolean;
  /** List of available providers (for dropdown) */
  providers?: ProviderDefinition[];
  /** Specific preset matching the filter (provider/baseUrl/family) */
  preset?: ProviderPreset;
  /** All available presets */
  presets?: ProviderPreset[];
}

export interface ModelConnection {
  baseUrl?: string; // e.g. http://localhost:11434 for Ollama
  path?: string; // API path override, e.g. /v1/chat/completions
  headers?: Record<string, string>; // Non-secret default headers
  auth: ModelAuth;
}

export interface ModelCapabilities {
  jsonMode: boolean;
  functionCalling: boolean;
  streaming?: boolean;
  vision?: boolean;
}

export interface ModelConfig {
  id: string; // 'gpt-4-turbo'
  provider: ModelProviderId;
  family: string; // 'gpt', 'claude', 'llama', etc.
  name: string; // 'GPT-4 Turbo'
  version?: string; // '4-turbo'
  contextWindow: number;
  capabilities: ModelCapabilities;
  connection: ModelConnection;
  /**
   * Local Companion-only settings.
   * When provider === 'local_companion', `runner` controls whether inference is handled
   * by routing to a local vLLM server.
   */
  localCompanion?: {
    runner: LocalCompanionRunner;
  };
  /**
   * Tracking flags for reset functionality.
   * - isSystemDefault: Model exists in bundled defaults.json
   * - isUserOverride: User modified a system default model
   * - isCustom: User-created model with new ID
   */
  isSystemDefault?: boolean;
  isUserOverride?: boolean;
  isCustom?: boolean;
  /**
   * Provider-specific parameters configured via UI controls.
   * These are structured settings that providers know how to interpret.
   * Example: { "reasoning": { "enabled": true, "effort": "medium" } }
   */
  providerParams?: Record<string, unknown>;
  /**
   * Extra payload parameters to include in API requests.
   * These are merged into the request body sent to the model API.
   * Use this as an escape hatch for advanced settings not covered by providerParams.
   * Example: { "reasoning": { "effort": "medium" } }
   */
  extraPayload?: Record<string, unknown>;
}

export interface PromptTemplate {
  id: string;
  mode: Mode;
  target: {
    family?: string | undefined;
    version?: string | undefined;
  };
  filePath?: string | undefined;
  systemPrompt: string; // Template string (can use {{variables}})
  parameters: {
    temperature: number;
    maxTokens?: number | undefined;
  };
  outputSchema?: Record<string, unknown> | undefined; // JSON Schema-like object
  toolDefinitions?:
    | Array<{
        name: string;
        description: string;
        parameters: Record<string, unknown>;
      }>
    | undefined;
  /**
   * Tracking flags for reset functionality.
   * - isSystemDefault: Template from built-in prompt set
   * - isUserOverride: User modified a system template
   * - isCustom: User-created template with new ID
   * - sourceSetId: Which prompt set this template came from
   */
  isSystemDefault?: boolean;
  isUserOverride?: boolean;
  isCustom?: boolean;
  sourceSetId?: string;
}

/**
 * Resolved prompt ready for use with LLM
 * Contains the final system prompt and parameters
 */
export interface ResolvedPrompt {
  systemPrompt: string;
  temperature: number;
  maxTokens?: number;
  toolDefinitions?: PromptTemplate['toolDefinitions'];
}

/**
 * Parsed response from LLM (extracted by Python parser)
 */
export interface ParsedResponse {
  thinking?: string;
  toolCall?: {
    tool: string;
    args: Record<string, unknown>;
  };
  finalText: string;
}

export interface ContextItem {
  id: string;
  type: 'file' | 'snippet' | 'symbol';
  content: string;
  relevanceScore: number;
  metadata: {
    filePath: string;
    lineStart?: number;
    lineEnd?: number;
    symbolName?: string;
  };
}

export interface FileNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  children?: FileNode[];
  content?: string; // Only for files
}

export interface EditorTab {
  id: string;
  filePath: string;
  fileName: string;
  content: string;
  originalContent: string;
  isDirty: boolean;
  language?: string;
  viewMode: 'code' | 'preview'; // View mode: code editor or preview
  // Diff mode: when set, this tab shows a diff view
  diffMode?: {
    beforeContent: string;
    afterContent: string;
    changeType: 'created' | 'modified' | 'deleted';
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// AI Config Types (persisted globally in IndexedDB)
// ─────────────────────────────────────────────────────────────────────────────

export type ToolId = string;
export type McpServerId = string;

export interface ModeTooling {
  toolIds: ToolId[];
  mcpServerIds: McpServerId[];
}

// Tool-specific settings (stored in tools.json alongside tool allowlist)
export interface ReadFileSettings {
  thresholdChars?: number; // Start chunking above this (default: 50000)
  maxChars?: number; // Hard cap on total chars (default: 100000)
  maxLines?: number; // Hard cap on total lines (default: 2000)
  headLines?: number; // Lines from head (default: 100)
  middleLines?: number; // Lines from middle (default: 50)
  tailLines?: number; // Lines from tail (default: 100)
}

export interface ToolSettings {
  read_file?: ReadFileSettings;
  // Add other tool settings as needed
}

export interface ToolDefinition {
  id: ToolId;
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

export interface McpServerDefinition {
  id: McpServerId;
  name: string;
  description: string;
  endpoint: string;
}

export interface PromptSetMetadata {
  id: string; // "user/set-name" or "default"
  name: string;
  author: string;
  version: string;
  description: string;
  modes: string[]; // Available modes in this set
  family: string; // Primary model family
  families: string[]; // Supported model families (for backward compatibility / multiple families)
  modelVersion?: string | undefined; // Optional: specific model version this set is optimized for (e.g., "5.2", "4.5-opus")
  isBuiltIn: boolean;
  createdAt?: number;
  updatedAt?: number;
}

export interface ModeStructure {
  hasPrompt: boolean;
  hasParser: boolean;
  tools: string[];
}

export interface VersionStructure {
  [mode: string]: ModeStructure;
}

export interface FamilyStructure {
  [version: string]: VersionStructure;
}

export interface PromptSetStructure {
  metadata: PromptSetMetadata;
  families: {
    [family: string]: FamilyStructure;
  };
}

export interface AiConfigRecord {
  id: 'global'; // Single record key
  activeMode: Mode;
  activeModelId: string;
  activeSetId: string; // Active prompt set ID
  debugEnabled?: boolean; // Debug mode toggle for chat inspector
  modeTooling: Record<Mode, ModeTooling>;
  updatedAt: number;
  // Legacy fields (for migration compatibility - will be ignored)
  models?: ModelConfig[];
  promptTemplates?: PromptTemplate[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Chat History Types
// ─────────────────────────────────────────────────────────────────────────────

export type ChatSessionId = string;
export type ChatTurnId = string;
export type TraceEventId = string;

export interface TokenUsage {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  // Optional detailed breakdown (provider-specific)
  cachedTokens?: number;
  reasoningTokens?: number;
}

export interface UsageBreakdown {
  main: TokenUsage;
  subAgents: TokenUsage;
  total: TokenUsage;
  llmCallCount?: number;
}

export interface ContextUsage {
  usedPromptTokens: number;
  contextWindow: number;
  fillPercent: number;
}

export interface ModelSnapshot {
  id: string;
  provider: string;
  family: string;
  version?: string;
  contextWindow: number;
}

export interface SessionTokenStats {
  totalTokens: number;
  promptTokens: number;
  completionTokens: number;
  byFamily: Record<string, TokenUsage>;
}

export interface TraceEventToolCall {
  type: 'tool_call';
  id: TraceEventId;
  timestamp: number;
  parentId?: TraceEventId;
  toolName: string;
  arguments: Record<string, unknown>;
  output?: string; // Accumulated streaming output from tool_chunk events
}

export interface TraceEventToolChunk {
  type: 'tool_chunk';
  id: TraceEventId;
  timestamp: number;
  parentId?: TraceEventId;
  toolCallId: TraceEventId;
  content: string;
}

export interface TraceEventToolResult {
  type: 'tool_result';
  id: TraceEventId;
  timestamp: number;
  parentId?: TraceEventId;
  toolCallId: TraceEventId;
  result: unknown;
  error?: string | undefined;
}

export interface TraceEventContextRetrieval {
  type: 'context_retrieval';
  id: TraceEventId;
  timestamp: number;
  parentId?: TraceEventId;
  contextType: 'current_file' | 'selected_code' | 'ranked' | 'limited' | 'symbol' | 'search';
  items: ContextItem[];
}

export interface TraceEventThinking {
  type: 'thinking';
  id: TraceEventId;
  timestamp: number;
  parentId?: TraceEventId;
  content: string;
  includeInContext: false; // Thinking is never sent to LLM
}

export interface TraceEventSubAgentStart {
  type: 'sub_agent_start';
  id: TraceEventId;
  timestamp: number;
  parentId?: TraceEventId;
  agentName: string;
  purpose: string;
  input?: Record<string, unknown>;
}

export interface TraceEventSubAgentEnd {
  type: 'sub_agent_end';
  id: TraceEventId;
  timestamp: number;
  parentId?: TraceEventId;
  agentStartId: TraceEventId;
  result?: unknown;
  error?: string | undefined;
  // Token usage from sub-agent (for aggregation in parent)
  usage?: TokenUsage;
  modelSnapshot?: ModelSnapshot;
}

export interface TraceEventFileChange {
  type: 'file_change';
  id: TraceEventId;
  timestamp: number;
  toolCallId: TraceEventId;
  path: string;
  changeType: 'created' | 'modified' | 'deleted';
  beforeContent?: string;
  afterContent?: string;
}

export interface TraceEventAssistantMessage {
  type: 'assistant_message';
  id: TraceEventId;
  timestamp: number;
  parentId?: TraceEventId;
  content: string;
  step?: number; // Optional step number for multi-step agent turns
}

export interface TraceEventContextCompression {
  type: 'context_compression';
  id: TraceEventId;
  timestamp: number;
  updates: Array<{ tcId: string; summary: string }>;
}

export type TraceEvent =
  | TraceEventToolCall
  | TraceEventToolChunk
  | TraceEventToolResult
  | TraceEventContextRetrieval
  | TraceEventThinking
  | TraceEventSubAgentStart
  | TraceEventSubAgentEnd
  | TraceEventFileChange
  | TraceEventAssistantMessage
  | TraceEventContextCompression;

// ─────────────────────────────────────────────────────────────────────────────
// Agent Activity Types (for live progress display during agent execution)
// ─────────────────────────────────────────────────────────────────────────────

export type AgentStepType = 'llm_start' | 'tool_start' | 'tool_result' | 'llm_response';
export type AgentStepStatus = 'running' | 'complete' | 'error';

export interface AgentStep {
  id: string;
  type: AgentStepType;
  timestamp: number;
  toolName?: string | undefined;
  toolArgs?: Record<string, unknown> | undefined;
  result?: unknown;
  error?: string | undefined;
  content?: string | undefined; // For intermediate LLM responses
  status: AgentStepStatus;
}

export interface ChatMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface Artifact {
  path: string; // Absolute file path
  type: string; // "plan", "file", etc.
  name: string; // Display name
  toolCallId?: string; // Associated tool call ID
}

export interface ChatTurn {
  id: ChatTurnId;
  timestamp: number;
  mode: Mode;
  modelId: string;
  userMessage: string;
  assistantMessage: string;
  systemPrompt: string; // Resolved system prompt used
  contextItems: ContextItem[]; // Snapshot of context items used
  usage?: TokenUsage;
  traceEvents: TraceEvent[]; // Ordered trace events for this turn
  error?: string | undefined; // Error message if the turn failed (displayed as system message, not included in context)

  // New Agentic Fields
  contextMessages?: ChatMessage[]; // The clean, optimized transcript sent to the LLM
  workingSet?: string[]; // List of file paths the agent has explicitly "read" and is keeping in focus
  artifacts?: Artifact[]; // Artifacts (plans, files) created by tools in this turn

  // Token usage breakdown and context tracking
  usageBreakdown?: UsageBreakdown; // Detailed breakdown: main vs sub-agents
  contextUsage?: ContextUsage; // Context window usage info
  modelSnapshot?: ModelSnapshot; // Snapshot of model used for stable per-family tracking
}

export interface ChatSession {
  id: ChatSessionId;
  projectId: ProjectId;
  title: string;
  createdAt: number;
  updatedAt: number;
  turns: ChatTurn[];
}

export interface ChatSessionSummary {
  id: ChatSessionId;
  projectId: ProjectId;
  title: string;
  createdAt: number;
  updatedAt: number;
  turnCount: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Debug Bundle Types (for chat turn inspection)
// ─────────────────────────────────────────────────────────────────────────────

export interface DebugBundleModel {
  id: string;
  provider: string;
  family: string;
  version?: string;
  runner?: string;
}

export interface DebugBundlePrompt {
  setId: string;
  mode: string;
  family: string;
  version?: string;
  templateId: string;
  promptFilePath?: string;
}

export interface DebugBundleParser {
  parserId?: string;
  parserFilePath?: string;
}

export interface DebugBundleLLMMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface DebugBundleLLMCall {
  step: number;
  timestamp: number;
  messages: DebugBundleLLMMessage[];
}

export interface DebugBundleToolCall {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  result?: unknown;
  error?: string;
  resultTruncated?: boolean;
  includeInContext?: boolean;
}

export interface DebugBundleTraceEvent {
  type: string;
  id?: string;
  timestamp?: number;
  [key: string]: unknown;
}

export interface DebugBundle {
  turnId: string;
  timestamp: number;
  model: DebugBundleModel;
  prompt: DebugBundlePrompt;
  parser: DebugBundleParser;
  resolvedSystemPrompt: string;
  llmMessages: DebugBundleLLMMessage[];
  llmCalls?: DebugBundleLLMCall[];
  traceEvents: DebugBundleTraceEvent[];
  toolCalls: DebugBundleToolCall[];
}
