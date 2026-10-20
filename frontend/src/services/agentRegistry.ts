/**
 * AryaOS V1 — Stage 10: Provider-Neutral Agent Registry
 *
 * Manages specialized logical workers, their allowed capabilities, concurrency limits,
 * autonomy levels, trust ratings, and live workloads.
 *
 * Logical workers remain strictly separated from execution backends (providers).
 */

import { AgentProfile } from '../types/agentCoordination';
import { ProviderCapabilityType } from '../types/intelligenceProvider';

export const INITIAL_AGENT_PROFILES: AgentProfile[] = [
  {
    agentId: 'agent-researcher',
    name: 'Archival Researcher',
    role: 'RESEARCHER',
    capabilities: ['RESEARCH', 'SUMMARIZATION', 'STRUCTURED_EXTRACTION'],
    allowedCapabilities: ['RESEARCH', 'SUMMARIZATION', 'STRUCTURED_EXTRACTION', 'CLASSIFICATION'],
    contextRequirements: ['archive', 'vitrines'],
    costClass: 'ECONOMY',
    latencyClass: 'FAST',
    concurrencyLimit: 3,
    currentWorkload: 0,
    trustLevel: 'VERIFIED',
    autonomyLevel: 'HIGH',
    status: 'IDLE',
    memoryScopes: ['archive', 'vitrines', 'docs'],
    historicalSuccessCount: 142,
    historicalFailureCount: 2,
  },
  {
    agentId: 'agent-analyst',
    name: 'Contextual Analyst',
    role: 'ANALYST',
    capabilities: ['REASONING', 'CLASSIFICATION', 'SUMMARIZATION'],
    allowedCapabilities: ['REASONING', 'CLASSIFICATION', 'SUMMARIZATION'],
    contextRequirements: ['archive', 'telemetry'],
    costClass: 'STANDARD',
    latencyClass: 'BALANCED',
    concurrencyLimit: 2,
    currentWorkload: 0,
    trustLevel: 'VERIFIED',
    autonomyLevel: 'HIGH',
    status: 'IDLE',
    memoryScopes: ['archive', 'analytics', 'telemetry'],
    historicalSuccessCount: 98,
    historicalFailureCount: 1,
  },
  {
    agentId: 'agent-planner',
    name: 'Strategic Planner',
    role: 'PLANNER',
    capabilities: ['REASONING', 'STRUCTURED_EXTRACTION'],
    allowedCapabilities: ['REASONING', 'STRUCTURED_EXTRACTION', 'CLASSIFICATION'],
    contextRequirements: ['plans', 'goals'],
    costClass: 'STANDARD',
    latencyClass: 'BALANCED',
    concurrencyLimit: 2,
    currentWorkload: 0,
    trustLevel: 'AUTONOMOUS',
    autonomyLevel: 'HIGH',
    status: 'IDLE',
    memoryScopes: ['plans', 'goals', 'dag'],
    historicalSuccessCount: 210,
    historicalFailureCount: 3,
  },
  {
    agentId: 'agent-writer',
    name: 'Narrative Synthesizer',
    role: 'WRITER',
    capabilities: ['SUMMARIZATION', 'REASONING'],
    allowedCapabilities: ['SUMMARIZATION', 'REASONING'],
    contextRequirements: ['scripts', 'prompts'],
    costClass: 'ECONOMY',
    latencyClass: 'FAST',
    concurrencyLimit: 2,
    currentWorkload: 0,
    trustLevel: 'VERIFIED',
    autonomyLevel: 'HIGH',
    status: 'IDLE',
    memoryScopes: ['scripts', 'prompts', 'narratives'],
    historicalSuccessCount: 88,
    historicalFailureCount: 0,
  },
  {
    agentId: 'agent-coder',
    name: 'Pipeline Engineer',
    role: 'CODER',
    capabilities: ['CODE_GENERATION', 'REASONING', 'STRUCTURED_EXTRACTION'],
    allowedCapabilities: ['CODE_GENERATION', 'REASONING', 'STRUCTURED_EXTRACTION'],
    contextRequirements: ['code', 'workflows'],
    costClass: 'STANDARD',
    latencyClass: 'BALANCED',
    concurrencyLimit: 2,
    currentWorkload: 0,
    trustLevel: 'VERIFIED',
    autonomyLevel: 'MEDIUM',
    status: 'IDLE',
    memoryScopes: ['code', 'workflows'],
    historicalSuccessCount: 75,
    historicalFailureCount: 4,
  },
  {
    agentId: 'agent-vision',
    name: 'Visual Inspector',
    role: 'VISION_ANALYST',
    capabilities: ['VISION', 'IMAGE_GENERATION'],
    allowedCapabilities: ['VISION', 'IMAGE_GENERATION'],
    contextRequirements: ['visual', 'keyframes'],
    costClass: 'PREMIUM',
    latencyClass: 'DEEP',
    concurrencyLimit: 1,
    currentWorkload: 0,
    trustLevel: 'VERIFIED',
    autonomyLevel: 'MEDIUM',
    status: 'IDLE',
    memoryScopes: ['visual', 'keyframes', 'vitrines'],
    historicalSuccessCount: 64,
    historicalFailureCount: 2,
  },
  {
    agentId: 'agent-video-director',
    name: 'Spatial Video Director',
    role: 'VIDEO_DIRECTOR',
    capabilities: ['VIDEO_GENERATION', 'VISION'],
    allowedCapabilities: ['VIDEO_GENERATION', 'VISION'],
    contextRequirements: ['video', 'shots'],
    costClass: 'PREMIUM',
    latencyClass: 'DEEP',
    concurrencyLimit: 1,
    currentWorkload: 0,
    trustLevel: 'VERIFIED',
    autonomyLevel: 'LOW', // Consequential action requires human approval
    status: 'IDLE',
    memoryScopes: ['video', 'shots', 'timeline'],
    historicalSuccessCount: 45,
    historicalFailureCount: 1,
  },
  {
    agentId: 'agent-quality',
    name: 'Auditing Gatekeeper',
    role: 'QUALITY_REVIEWER',
    capabilities: ['REASONING', 'CLASSIFICATION'],
    allowedCapabilities: ['REASONING', 'CLASSIFICATION', 'STRUCTURED_EXTRACTION'],
    contextRequirements: ['qa', 'reviews'],
    costClass: 'STANDARD',
    latencyClass: 'BALANCED',
    concurrencyLimit: 2,
    currentWorkload: 0,
    trustLevel: 'AUTONOMOUS',
    autonomyLevel: 'HIGH',
    status: 'IDLE',
    memoryScopes: ['qa', 'reviews', 'rubrics'],
    historicalSuccessCount: 130,
    historicalFailureCount: 0,
  },
  {
    agentId: 'agent-metadata',
    name: 'Ontology Indexer',
    role: 'METADATA_AGENT',
    capabilities: ['CLASSIFICATION', 'STRUCTURED_EXTRACTION', 'EMBEDDING'],
    allowedCapabilities: ['CLASSIFICATION', 'STRUCTURED_EXTRACTION', 'EMBEDDING'],
    contextRequirements: ['tags', 'entities'],
    costClass: 'ECONOMY',
    latencyClass: 'FAST',
    concurrencyLimit: 4,
    currentWorkload: 0,
    trustLevel: 'AUTONOMOUS',
    autonomyLevel: 'HIGH',
    status: 'IDLE',
    memoryScopes: ['tags', 'entities', 'metadata'],
    historicalSuccessCount: 312,
    historicalFailureCount: 1,
  },
  {
    agentId: 'agent-publisher',
    name: 'Distribution Gateway',
    role: 'PUBLISHING_AGENT',
    capabilities: ['REASONING', 'SUMMARIZATION'],
    allowedCapabilities: ['REASONING', 'SUMMARIZATION'],
    contextRequirements: ['channels', 'exports'],
    costClass: 'ECONOMY',
    latencyClass: 'FAST',
    concurrencyLimit: 1,
    currentWorkload: 0,
    trustLevel: 'VERIFIED',
    autonomyLevel: 'LOW', // External side effects require human approval
    status: 'IDLE',
    memoryScopes: ['channels', 'social', 'exports'],
    historicalSuccessCount: 52,
    historicalFailureCount: 0,
  },
];

