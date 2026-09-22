import React, { useEffect, useState, useRef } from 'react';
import {
  checkBackendHealth,
  fetchCapabilities,
  fetchHistory,
  getStoredApiKey,
  pollJobStatus,
  submitGeneration,
} from './api/creatorApi';
import {
  CapabilitiesManifest,
  GenerationJob,
  GenerationType,
  HealthStatus,
  HistoryItem,
} from './types/creator';
import { Header } from './components/Header';
import { AuthModal } from './components/AuthModal';
import { GenerationTypeSelector } from './components/GenerationTypeSelector';
import { PromptSection } from './components/PromptSection';
import { ReferenceUpload } from './components/ReferenceUpload';
import { ConfigPanel } from './components/ConfigPanel';
import { StartEndFrameControls } from './components/StartEndFrameControls';
import { GenerateButton } from './components/GenerateButton';
import { JobStatusCard } from './components/JobStatusCard';
import { AssetPreview } from './components/AssetPreview';
import { HistoryPanel } from './components/HistoryPanel';

export const App: React.FC = () => {
  // Global backend state
  const [health, setHealth] = useState<HealthStatus>({ status: 'connecting' });
  const [manifest, setManifest] = useState<CapabilitiesManifest | null>(null);
  const [isLoadingManifest, setIsLoadingManifest] = useState(true);
  const [hasApiKey, setHasApiKey] = useState(Boolean(getStoredApiKey()));
  const [isAuthModalOpen, setIsAuthModalOpen] = useState(false);

  // Form State
  const [generationType, setGenerationType] = useState<GenerationType>('image');
  const [prompt, setPrompt] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [selectedAspectRatio, setSelectedAspectRatio] = useState('16:9');
  const [selectedResolution, setSelectedResolution] = useState('1024x1024');
  const [selectedDuration, setSelectedDuration] = useState(5);
  const [referenceImageUrl, setReferenceImageUrl] = useState<string | undefined>();
  const [startFrameUrl, setStartFrameUrl] = useState<string | undefined>();
  const [endFrameUrl, setEndFrameUrl] = useState<string | undefined>();

  // Execution & Job State
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [currentJob, setCurrentJob] = useState<GenerationJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);

  // History State
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [isRefreshingHistory, setIsRefreshingHistory] = useState(false);

  const pollIntervalRef = useRef<any>(null);

  // 1. Initial Load: Health, Capabilities, and Persistent History
  useEffect(() => {
    loadHealth();
    loadCapabilities();
    loadHistory();

    const healthInterval = setInterval(loadHealth, 15000);
    return () => {
      clearInterval(healthInterval);
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  const loadHealth = async () => {
    const res = await checkBackendHealth();
    setHealth(res);
  };

  const loadCapabilities = async () => {
    setIsLoadingManifest(true);
    try {
      const data = await fetchCapabilities();
      setManifest(data);
      if (data.models[generationType]?.length) {
        setSelectedModel(data.models[generationType][0].id);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load capabilities');
    } finally {
      setIsLoadingManifest(false);
    }
  };

  const loadHistory = async () => {
    try {
      const data = await fetchHistory();
      setHistory(data);
    } catch (err: any) {
      console.warn('History fetch notice:', err.message);
    } finally {
      setIsLoadingHistory(false);
      setIsRefreshingHistory(false);
    }
  };

  const handleRefreshHistory = () => {
    setIsRefreshingHistory(true);
    loadHistory();
  };

  // When generation type changes, re-sync model selection
  const handleTypeChange = (type: GenerationType) => {
    setGenerationType(type);
    setValidationError(null);
    if (manifest?.models?.[type]?.length) {
      const defaultModel = manifest.models[type].find((m) => m.default) || manifest.models[type][0];
      setSelectedModel(defaultModel.id);
    }
  };

  // 2. Active Model Object & Capabilities
  const currentModels = manifest?.models?.[generationType] || [];
  const selectedModelObj = currentModels.find((m) => m.id === selectedModel);

  // 3. Asynchronous Job Polling
  const startPollingJob = (jobId: string) => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);

    pollIntervalRef.current = setInterval(async () => {
      try {
        const updatedJob = await pollJobStatus(jobId);
        setCurrentJob(updatedJob);

        if (updatedJob.status === 'completed' || updatedJob.status === 'failed') {
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
          // Refresh persistent history from backend
          loadHistory();
        }
      } catch (err: any) {
        console.error('Job polling error:', err);
      }
    }, 2000);
  };

  // 4. Job Submission Handler
  const handleGenerate = async () => {
    setError(null);
    setValidationError(null);

    // Validation 1: Prompt
    if (!prompt.trim()) {
      setValidationError('Please enter a prompt describing your desired generation.');
      return;
    }

    // Validation 2: Image-to-Video requires start frame
    if (generationType === 'image_to_video' && !startFrameUrl && !referenceImageUrl) {
      setValidationError('Image → Video generation requires a start frame image.');
      return;
    }

    setIsSubmitting(true);
    try {
      const job = await submitGeneration({
        generation_type: generationType,
        prompt: prompt.trim(),
        model: selectedModel,
        provider: selectedModelObj?.provider,
        aspect_ratio: selectedAspectRatio,
        resolution: selectedResolution,
        duration_seconds: generationType !== 'image' ? selectedDuration : undefined,
        start_frame_url: startFrameUrl || referenceImageUrl,
        end_frame_url: endFrameUrl,
        reference_image_url: referenceImageUrl,
      });

      setCurrentJob(job);
      // Start async polling
      startPollingJob(job.job_id);
    } catch (err: any) {
      setError(err.message || 'Generation submission failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Selecting a history item loads it into the current view
  const handleSelectHistoryItem = (item: HistoryItem) => {
    setCurrentJob({
      job_id: item.job_id,
      workflow_run_id: item.workflow_run_id,
      status: item.status,
      generation_type: item.generation_type,
      prompt: item.prompt,
      model: item.model,
      provider: item.provider,
      aspect_ratio: item.aspect_ratio,
      duration_seconds: item.duration_seconds,
      total_cost_usd: item.total_cost_usd,
      output: {
        asset_url: item.asset_url,
        storage_path: item.asset_url,
        aspect_ratio: item.aspect_ratio,
        duration_seconds: item.duration_seconds,
      },
    });
  };

  return (
    <div className="app-container">
      <Header
        health={health}
        onOpenAuth={() => setIsAuthModalOpen(true)}
        hasApiKey={hasApiKey}
        onRefreshHistory={handleRefreshHistory}
        isRefreshingHistory={isRefreshingHistory}
      />

      <main className="main-layout">
        {/* Left Column: Creator Form Controls */}
        <section aria-label="Creator Controls">
          <div className="creator-card">
            {/* 1. Generation Type Selection */}
            <GenerationTypeSelector
              selectedType={generationType}
              onChange={handleTypeChange}
            />

            {/* 2. Prompt Input */}
            <PromptSection
              prompt={prompt}
              onChange={setPrompt}
              generationType={generationType}
              error={validationError}
            />

            {/* 3. Reference Image Upload (Optional or Required for I2V) */}
            {generationType === 'image' && (
              <ReferenceUpload
                label="Reference Image (Optional)"
                sublabel="Provide a reference image for style or composition guidance"
                imageUrl={referenceImageUrl}
                onImageChange={setReferenceImageUrl}
              />
            )}

            {/* 4. Configuration: Model, Aspect Ratio, Resolution, Duration */}
            <ConfigPanel
              generationType={generationType}
              models={currentModels}
              selectedModel={selectedModel}
              onModelChange={setSelectedModel}
              aspectRatios={manifest?.aspect_ratios || []}
              selectedAspectRatio={selectedAspectRatio}
              onAspectRatioChange={setSelectedAspectRatio}
              resolutions={manifest?.resolutions || []}
              selectedResolution={selectedResolution}
              onResolutionChange={setSelectedResolution}
              durations={manifest?.durations || []}
              selectedDuration={selectedDuration}
              onDurationChange={setSelectedDuration}
            />

            {/* 5. Start Frame & End Frame Controls (respects backend capabilities) */}
            <StartEndFrameControls
              generationType={generationType}
              selectedModelObj={selectedModelObj}
              startFrameUrl={startFrameUrl}
              onStartFrameChange={setStartFrameUrl}
              endFrameUrl={endFrameUrl}
              onEndFrameChange={setEndFrameUrl}
            />

            {/* 6. Generate Action Button */}
            <GenerateButton
              generationType={generationType}
              isSubmitting={isSubmitting}
              isJobRunning={currentJob?.status === 'in_progress'}
              onClick={handleGenerate}
              disabled={isLoadingManifest}
              error={error}
            />
          </div>
        </section>

        {/* Right Column: Viewport, Status, and Telemetry */}
        <section aria-label="Asset Output & Telemetry">
          {/* Active Job Status Card */}
          {currentJob && (
            <JobStatusCard
              job={currentJob}
              onRefresh={() => currentJob.job_id && pollJobStatus(currentJob.job_id).then(setCurrentJob)}
            />
          )}

          {/* Generated Asset Preview & Download */}
          <AssetPreview
            currentJob={currentJob}
            generationType={generationType}
            prompt={prompt}
          />
        </section>
      </main>

      {/* Persistent History Panel across bottom */}
      <footer style={{ padding: '0 1.5rem 2rem', maxWidth: '1600px', margin: '0 auto', width: '100%' }}>
        <HistoryPanel
          history={history}
          isLoading={isLoadingHistory}
          onSelectItem={handleSelectHistoryItem}
          selectedJobId={currentJob?.job_id}
        />
      </footer>

      {/* Authentication Modal */}
      <AuthModal
        isOpen={isAuthModalOpen}
        onClose={() => setIsAuthModalOpen(false)}
        onKeyUpdated={() => setHasApiKey(Boolean(getStoredApiKey()))}
      />
    </div>
  );
};
