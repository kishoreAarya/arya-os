/**
 * AryaOS V1 — Stage 04: Semantic Memory Archive Service
 *
 * Implements deterministic bidirectional mapping between Three.js spatial vitrines
 * and semantic memory records. Decouples spatial presentation from domain intelligence.
 */

import {
  MemoryRecord,
  MemoryFilterType,
  MemoryRelationship,
  TimelineContext,
  VitrineMemoryMapping,
} from '../types/memory';

/**
 * Deterministic mapping of 24 Stage 03 Vitrines to Memory Records.
 * Never random. Never recreated per render.
 */
export const VITRINE_MAPPING_REGISTRY: VitrineMemoryMapping[] = [
  // Dais Flank Crystals (01-08)
  { vitrineId: 'Dais_Flank_Crystal_01', memoryId: 'MEM-0001', archetype: 'mountain', sector: 'DAIS_FLANK' },
  { vitrineId: 'Dais_Flank_Crystal_02', memoryId: 'MEM-0002', archetype: 'neural', sector: 'DAIS_FLANK' },
  { vitrineId: 'Dais_Flank_Crystal_03', memoryId: 'MEM-0003', archetype: 'city', sector: 'DAIS_FLANK' },
  { vitrineId: 'Dais_Flank_Crystal_04', memoryId: 'MEM-0004', archetype: 'matrix', sector: 'DAIS_FLANK' },
  { vitrineId: 'Dais_Flank_Crystal_05', memoryId: 'MEM-0005', archetype: 'chrono', sector: 'DAIS_FLANK' },
  { vitrineId: 'Dais_Flank_Crystal_06', memoryId: 'MEM-0006', archetype: 'mountain', sector: 'DAIS_FLANK' },
  { vitrineId: 'Dais_Flank_Crystal_07', memoryId: 'MEM-0007', archetype: 'neural', sector: 'DAIS_FLANK' },
  { vitrineId: 'Dais_Flank_Crystal_08', memoryId: 'MEM-0008', archetype: 'city', sector: 'DAIS_FLANK' },

  // Pathway Memory Crystals (01-12)
  { vitrineId: 'Pathway_Memory_Crystal_01', memoryId: 'MEM-0009', archetype: 'mountain', sector: 'PATHWAY' },
  { vitrineId: 'Pathway_Memory_Crystal_02', memoryId: 'MEM-0010', archetype: 'neural', sector: 'PATHWAY' },
  { vitrineId: 'Pathway_Memory_Crystal_03', memoryId: 'MEM-0011', archetype: 'city', sector: 'PATHWAY' },
  { vitrineId: 'Pathway_Memory_Crystal_04', memoryId: 'MEM-0012', archetype: 'matrix', sector: 'PATHWAY' },
  { vitrineId: 'Pathway_Memory_Crystal_05', memoryId: 'MEM-0013', archetype: 'chrono', sector: 'PATHWAY' },
  { vitrineId: 'Pathway_Memory_Crystal_06', memoryId: 'MEM-0014', archetype: 'mountain', sector: 'PATHWAY' },
  { vitrineId: 'Pathway_Memory_Crystal_07', memoryId: 'MEM-0015', archetype: 'neural', sector: 'PATHWAY' },
  { vitrineId: 'Pathway_Memory_Crystal_08', memoryId: 'MEM-0016', archetype: 'city', sector: 'PATHWAY' },
  { vitrineId: 'Pathway_Memory_Crystal_09', memoryId: 'MEM-0017', archetype: 'matrix', sector: 'PATHWAY' },
  { vitrineId: 'Pathway_Memory_Crystal_10', memoryId: 'MEM-0018', archetype: 'chrono', sector: 'PATHWAY' },
  { vitrineId: 'Pathway_Memory_Crystal_11', memoryId: 'MEM-0019', archetype: 'mountain', sector: 'PATHWAY' },
  { vitrineId: 'Pathway_Memory_Crystal_12', memoryId: 'MEM-0020', archetype: 'neural', sector: 'PATHWAY' },

  // Rotunda Inner Crystals (01-04)
  { vitrineId: 'Rotunda_Inner_Crystal_01', memoryId: 'MEM-0021', archetype: 'city', sector: 'ROTUNDA_INNER' },
  { vitrineId: 'Rotunda_Inner_Crystal_02', memoryId: 'MEM-0022', archetype: 'matrix', sector: 'ROTUNDA_INNER' },
  { vitrineId: 'Rotunda_Inner_Crystal_03', memoryId: 'MEM-0023', archetype: 'chrono', sector: 'ROTUNDA_INNER' },
  { vitrineId: 'Rotunda_Inner_Crystal_04', memoryId: 'MEM-0024', archetype: 'mountain', sector: 'ROTUNDA_INNER' },
];

