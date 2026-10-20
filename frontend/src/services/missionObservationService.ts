/**
 * AryaOS V1 — Stage 12: Mission Observation Loop
 *
 * Captures, categories, and logs meaningful mission-level operational events:
 * PROGRESS, QUALITY, RESOURCE, DEADLINE, FAILURE, RISK, DEPENDENCY, LEARNING, HUMAN_DECISION.
 */

import {
  MissionObservation,
  MissionObservationCategory,
} from '../types/missionControl';
import { executionPersistence } from './executionPersistence';

export class MissionObservationService {
  /**
   * Records a structured mission observation.
   */
  public recordObservation(
    missionId: string,
    category: MissionObservationCategory,
    summary: string,
    details: Record<string, unknown> = {}
  ): MissionObservation {
    const observationId = `mobs-${missionId}-${Date.now()}-${Math.random().toString(36).substr(2, 6)}`;
    const timestamp = new Date().toISOString();

    const sanitizedDetails = executionPersistence.sanitizeForPersistence(details);

    const observation: MissionObservation = {
      observationId,
      missionId,
      category,
      summary,
      timestamp,
      details: sanitizedDetails,
    };

    // Update mission in persistence
    const mission = executionPersistence.getMission(missionId);
    if (mission) {
      if (!mission.observations) mission.observations = [];
      mission.observations.push(observation);
      mission.updatedAt = timestamp;
      executionPersistence.saveMission(mission);
    }

    return observation;
  }

  /**
   * Retrieves observations for a mission, optionally filtered by category.
   */
  public getObservations(
    missionId: string,
    category?: MissionObservationCategory
  ): MissionObservation[] {
    const mission = executionPersistence.getMission(missionId);
    if (!mission || !mission.observations) return [];
    if (category) {
      return mission.observations.filter((o) => o.category === category);
    }
    return [...mission.observations];
  }
}

export const missionObservationService = new MissionObservationService();
