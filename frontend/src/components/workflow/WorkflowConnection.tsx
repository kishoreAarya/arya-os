import React from 'react';
import './WorkflowOrbit.css';

export interface WorkflowConnectionProps {
  active?: boolean;
  completed?: boolean;
  error?: boolean;
}

export const WorkflowConnection: React.FC<WorkflowConnectionProps> = ({
  active = false,
  completed = false,
  error = false,
}) => {
  let statusClass = 'connection-pending';
  if (error) statusClass = 'connection-error';
  else if (completed) statusClass = 'connection-completed';
  else if (active) statusClass = 'connection-active';

  return (
    <div className={`workflow-connection ${statusClass}`} aria-hidden="true">
      <div className="connection-track" />
      {active && <div className="connection-pulse" />}
    </div>
  );
};