/**
 * 24 Seed Memory Records mapped to the Stage 03 Memory Archive vitrines.
 * Uses real AryaOS architectural history, decisions, events, and workflows.
 */
export const STAGE04_MEMORY_DATABASE: MemoryRecord[] = [
  {
    id: 'MEM-0001',
    title: 'Foundational Architecture Charter: Project Horizon',
    summary: 'The inaugural architectural specification establishing the multi-agent operating system, memory archives, and decoupled spatial-semantic abstraction layer.',
    type: 'project',
    createdAt: '2026-08-15T09:00:00Z',
    updatedAt: '2026-08-16T14:30:00Z',
    importance: 1.0,
    tags: ['charter', 'architecture', 'horizon', 'core'],
    entities: [
      { id: 'ent-01', name: 'Lead Architect', type: 'user', role: 'System Designer' },
      { id: 'ent-02', name: 'Arya Core', type: 'system', role: 'Kernel Host' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0002', relationshipType: 'predecessor', label: 'Establishes Lineage For', strength: 0.95 },
      { targetMemoryId: 'MEM-0023', relationshipType: 'anchored_in', label: 'Sparks Epoch Zero', strength: 1.0 },
      { targetMemoryId: 'MEM-0004', relationshipType: 'references', label: 'Defines Consensus Rules', strength: 0.8 },
    ],
    source: { type: 'system', identifier: 'INIT_BOOTSTRAP' },
    spatialObjectId: 'Dais_Flank_Crystal_01',
    metadata: { revision: '1.0.0-PROD', clearance: 'CORE_KERNEL' },
  },
  {
    id: 'MEM-0002',
    title: 'Cognitive Lineage & Autonomous Routing Matrix',
    summary: 'Decision matrix arbitrating how creative requests are decomposed across Research, Script, Video, and Publishing agent pools with zero circular dependencies.',
    type: 'decision',
    createdAt: '2026-08-22T11:15:00Z',
    updatedAt: '2026-08-23T18:00:00Z',
    importance: 0.92,
    tags: ['routing', 'lineage', 'orchestrator', 'decision'],
    entities: [
      { id: 'ent-03', name: 'Orchestrator Agent', type: 'agent', role: 'Workflow Dispatcher' },
      { id: 'ent-04', name: 'Script Agent', type: 'agent', role: 'Story Synthesizer' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0001', relationshipType: 'derived_from', label: 'Derived From Charter', strength: 0.95 },
      { targetMemoryId: 'MEM-0012', relationshipType: 'collaborates_with', label: 'Coordinates Audio Routing', strength: 0.85 },
      { targetMemoryId: 'MEM-0020', relationshipType: 'references', label: 'Arbitration Baseline', strength: 0.75 },
    ],
    source: { type: 'agent', identifier: 'ORCHESTRATOR_DISPATCH' },
    spatialObjectId: 'Dais_Flank_Crystal_02',
    metadata: { routingGraphDepth: 6, maxHops: 12 },
  },
  {
    id: 'MEM-0003',
    title: 'Metropolitan World Synthesis Protocol',
    summary: 'A procedural pipeline for assembling multi-block speculative urban scenes with deterministic lighting cues and high-frequency architectural occlusion.',
    type: 'workflow',
    createdAt: '2026-08-28T16:45:00Z',
    importance: 0.84,
    tags: ['world-building', 'procedural', 'urban', 'graphics'],
    entities: [
      { id: 'ent-05', name: 'Spatial Engine', type: 'system', role: '3D Geometry Synthesizer' },
      { id: 'ent-06', name: 'Director Persona', type: 'user', role: 'Creative Director' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0011', relationshipType: 'predecessor', label: 'Feeds Urban Expansion', strength: 0.9 },
      { targetMemoryId: 'MEM-0016', relationshipType: 'references', label: 'Calibrates Against Colonnade', strength: 0.7 },
    ],
    source: { type: 'pipeline', identifier: 'SPATIAL_GEN_V1' },
    spatialObjectId: 'Dais_Flank_Crystal_03',
    metadata: { lodStages: 4, instancedMeshesCount: 140 },
  },
  {
    id: 'MEM-0004',
    title: 'Multi-Agent Consensus & Arbitration Graph',
    summary: 'Formal knowledge repository documenting conflict resolution heuristics when Video, Sound, and Story agents disagree on shot duration and emotional cadence.',
    type: 'knowledge',
    createdAt: '2026-09-02T13:20:00Z',
    importance: 0.88,
    tags: ['arbitration', 'consensus', 'heuristics', 'knowledge'],
    entities: [
      { id: 'ent-07', name: 'Arbitration Gateway', type: 'agent', role: 'Conflict Resolver' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0002', relationshipType: 'related_to', label: 'Pairs With Routing Matrix', strength: 0.88 },
      { targetMemoryId: 'MEM-0020', relationshipType: 'predecessor', label: 'Underpins Continuity Decisions', strength: 0.92 },
    ],
    source: { type: 'system', identifier: 'ARBITRATION_SUBSYSTEM' },
    spatialObjectId: 'Dais_Flank_Crystal_04',
    metadata: { resolutionLatencyMs: 14, consensusThreshold: 0.75 },
  },
  {
    id: 'MEM-0005',
    title: 'Temporal Frame Consistency & First-Frame Anchoring',
    summary: 'The critical continuity breakthrough solving video frame drift across cuts by mathematically locking first-frame and last-frame latent conditioning vectors.',
    type: 'artifact',
    createdAt: '2026-09-05T20:10:00Z',
    updatedAt: '2026-09-06T08:00:00Z',
    importance: 0.98,
    tags: ['continuity', 'keyframes', 'temporal', 'first-frame'],
    entities: [
      { id: 'ent-08', name: 'Continuity Engine', type: 'system', role: 'Temporal Lock Sentinel' },
      { id: 'ent-09', name: 'Video Agent', type: 'agent', role: 'Diffusion Generator' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0010', relationshipType: 'references', label: 'Provides Keyframe Anchors', strength: 0.95 },
      { targetMemoryId: 'MEM-0013', relationshipType: 'predecessor', label: 'Enables Cut Sequencing', strength: 0.9 },
    ],
    source: { type: 'pipeline', identifier: 'CONTINUITY_VALIDATOR_V3' },
    spatialObjectId: 'Dais_Flank_Crystal_05',
    metadata: { ssimThreshold: 0.85, latentDriftTolerance: 0.04 },
  },
  {
    id: 'MEM-0006',
    title: 'Deep Obsidian Topology & Elevation Shaders',
    summary: 'Physical material specification defining dark obsidian architectural facets: DARK != PURE BLACK, with calibrated metalness (0.80) and roughness (0.26).',
    type: 'knowledge',
    createdAt: '2026-09-08T15:30:00Z',
    importance: 0.78,
    tags: ['materials', 'pbr', 'obsidian', 'shaders'],
    entities: [
      { id: 'ent-05', name: 'Spatial Engine', type: 'system', role: 'Material Compiler' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0019', relationshipType: 'related_to', label: 'Shares Specular Curve', strength: 0.85 },
      { targetMemoryId: 'MEM-0016', relationshipType: 'references', label: 'Grounds Surface Reflection', strength: 0.8 },
    ],
    source: { type: 'pipeline', identifier: 'PBR_MAT_PIPELINE' },
    spatialObjectId: 'Dais_Flank_Crystal_06',
    metadata: { ior: 1.62, clearcoatRoughness: 0.13 },
  },
  {
    id: 'MEM-0007',
    title: 'Director Persona Alignment & Creative Intent',
    summary: 'High-level creative dialogue exploring moody atmospheric cinematic aesthetics, pacing, and intentional lighting hierarchies for the Memory Archive.',
    type: 'conversation',
    createdAt: '2026-09-11T19:00:00Z',
    importance: 0.82,
    tags: ['dialogue', 'creative', 'intent', 'director'],
    entities: [
      { id: 'ent-06', name: 'Director Persona', type: 'user', role: 'Creative Director' },
      { id: 'ent-01', name: 'Lead Architect', type: 'user', role: 'System Designer' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0015', relationshipType: 'predecessor', label: 'Establishes Storyboard Tone', strength: 0.9 },
      { targetMemoryId: 'MEM-0021', relationshipType: 'references', label: 'Shapes Core Aesthetics', strength: 0.85 },
    ],
    source: { type: 'user', identifier: 'CREATIVE_SESSION_0911' },
    spatialObjectId: 'Dais_Flank_Crystal_07',
    metadata: { mood: 'atmospheric-cinematic', tone: 'contemplative' },
  },
  {
    id: 'MEM-0008',
    title: 'Spatial Colonnade Acoustic Simulation',
    summary: 'Acoustic impulse response profiling measuring reverberation within the monumental colonnade ring, generating spatial sound dampening curves.',
    type: 'event',
    createdAt: '2026-09-14T10:00:00Z',
    importance: 0.72,
    tags: ['acoustics', 'sound', 'colonnade', 'spatial-audio'],
    entities: [
      { id: 'ent-10', name: 'Sound Resolver', type: 'agent', role: 'Acoustic Synthesizer' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0012', relationshipType: 'derived_from', label: 'Utilizes Acoustic Tokens', strength: 0.85 },
    ],
    source: { type: 'agent', identifier: 'SOUND_RESOLVER_DAEMON' },
    spatialObjectId: 'Dais_Flank_Crystal_08',
    metadata: { rt60Seconds: 2.4, earlyReflectionsGain: -4.5 },
  },

  // Pathway Memory Crystals (09-20)
  {
    id: 'MEM-0009',
    title: 'Volumetric Terrain Generation Pipeline',
    summary: 'Automated heightfield synthesis computing eroded mountain silhouettes and distant geological monoliths for background horizons.',
    type: 'workflow',
    createdAt: '2026-09-16T14:15:00Z',
    importance: 0.75,
    tags: ['terrain', 'volumetric', 'heightfield', 'environment'],
    entities: [
      { id: 'ent-05', name: 'Spatial Engine', type: 'system', role: 'Terrain Builder' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0014', relationshipType: 'collaborates_with', label: 'Embeds Fog In Haze', strength: 0.8 },
      { targetMemoryId: 'MEM-0024', relationshipType: 'predecessor', label: 'Extends Into Orbital Realm', strength: 0.7 },
    ],
    source: { type: 'pipeline', identifier: 'TERRAIN_SYNTH_JOB_482' },
    spatialObjectId: 'Pathway_Memory_Crystal_01',
    metadata: { resolution: '2048x2048', erosionPasses: 16 },
  },
  {
    id: 'MEM-0010',
    title: 'Keyframe Interpolation & Motion Smoothing',
    summary: 'Algorithmic smoothing layer eliminating camera shudder and micro-jitter during cinematic tracking shots between monument anchors.',
    type: 'workflow',
    createdAt: '2026-09-18T17:30:00Z',
    importance: 0.86,
    tags: ['keyframes', 'motion', 'interpolation', 'spline'],
    entities: [
      { id: 'ent-09', name: 'Video Agent', type: 'agent', role: 'Motion Controller' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0005', relationshipType: 'derived_from', label: 'Driven By First-Frame Anchors', strength: 0.95 },
      { targetMemoryId: 'MEM-0018', relationshipType: 'collaborates_with', label: 'Interpolates Awakening Arc', strength: 0.85 },
    ],
    source: { type: 'agent', identifier: 'VIDEO_INTERPOLATOR_RUN' },
    spatialObjectId: 'Pathway_Memory_Crystal_02',
    metadata: { splineType: 'CatmullRom', velocityDamping: 0.92 },
  },
  {
    id: 'MEM-0011',
    title: 'Procedural Urban Expansion Graph',
    summary: 'Graph grammar producing self-similar multi-tiered megalith structures with hierarchical cybernetic conduits and illuminated viaducts.',
    type: 'artifact',
    createdAt: '2026-09-20T12:00:00Z',
    importance: 0.8,
    tags: ['city', 'megalith', 'graph-grammar', 'viaducts'],
    entities: [
      { id: 'ent-05', name: 'Spatial Engine', type: 'system', role: 'Urban Synthesizer' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0003', relationshipType: 'derived_from', label: 'Grown From Urban Protocol', strength: 0.9 },
    ],
    source: { type: 'pipeline', identifier: 'GRAPH_SYNTH_PIPELINE' },
    spatialObjectId: 'Pathway_Memory_Crystal_03',
    metadata: { nodeCount: 1420, edgeCount: 3840 },
  },
  {
    id: 'MEM-0012',
    title: 'Sound Resonance & Acoustic Token Resolution',
    summary: 'Decision establishing deterministic hash mapping between visual scene intensity, lighting color temperature, and orchestral drone frequencies.',
    type: 'decision',
    createdAt: '2026-09-21T09:45:00Z',
    importance: 0.84,
    tags: ['audio', 'resonance', 'tokens', 'decision'],
    entities: [
      { id: 'ent-10', name: 'Sound Resolver', type: 'agent', role: 'Acoustic Synthesizer' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0008', relationshipType: 'predecessor', label: 'Provides Acoustic Baselines', strength: 0.85 },
      { targetMemoryId: 'MEM-0002', relationshipType: 'references', label: 'Aligns With Routing Priority', strength: 0.7 },
    ],
    source: { type: 'agent', identifier: 'SOUND_RESOLVER_DAEMON' },
    spatialObjectId: 'Pathway_Memory_Crystal_04',
    metadata: { droneBaseHz: 55.0, harmonicSeriesLength: 8 },
  },
  {
    id: 'MEM-0013',
    title: 'Episodic Cut Sequencing & Transition Pacing',
    summary: 'Workflow sequence defining automated editorial rhythm: 3-second establishing holds, 1.2-second focus shifts, and sub-second cut cadences.',
    type: 'workflow',
    createdAt: '2026-09-22T16:10:00Z',
    importance: 0.88,
    tags: ['editing', 'sequencing', 'cuts', 'pacing'],
    entities: [
      { id: 'ent-03', name: 'Orchestrator Agent', type: 'agent', role: 'Editor' },
      { id: 'ent-06', name: 'Director Persona', type: 'user', role: 'Reviewer' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0005', relationshipType: 'derived_from', label: 'Requires Continuity Lock', strength: 0.9 },
      { targetMemoryId: 'MEM-0018', relationshipType: 'collaborates_with', label: 'Times Awakening Reveal', strength: 0.85 },
    ],
    source: { type: 'pipeline', identifier: 'OPENMONTAGE_DISPATCH' },
    spatialObjectId: 'Pathway_Memory_Crystal_05',
    metadata: { totalShots: 8, estimatedDurationSec: 24.5 },
  },
  {
    id: 'MEM-0014',
    title: 'Atmospheric Density Field Mapping',
    summary: 'Theoretical model defining multi-altitude atmospheric scatter, Rayleigh cool blue sky falloff, and low-altitude warm sodium haze gradients.',
    type: 'knowledge',
    createdAt: '2026-09-23T11:00:00Z',
    importance: 0.82,
    tags: ['atmosphere', 'fog', 'rayleigh', 'optics'],
    entities: [
      { id: 'ent-01', name: 'Lead Architect', type: 'user', role: 'Optics Researcher' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0016', relationshipType: 'collaborates_with', label: 'Calibrates Fog Color', strength: 0.88 },
      { targetMemoryId: 'MEM-0009', relationshipType: 'references', label: 'Envelopes Mountain Peaks', strength: 0.8 },
    ],
    source: { type: 'system', identifier: 'OPTICS_RESEARCH_PAPER' },
    spatialObjectId: 'Pathway_Memory_Crystal_06',
    metadata: { fogNear: 19.0, fogFar: 182.0, hexHaze: '#52657a' },
  },
  {
    id: 'MEM-0015',
    title: 'Script-to-Storyboard Synthesis Session',
    summary: 'Multi-turn planning exchange generating the shot graph for the Memory Archive establishing reveal, camera heights, and character silhouette placement.',
    type: 'conversation',
    createdAt: '2026-09-24T18:20:00Z',
    importance: 0.85,
    tags: ['script', 'storyboard', 'planning', 'conversation'],
    entities: [
      { id: 'ent-04', name: 'Script Agent', type: 'agent', role: 'Writer' },
      { id: 'ent-06', name: 'Director Persona', type: 'user', role: 'Creative Director' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0007', relationshipType: 'derived_from', label: 'Continues Director Alignment', strength: 0.9 },
      { targetMemoryId: 'MEM-0018', relationshipType: 'predecessor', label: 'Drafts Transition Arc', strength: 0.85 },
    ],
    source: { type: 'user', identifier: 'STORYBOARD_WORKSHOP_44' },
    spatialObjectId: 'Pathway_Memory_Crystal_07',
    metadata: { shotCount: 12, dialogueLines: 0, visualOnly: true },
  },
  {
    id: 'MEM-0016',
    title: 'Architectural Lighting Calibration Pass',
    summary: 'Decision establishing Phase 2.8/2.9 lighting defaults: sun at 0.68W (#647b94), core at 12.0W (#ffa232), and restrained ambient fill at 0.44W (#22262e).',
    type: 'decision',
    createdAt: '2026-09-25T14:40:00Z',
    importance: 0.94,
    tags: ['lighting', 'calibration', 'eevee', 'threejs', 'decision'],
    entities: [
      { id: 'ent-01', name: 'Lead Architect', type: 'user', role: 'Lookdev Lead' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0014', relationshipType: 'derived_from', label: 'Implements Density Field', strength: 0.88 },
      { targetMemoryId: 'MEM-0021', relationshipType: 'references', label: 'Balances Reactor Glare', strength: 0.92 },
    ],
    source: { type: 'pipeline', identifier: 'LOOKDEV_PHASE29_VALIDATION' },
    spatialObjectId: 'Pathway_Memory_Crystal_08',
    metadata: { heroMae: 41.24, heroPsnr: 13.13, heroSsim: 0.1252 },
  },
  {
    id: 'MEM-0017',
    title: 'Cross-Modal Embeddings for Prompt Alignment',
    summary: 'Knowledge base on mathematical vector alignment between text prompts, visual depth maps, and synthetic acoustic features for coherent asset generation.',
    type: 'knowledge',
    createdAt: '2026-09-26T16:00:00Z',
    importance: 0.84,
    tags: ['embeddings', 'multimodal', 'alignment', 'vectors'],
    entities: [
      { id: 'ent-02', name: 'Arya Core', type: 'system', role: 'Inference Engine' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0004', relationshipType: 'references', label: 'Informs Conflict Resolution', strength: 0.8 },
      { targetMemoryId: 'MEM-0012', relationshipType: 'collaborates_with', label: 'Coordinates Audio Tokens', strength: 0.75 },
    ],
    source: { type: 'system', identifier: 'EMBEDDING_CLUSTER_PRIMARY' },
    spatialObjectId: 'Pathway_Memory_Crystal_09',
    metadata: { dimension: 1536, cosineSimilarityMin: 0.82 },
  },
  {
    id: 'MEM-0018',
    title: 'Cinematic Awakening Transition Timeline',
    summary: 'Event milestone marking the successful runtime transition between Stage 01 Awakening (Hero Monolith), Stage 02 Core, and Stage 03 Memory Archive.',
    type: 'event',
    createdAt: '2026-09-27T21:15:00Z',
    importance: 0.96,
    tags: ['awakening', 'transition', 'milestone', 'stage-switch'],
    entities: [
      { id: 'ent-02', name: 'Arya Core', type: 'system', role: 'Runtime State Manager' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0010', relationshipType: 'derived_from', label: 'Smooths Transition Camera', strength: 0.85 },
      { targetMemoryId: 'MEM-0013', relationshipType: 'references', label: 'Adheres To Pacing Rules', strength: 0.8 },
      { targetMemoryId: 'MEM-0021', relationshipType: 'successor', label: 'Arrives At Astrolabe Core', strength: 0.95 },
    ],
    source: { type: 'system', identifier: 'RUNTIME_LIFECYCLE_STAGE_TRANSITION' },
    spatialObjectId: 'Pathway_Memory_Crystal_10',
    metadata: { transitionDurationMs: 1400, easing: 'easeInOutCubic' },
  },
  {
    id: 'MEM-0019',
    title: 'Monolith Specular Occlusion Model',
    summary: 'Mathematical artifact defining specular ambient occlusion terms on titanium and gunmetal surfaces under multi-directional grazing illumination.',
    type: 'artifact',
    createdAt: '2026-09-28T13:10:00Z',
    importance: 0.76,
    tags: ['specular', 'ao', 'occlusion', 'titanium'],
    entities: [
      { id: 'ent-05', name: 'Spatial Engine', type: 'system', role: 'Shader Compiler' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0006', relationshipType: 'derived_from', label: 'Extends Obsidian PBR', strength: 0.85 },
    ],
    source: { type: 'pipeline', identifier: 'SHADER_OPT_V2' },
    spatialObjectId: 'Pathway_Memory_Crystal_11',
    metadata: { bentNormalApproximation: true, aoStrength: 0.85 },
  },
  {
    id: 'MEM-0020',
    title: 'Agent Arbitration on Visual Continuity',
    summary: 'Decision resolving a critical tension between Video Agent prompt compliance and Continuity Sentinel frame-anchor strictness during Shot 04 generation.',
    type: 'decision',
    createdAt: '2026-09-29T10:30:00Z',
    importance: 0.9,
    tags: ['arbitration', 'conflict', 'shot-04', 'decision'],
    entities: [
      { id: 'ent-07', name: 'Arbitration Gateway', type: 'agent', role: 'Mediator' },
      { id: 'ent-09', name: 'Video Agent', type: 'agent', role: 'Appellant' },
      { id: 'ent-08', name: 'Continuity Engine', type: 'system', role: 'Respondent' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0004', relationshipType: 'derived_from', label: 'Executes Consensus Graph', strength: 0.92 },
      { targetMemoryId: 'MEM-0005', relationshipType: 'references', label: 'Relaxes Frame Anchor by 3%', strength: 0.88 },
    ],
    source: { type: 'agent', identifier: 'ARBITRATION_RUN_8992' },
    spatialObjectId: 'Pathway_Memory_Crystal_12',
    metadata: { resolutionType: 'TOLERANCE_ADJUSTMENT', passRateAfter: 1.0 },
  },

  // Rotunda Inner Crystals (21-24)
  {
    id: 'MEM-0021',
    title: 'The Astrolabe Core Ignition Event',
    summary: 'The climactic event milestone in the Memory Archive: central 380W kinetic reactor core activation, initiating rotating gimbal rings and radiant photon wash.',
    type: 'event',
    createdAt: '2026-09-30T18:00:00Z',
    importance: 1.0,
    tags: ['astrolabe', 'ignition', 'reactor', 'core', 'kinetic'],
    entities: [
      { id: 'ent-02', name: 'Arya Core', type: 'system', role: 'Power Host' },
      { id: 'ent-05', name: 'Spatial Engine', type: 'system', role: 'Kinetic Animator' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0022', relationshipType: 'collaborates_with', label: 'Powers Memory Shards', strength: 0.98 },
      { targetMemoryId: 'MEM-0023', relationshipType: 'derived_from', label: 'Emanates From Epoch Zero', strength: 1.0 },
      { targetMemoryId: 'MEM-0016', relationshipType: 'references', label: 'Calibrated Lighting Target', strength: 0.92 },
    ],
    source: { type: 'system', identifier: 'ASTROLABE_SUBSYSTEM_BOOT' },
    spatialObjectId: 'Rotunda_Inner_Crystal_01',
    metadata: { reactorWatts: 380, gimbalAxes: 3, pulseFrequencyHz: 0.33 },
  },
  {
    id: 'MEM-0022',
    title: 'Primary Memory Shard Lattice Topology',
    summary: 'Architectural artifact documenting the concentric floating obsidian slabs and suspended data voxels encircling the Astrolabe core.',
    type: 'artifact',
    createdAt: '2026-09-30T19:30:00Z',
    importance: 0.94,
    tags: ['shards', 'lattice', 'topology', 'voxels'],
    entities: [
      { id: 'ent-05', name: 'Spatial Engine', type: 'system', role: 'Geometry Host' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0021', relationshipType: 'anchored_in', label: 'Orbits Astrolabe Core', strength: 0.98 },
      { targetMemoryId: 'MEM-0024', relationshipType: 'collaborates_with', label: 'Connects To Outer Sanctuary', strength: 0.8 },
    ],
    source: { type: 'pipeline', identifier: 'SHARD_LATTICE_COMPILER' },
    spatialObjectId: 'Rotunda_Inner_Crystal_02',
    metadata: { totalShards: 24, floatHarmonics: [1.5, 0.45] },
  },
  {
    id: 'MEM-0023',
    title: 'AryaOS Epoch Zero: Initial Awakening',
    summary: 'The foundational project inception record. The creation of the autonomous creative intelligence substrate, uniting generative agents and spatial architectures.',
    type: 'project',
    createdAt: '2026-08-01T00:00:00Z',
    importance: 1.0,
    tags: ['epoch-zero', 'genesis', 'aryaos', 'awakening'],
    entities: [
      { id: 'ent-01', name: 'Lead Architect', type: 'user', role: 'Creator' },
      { id: 'ent-02', name: 'Arya Core', type: 'system', role: 'Awakened Substrate' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0001', relationshipType: 'predecessor', label: 'Leads To Architecture Charter', strength: 1.0 },
      { targetMemoryId: 'MEM-0021', relationshipType: 'predecessor', label: 'Destined For Astrolabe Core', strength: 0.95 },
    ],
    source: { type: 'system', identifier: 'GENESIS_EPOCH_0' },
    spatialObjectId: 'Rotunda_Inner_Crystal_03',
    metadata: { version: '0.0.1-GENESIS', immutableRoot: true },
  },
  {
    id: 'MEM-0024',
    title: 'Deep Horizon Space & Orbital Sanctuary',
    summary: 'Philosophical and technical knowledge charter on the boundary between physical workspace interfaces and limitless spatial memory expanses.',
    type: 'knowledge',
    createdAt: '2026-10-01T12:00:00Z',
    importance: 0.88,
    tags: ['sanctuary', 'philosophy', 'horizon', 'knowledge'],
    entities: [
      { id: 'ent-06', name: 'Director Persona', type: 'user', role: 'Philosopher' },
      { id: 'ent-02', name: 'Arya Core', type: 'system', role: 'Living Repository' },
    ],
    relationships: [
      { targetMemoryId: 'MEM-0022', relationshipType: 'references', label: 'Frames Shard Lattice', strength: 0.8 },
      { targetMemoryId: 'MEM-0009', relationshipType: 'references', label: 'Encircles Mountain Horizon', strength: 0.75 },
    ],
    source: { type: 'system', identifier: 'SANCTUARY_CHARTER' },
    spatialObjectId: 'Rotunda_Inner_Crystal_04',
    metadata: { horizonDistanceM: 500, atmosphericLayers: 5 },
  },
];

/**
 * Fast lookup indexes
 */
const MEMORY_BY_ID_MAP = new Map<string, MemoryRecord>();
const MEMORY_BY_VITRINE_MAP = new Map<string, MemoryRecord>();
const VITRINE_BY_MEMORY_MAP = new Map<string, string>();

STAGE04_MEMORY_DATABASE.forEach((rec) => {
  MEMORY_BY_ID_MAP.set(rec.id, rec);
  if (rec.spatialObjectId) {
    MEMORY_BY_VITRINE_MAP.set(rec.spatialObjectId, rec);
    VITRINE_BY_MEMORY_MAP.set(rec.id, rec.spatialObjectId);
  }
});

/**
 * Memory Archive Service API
 */
export const memoryArchiveService = {
  /**
   * Retrieves all 24 deterministic memory records.
   */
  getAllMemories(): MemoryRecord[] {
    return STAGE04_MEMORY_DATABASE;
  },

  /**
   * Retrieves a single memory by ID.
   */
  getMemoryById(id: string): MemoryRecord | undefined {
    return MEMORY_BY_ID_MAP.get(id);
  },

  /**
   * Bidirectional lookup: Vitrine ID -> Memory Record.
   */
  getMemoryByVitrineId(vitrineId: string): MemoryRecord | undefined {
    return MEMORY_BY_VITRINE_MAP.get(vitrineId);
  },

  /**
   * Bidirectional lookup: Memory ID -> Vitrine ID.
   */
  getVitrineIdByMemoryId(memoryId: string): string | undefined {
    return VITRINE_BY_MEMORY_MAP.get(memoryId);
  },

  /**
   * Retrieves all vitrine-memory mappings.
   */
  getMappings(): VitrineMemoryMapping[] {
    return VITRINE_MAPPING_REGISTRY;
  },

  /**
   * Filters memories by category pill.
   */
  filterMemories(filter: MemoryFilterType, dataset = STAGE04_MEMORY_DATABASE): MemoryRecord[] {
    if (filter === 'ALL') return dataset;
    const typeKey = filter.toLowerCase().replace(/s$/, '') as any;
    return dataset.filter((m) => {
      if (filter === 'PROJECTS') return m.type === 'project';
      if (filter === 'DECISIONS') return m.type === 'decision';
      if (filter === 'CONVERSATIONS') return m.type === 'conversation';
      if (filter === 'WORKFLOWS') return m.type === 'workflow';
      if (filter === 'ARTIFACTS') return m.type === 'artifact';
      if (filter === 'EVENTS') return m.type === 'event';
      if (filter === 'KNOWLEDGE') return m.type === 'knowledge';
      return m.type === typeKey;
    });
  },

  /**
   * Full text search across title, summary, tags, entity names, and type.
   */
  searchMemories(query: string, filter: MemoryFilterType = 'ALL'): MemoryRecord[] {
    const q = query.trim().toLowerCase();
    const sourceList = this.filterMemories(filter);
    if (!q) return sourceList;

    return sourceList.filter((m) => {
      if (m.title.toLowerCase().includes(q)) return true;
      if (m.summary.toLowerCase().includes(q)) return true;
      if (m.id.toLowerCase().includes(q)) return true;
      if (m.type.toLowerCase().includes(q)) return true;
      if (m.tags.some((t) => t.toLowerCase().includes(q))) return true;
      if (m.entities.some((e) => e.name.toLowerCase().includes(q) || (e.role && e.role.toLowerCase().includes(q)))) {
        return true;
      }
      return false;
    });
  },

  /**
   * Resolves outgoing and incoming relationships for a memory.
   */
  getRelatedMemories(memoryId: string): Array<{ memory: MemoryRecord; relationship: MemoryRelationship }> {
    const origin = MEMORY_BY_ID_MAP.get(memoryId);
    if (!origin) return [];

    const results: Array<{ memory: MemoryRecord; relationship: MemoryRelationship }> = [];
    const seenIds = new Set<string>();

    // 1. Direct outgoing relationships
    origin.relationships.forEach((rel) => {
      const target = MEMORY_BY_ID_MAP.get(rel.targetMemoryId);
      if (target && !seenIds.has(target.id)) {
        seenIds.add(target.id);
        results.push({ memory: target, relationship: rel });
      }
    });

    // 2. Incoming relationships from other memories pointing to this memory
    STAGE04_MEMORY_DATABASE.forEach((other) => {
      if (other.id !== memoryId && !seenIds.has(other.id)) {
        const incomingRel = other.relationships.find((r) => r.targetMemoryId === memoryId);
        if (incomingRel) {
          seenIds.add(other.id);
          results.push({
            memory: other,
            relationship: {
              targetMemoryId: other.id,
              relationshipType: incomingRel.relationshipType === 'predecessor'
                ? 'successor'
                : incomingRel.relationshipType === 'derived_from'
                ? 'references'
                : incomingRel.relationshipType,
              label: `Referenced by ${other.title}`,
              strength: incomingRel.strength,
            },
          });
        }
      }
    });

    return results;
  },

  /**
   * Constructs temporal timeline context (predecessor, current, successor in sequence).
   */
  getTimelineContext(memoryId: string): TimelineContext | null {
    const current = MEMORY_BY_ID_MAP.get(memoryId);
    if (!current) return null;

    if (!current.createdAt) {
      return {
        current,
        chronologicalIndex: -1,
        totalInSequence: 0,
        hasTimestamp: false,
      };
    }

    // Sort all timestamped memories chronologically
    const datedMemories = STAGE04_MEMORY_DATABASE
      .filter((m) => Boolean(m.createdAt))
      .sort((a, b) => new Date(a.createdAt!).getTime() - new Date(b.createdAt!).getTime());

    const idx = datedMemories.findIndex((m) => m.id === memoryId);
    if (idx === -1) {
      return {
        current,
        chronologicalIndex: -1,
        totalInSequence: datedMemories.length,
        hasTimestamp: false,
      };
    }

    return {
      current,
      predecessor: idx > 0 ? datedMemories[idx - 1] : undefined,
      successor: idx < datedMemories.length - 1 ? datedMemories[idx + 1] : undefined,
      chronologicalIndex: idx + 1,
      totalInSequence: datedMemories.length,
      hasTimestamp: true,
    };
  },
};
