import React from 'react';
import {
  FileText,
  Image as ImageIcon,
  Cpu,
  Play,
  Sparkles,
  Film,
  GitCommit,
} from 'lucide-react';
import { GenerationType } from '../../types/creator';
import { WorkflowNode, WorkflowNodeProps } from './WorkflowNode';
import { WorkflowConnection } from './WorkflowConnection';
import './WorkflowOrbit.css';

export interface WorkflowOrbitProps {
  generationType: GenerationType;
  hasPrompt: boolean;
  hasReference: boolean;
  hasModel: boolean;
  modelName?: string;
  isGenerating: boolean;
  isProcessing: boolean;
  isCompleted: boolean;
  isError: boolean;
  startFrameUrl?: string;
  endFrameUrl?: string;
  onNodeClick?: (nodeId: string) => void;
  isPreflightBlocked?: boolean;
}

export const WorkflowOrbit: React.FC<WorkflowOrbitProps> = ({
  generationType,
  hasPrompt,
  hasReference,
  hasModel,
  modelName,
  isGenerating,
  isProcessing,
  isCompleted,
  isError,
  startFrameUrl,
  endFrameUrl,
  onNodeClick,
  isPreflightBlocked = false,
}) => {
  const isImageToVideo = generationType === 'image_to_video';

  // Construct Stage 3 pipeline nodes based on generation mode
  const nodes: WorkflowNodeProps[] = isImageToVideo
    ? [
        {
          id: 'reference',
          label: 'Reference Image',
          icon: <ImageIcon size={13} />,
          status: hasReference ? 'completed' : 'active',
          sublabel: hasReference ? 'Supplied' : 'Required',
          isCurrent: !hasReference,
        },
        {
          id: 'start_frame',
          label: 'Start Frame',
          icon: <Film size={13} />,
          status: startFrameUrl ? 'completed' : hasReference ? 'completed' : 'pending',
          sublabel: startFrameUrl ? 'Set' : hasReference ? 'Inherited' : 'Required',
          isCurrent: hasReference && !startFrameUrl && !isGenerating && !isProcessing && !isCompleted && !isError,
        },
        {
          id: 'motion_gen',
          label: 'Motion Engine',
          icon: <Play size={13} />,
          status: isError
            ? 'error'
            : isGenerating || isProcessing
            ? 'active'
            : isCompleted
            ? 'completed'
            : 'pending',
          sublabel: isError
            ? 'Failed'
            : isGenerating
            ? 'Submitting'
            : isProcessing
            ? 'Synthesizing'
            : isPreflightBlocked
            ? 'Blocked'
            : modelName || 'Kling',
          isCurrent: isGenerating || isProcessing,
        },
        {
          id: 'end_frame',
          label: 'End Frame',
          icon: <Film size={13} />,
          status: endFrameUrl ? 'completed' : 'pending',
          sublabel: endFrameUrl ? 'Locked' : 'Optional',
        },
        {
          id: 'video_output',
          label: 'Video Asset',
          icon: <Sparkles size={13} />,
          status: isCompleted ? 'completed' : 'pending',
          sublabel: isCompleted ? 'Ready' : isError ? 'Interrupted' : 'Output',
          isCurrent: isCompleted,
        },
      ]
    : [
        {
          id: 'prompt',
          label: 'Prompt',
          icon: <FileText size={13} />,
          status: hasPrompt ? 'completed' : 'active',
          sublabel: hasPrompt ? 'Defined' : 'Required',
          isCurrent: !hasPrompt,
        },
        {
          id: 'reference',
          label: 'Reference',
          icon: <ImageIcon size={13} />,
          status: hasReference ? 'completed' : 'pending',
          sublabel: hasReference ? 'Attached' : 'Optional',
        },
        {
          id: 'model',
          label: 'AI Model',
          icon: <Cpu size={13} />,
          status: hasModel ? 'completed' : 'pending',
          sublabel: modelName ? modelName.split('/')[1] || modelName : 'Selected',
          isCurrent: hasPrompt && !isGenerating && !isProcessing && !isCompleted && !isError,
        },
        {
          id: 'generate',
          label: 'Generate',
          icon: <Play size={13} />,
          status: isError
            ? 'error'
            : isGenerating || isProcessing
            ? 'active'
            : isCompleted
            ? 'completed'
            : 'pending',
          sublabel: isError
            ? 'Failed'
            : isGenerating
            ? 'Queuing'
            : isProcessing
            ? 'Processing'
            : isPreflightBlocked
            ? 'Blocked'
            : hasPrompt
            ? 'Ready'
            : 'Standby',
          isCurrent: isGenerating || isProcessing,
        },
        {
          id: 'preview',
          label: 'Asset Viewport',
          icon: <Sparkles size={13} />,
          status: isCompleted ? 'completed' : 'pending',
          sublabel: isCompleted ? 'Produced' : isError ? 'Interrupted' : 'Awaiting',
          isCurrent: isCompleted,
        },
      ];

  const currentStageLabel = isError
    ? 'Execution Error'
    : isCompleted
    ? 'Asset Produced'
    : isProcessing
    ? 'Synthesizing Media'
    : isGenerating
    ? 'Dispatching Task'
    : isPreflightBlocked
    ? 'Configuration Blocked'
    : hasPrompt
    ? 'Pipeline Armed'
    : 'Awaiting Parameters';

  return (
    <div
      className={`workflow-orbit-card ${isError ? 'workflow-card-error' : ''}`}
      role="region"
      aria-label="Generation Workflow Pipeline"
    >
      <div className="workflow-orbit-header">
        <div className="workflow-orbit-title">
          <GitCommit size={14} color="var(--accent-primary)" />
          <span>Spatial Workflow Pipeline</span>
        </div>

        <span
          className={`workflow-orbit-stage-badge ${
            isError
              ? 'badge-stage-error'
              : isCompleted
              ? 'badge-stage-complete'
              : isGenerating || isProcessing
              ? 'badge-stage-active'
              : ''
          }`}
        >
          {currentStageLabel}
        </span>
      </div>

      <div className="workflow-nodes-flow">
        {nodes.map((node, index) => {
          const isNextCompleted = index < nodes.length - 1 && nodes[index + 1].status === 'completed';
          const isNextActive = index < nodes.length - 1 && nodes[index + 1].status === 'active';
          const isNextError = index < nodes.length - 1 && nodes[index + 1].status === 'error';

          return (
            <React.Fragment key={node.id}>
              <WorkflowNode
                {...node}
                onClick={() => onNodeClick && onNodeClick(node.id)}
              />

              {index < nodes.length - 1 && (
                <WorkflowConnection
                  completed={node.status === 'completed' && isNextCompleted}
                  active={(node.status === 'completed' && isNextActive) || (node.status === 'active' && !isNextCompleted)}
                  error={node.status === 'completed' && isNextError}
                />
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
};

