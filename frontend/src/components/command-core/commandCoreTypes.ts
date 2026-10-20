import React from 'react';
import { GenerationType } from '../../types/creator';

export type CommandCoreState =
  | 'idle'
  | 'configuring'
  | 'ready'
  | 'generating'
  | 'processing'
  | 'complete'
  | 'error';

export interface CommandCoreProps {
  state: CommandCoreState;
  generationType: GenerationType;
  progress?: number; // 0 to 100
  modelName?: string;
  onClick?: () => void;
  className?: string;
  style?: React.CSSProperties;
}
