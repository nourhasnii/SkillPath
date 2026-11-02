import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

/**
 * Typed access to the Smart Profile endpoints of `app/main.py`.
 *
 * Every field mirrors an assertion of the SkillPath ontology:
 * `vise` → Metier, `aAcquis` → Competence, `aSuivi` → Formation,
 * `suitParcours` → Parcours (`contientFormation`), `aPasseEvaluation` → Evaluation.
 * Nothing is computed or invented on the client.
 */

export interface ProfileReference {
  id: string;
  label: string;
}

export interface ProfilePath {
  id: string;
  label: string;
  formations: ProfileReference[];
}

export interface ProfileCompleteness {
  /** 25 points per satisfied block: target occupation, skills, trainings, path or evaluation. */
  score: number;
  /** Keys of the blocks that are still empty. */
  missing: string[];
}

export interface SmartProfileView {
  id: string;
  label: string;
  types: string[];
  target_occupation: ProfileReference | null;
  skills_acquired: ProfileReference[];
  trainings_followed: ProfileReference[];
  parcours: ProfilePath | null;
  evaluations: ProfileReference[];
  completeness: ProfileCompleteness;
}

/** Candidate returned by the local spaCy + rapidfuzz matcher (no LLM involved). */
export interface SkillCandidate {
  iri: string;
  label: string;
  /** 0-100 `fuzz.token_set_ratio` between the typed fragment and the ontology label. */
  score: number;
  /** The fragment of the typed text the candidate was matched from. */
  mention: string;
}

export interface ProfilePatch {
  target_occupation?: string | null;
  skills_add?: string[];
  skills_remove?: string[];
  trainings_add?: string[];
  trainings_remove?: string[];
}

export interface SkillResolution {
  text: string;
  candidates: SkillCandidate[];
}

const API_ROOT = 'http://localhost:8000';

@Injectable({ providedIn: 'root' })
export class SmartProfileService {
  private readonly http = inject(HttpClient);

  getProfile(profileId: string): Observable<SmartProfileView> {
    return this.http.get<SmartProfileView>(
      `${API_ROOT}/api/profile/${encodeURIComponent(profileId)}`,
      { withCredentials: true }
    );
  }

  /** Applies a partial update; the response is the recomputed profile view. */
  patchProfile(profileId: string, patch: ProfilePatch): Observable<SmartProfileView> {
    return this.http.patch<SmartProfileView>(
      `${API_ROOT}/api/profile/${encodeURIComponent(profileId)}`,
      patch,
      { withCredentials: true }
    );
  }

  resolveSkills(text: string): Observable<SkillResolution> {
    return this.http.post<SkillResolution>(
      `${API_ROOT}/api/profile/resolve-skills`,
      { text },
      { withCredentials: true }
    );
  }
}
