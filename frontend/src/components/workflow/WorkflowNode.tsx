import React from 'react';
import { Check } from 'lucide-react';
import './WorkflowOrbit.css';

export interface WorkflowNodeProps {
  id: string;
  label: string;
  icon: React.ReactNode;
  status: 'pending' | 'active' | 'completed' | 'error';
  sublabel?: string;
  onClick?: () => void;
  isCurrent?: boolean;
}

export const WorkflowNode: React.FC<WorkflowNodeProps> = ({
  id,
  label,
  icon,
  status,
  sublabel,
  onClick,
  isCurrent,
}) => {
  return (
    <div
      className={`workflow-node workflow-node-${status} ${isCurrent ? 'workflow-node-current' : ''}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      title={`${label} (${status})`}
      onKeyDown={(e) => {
        if ((e.key === 'Enter' || e.key === ' ') && onClick) {
          e.preventDefault();
          onClick();
        }
      }}
      data-node-id={id}
    >
      <div className="workflow-node-icon-wrap">
        {status === 'completed' ? (
          <Check size={14} className="workflow-node-check" />
        ) : (
          icon
        )}
      </div>

      <div className="workflow-node-content">
        <span className="workflow-node-label">{label}</span>
        {sublabel && <span className="workflow-node-sublabel">{sublabel}</span>}
      </div>
    </div>
  );
};