class AgentRegistry {
  private agents: Map<string, AgentProfile> = new Map();

  constructor() {
    this.resetRegistry();
  }

  public resetRegistry(): void {
    this.agents.clear();
    INITIAL_AGENT_PROFILES.forEach((profile) => {
      this.agents.set(profile.agentId, { ...profile });
    });
  }

  public getAgent(agentId: string): AgentProfile | undefined {
    return this.agents.get(agentId);
  }

  public getAllAgents(): AgentProfile[] {
    return Array.from(this.agents.values());
  }

  public getAgentsForCapability(capability: ProviderCapabilityType): AgentProfile[] {
    return this.getAllAgents().filter(
      (agent) =>
        agent.allowedCapabilities.includes(capability) &&
        agent.status !== 'UNAVAILABLE'
    );
  }

  public registerAgent(profile: AgentProfile): void {
    this.agents.set(profile.agentId, { ...profile });
  }

  public updateAgentWorkload(agentId: string, delta: number): void {
    const agent = this.agents.get(agentId);
    if (!agent) return;
    agent.currentWorkload = Math.max(0, agent.currentWorkload + delta);
    if (agent.currentWorkload >= agent.concurrencyLimit) {
      agent.status = 'RUNNING';
    } else if (agent.currentWorkload > 0) {
      agent.status = 'ASSIGNED';
    } else {
      agent.status = 'IDLE';
    }
  }

  public updateAgentStatus(agentId: string, status: AgentProfile['status']): void {
    const agent = this.agents.get(agentId);
    if (!agent) return;
    agent.status = status;
  }

  public recordAgentTelemetry(agentId: string, success: boolean): void {
    const agent = this.agents.get(agentId);
    if (!agent) return;
    if (success) {
      agent.historicalSuccessCount += 1;
    } else {
      agent.historicalFailureCount += 1;
    }
  }
}

export const agentRegistry = new AgentRegistry();
