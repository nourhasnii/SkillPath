import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, catchError, map, of, shareReplay, switchMap, tap } from 'rxjs';

import { AccountProfile, AuthService, LevelInfo, profileCompletion } from '../auth/auth.service';
import { DashboardDataService } from '../dashboard/dashboard-data.service';

/**
 * Typed access to the real SkillPath analysis endpoints.
 *
 * Every shape below mirrors what `app/main.py` actually returns. Values that the
 * ontology does not record (course duration, provider, graded proficiency) are
 * expressed as `null` / absent so the UI can show an honest unavailable state
 * instead of an invented one.
 */

export type SkillStatus = 'acquise' | 'en_cours' | 'manquante';
export type SkillPriority = 'aucune' | 'basse' | 'moyenne' | 'haute';
export type RoadmapPhase = 'fondation' | 'intermediaire' | 'avance' | 'terminee';

export interface SkillComparison {
  id: string;
  label: string;
  statut: SkillStatus;
  priorite: SkillPriority;
  formations_recommandees: string[];
}

/** A required competency acquired through a training the profile actually followed. */
export interface FormationAcquiredCompetency {
  competence: string;
  formation: string;
  formation_label: string;
}

export interface SkillGapReport {
  profil: string;
  metier: string;
  competences_requises: string[];
  competences_acquises: string[];
  competences_declarees: string[];
  competences_via_formation: FormationAcquiredCompetency[];
  competences_manquantes: string[];
  competences_en_cours: string[];
  match_score: number;
  formations_recommandees: string[];
  competences: SkillComparison[];
}

export interface LearningStep {
  ordre: number;
  formation: string;
  label: string;
  type: string;
  duree_heures: number | null;
  prerequis: string[];
  prerequis_satisfaits: string[];
  competences_couvertes: string[];
  deja_suivie: boolean;
  statut: 'a_suivre' | 'terminee';
  phase: RoadmapPhase;
}

export interface LearningPathProgression {
  total: number;
  terminees: number;
  pourcentage: number;
  heures_restantes: number | null;
  duree_disponible: boolean;
}

export interface LearningPathCandidate {
  id: string;
  rank: number;
  training_ids: string[];
  training_count: number;
  covered_competencies: string[];
  uncovered_competencies: string[];
  duration_hours: number | null;
  duration_available: boolean;
  prerequisites_valid: boolean;
  coverage_ratio: number;
  ranking_explanation: string;
  etapes: LearningStep[];
}

export interface LearningPathReport {
  profil: string;
  metier: string;
  competences_requises: string[];
  competences_acquises: string[];
  competences_declarees: string[];
  competences_via_formation: FormationAcquiredCompetency[];
  competences_manquantes: string[];
  competences_en_cours: string[];
  match_score: number;
  etapes: LearningStep[];
  etapes_terminees: LearningStep[];
  competences_couvertes: string[];
  competences_non_couvertes: string[];
  competences_sans_formation: string[];
  competences_bloquees_prerequis: string[];
  progression: LearningPathProgression;
}

export interface OptimalLearningPathReport extends LearningPathReport {
  candidates: LearningPathCandidate[];
  max_duration_hours: number | null;
}

export interface CareerGraphNode {
  id: string;
  label: string;
  type: 'profile' | 'skill' | 'job' | 'training';
}

export interface CareerGraphEdge {
  id: string;
  from: string;
  to: string;
  relation: string;
}

export interface CareerGraph {
  nodes: CareerGraphNode[];
  edges: CareerGraphEdge[];
}

export interface SavedPath {
  id: string;
  label: string;
  formations: { id: string; label: string }[];
}

/** Real facts about the signed-in student/professional, derived from the ontology profile. */
export interface CareerContext {
  profileIri: string | null;
  profileName: string | null;
  targetOccupation: { id: string; label: string } | null;
  acquiredSkills: string[];
  followedTrainings: string[];
  savedPaths: SavedPath[];
  profileCompletion: number;
  /** Overall readiness level of the profile (may be null until an evaluation is generated). */
  level: LevelInfo | null;
  /** Level required by the target occupation, or null when the ontology declares none. */
  requiredLevel: LevelInfo | null;
}

/** One automatic evaluation stored for the connected profile. */
export interface EvaluationSummary {
  id: string;
  label: string;
  score: number | null;
  date: string | null;
  occupation: string | null;
  diagnostic: EvaluationDiagnostic;
}

export interface EvaluationModuleSuggestion {
  id: string;
  name: string;
  durationHours: number | null;
}

export interface EvaluationTrainingSuggestion {
  id: string;
  name: string;
  durationHours: number | null;
  modules: EvaluationModuleSuggestion[];
}

export interface EvaluationCompetenceSuggestion {
  competence: string;
  trainings: EvaluationTrainingSuggestion[];
}

export interface EvaluationDiagnostic {
  strengths: string[];
  gaps: string[];
  levelReason: string;
  nextLevel: 'Intermediate' | 'Advanced' | null;
  competencesToNextLevel: number;
  requiredLevelGap: string | null;
  suggestions: EvaluationCompetenceSuggestion[];
}

export interface RecommendedTeaching {
  name: string;
  type: 'Training' | 'Module';
  duration_hours: number | null;
}

export interface SkillRecommendation {
  competence: string;
  score: number;
  explanations: string[];
  teachings: RecommendedTeaching[];
}

export interface CareerBridgeModule {
  id: string;
  name: string;
  durationHours: number | null;
}

export interface CareerBridgeTraining {
  id: string;
  name: string;
  durationHours: number | null;
  modules: CareerBridgeModule[];
}

export interface CareerBridgeGap {
  competence: string;
  trainings: CareerBridgeTraining[];
}

export interface CareerBridge {
  occupationId: string;
  occupation: string;
  family: string | null;
  percent: number;
  coveredNames: string[];
  missingNames: string[];
  trainings: CareerBridgeGap[];
}

/** Payload returned by `POST /me/evaluations/generate`. */
export interface EvaluationResult {
  score: number;
  date: string | null;
  level: LevelInfo | null;
  requiredLevel: LevelInfo | null;
  masteredCount: number;
  missingCount: number;
  occupationName: string;
  diagnostic: EvaluationDiagnostic;
  /** Present when the target occupation declares no required competency. */
  message?: string;
}

const API_ROOT = 'http://localhost:8000';

/** Turns an ontology IRI local name (`form_MoocPython`) into a readable label. */
export function humanizeIdentifier(value: string | null | undefined): string {
  if (!value) return '';
  return value
    .replace(/^_?(?:comp|form|met|profil|mod|parc|eval|niv)_/, '')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/_/g, ' ')
    .trim();
}

/**
 * Readable label of an overall readiness level.
 *
 * The ontology value (1/2/3) is authoritative; anything else falls back to the
 * declared name so the UI never invents a level the graph does not hold.
 */
export function levelLabel(level: LevelInfo | null | undefined): string {
  if (!level) return '';
  switch (level.value) {
    case 1: return 'Beginner';
    case 2: return 'Intermediate';
    case 3: return 'Advanced';
    default: return humanizeIdentifier(level.label) || level.label;
  }
}

/** Badge tone for an overall readiness level, aligned with the design system. */
export function levelTone(level: LevelInfo | null | undefined): 'danger' | 'warning' | 'success' {
  switch (level?.value) {
    case 1: return 'danger';
    case 2: return 'warning';
    case 3: return 'success';
    default: return 'warning';
  }
}

const COURSE_FORMATS: Record<string, string> = {
  FormationEnLigne: 'Online course',
  FormationPresentielle: 'On-site programme',
  Formation: 'Training'
};

/** Course format derived from the ontology class (the only delivery data we actually hold). */
export function courseFormat(courseType: string | null | undefined): string {
  if (!courseType) return 'Training';
  return COURSE_FORMATS[courseType] ?? humanizeIdentifier(courseType);
}

const PHASE_LABELS: Record<RoadmapPhase, string> = {
  fondation: 'Foundation',
  intermediaire: 'Intermediate',
  avance: 'Advanced',
  terminee: 'Completed'
};

export function phaseLabel(phase: RoadmapPhase): string {
  return PHASE_LABELS[phase] ?? 'Stage';
}

export const SKILL_STATUS_META: Record<
  SkillStatus,
  { label: string; tone: 'success' | 'warning' | 'danger'; description: string }
> = {
  acquise: { label: 'Mastered', tone: 'success', description: 'Declared as acquired in your profile.' },
  en_cours: { label: 'In progress', tone: 'warning', description: 'Covered by a training already in your profile.' },
  manquante: { label: 'Missing', tone: 'danger', description: 'Required by the occupation, not acquired yet.' }
};

export const SKILL_PRIORITY_META: Record<SkillPriority, { label: string; tone: 'neutral' | 'success' | 'warning' | 'danger' }> = {
  aucune: { label: 'No action', tone: 'neutral' },
  basse: { label: 'Low', tone: 'success' },
  moyenne: { label: 'Medium', tone: 'warning' },
  haute: { label: 'High', tone: 'danger' }
};

@Injectable({ providedIn: 'root' })
export class CareerService {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);
  private readonly data = inject(DashboardDataService);

  private contextRequest?: Observable<CareerContext>;
  private readonly contextState = signal<CareerContext | null>(null);
  readonly context = computed(() => this.contextState());

  /** One cached read of `/account/profile`; shared by the shell and every feature page. */
  loadContext(force = false): Observable<CareerContext> {
    if (force) {
      this.contextRequest = undefined;
      this.contextState.set(null);
    }
    if (!this.contextRequest) {
      this.contextRequest = this.auth.getProfile().pipe(
        map(profile => toContext(profile)),
        tap(context => this.contextState.set(context)),
        shareReplay({ bufferSize: 1, refCount: false })
      );
    }
    return this.contextRequest;
  }

  getSkillGap(profil: string, metier: string): Observable<SkillGapReport> {
    return this.http.get<SkillGapReport>(`${API_ROOT}/analyse`, {
      params: { profil, metier },
      withCredentials: true
    });
  }

  getLearningPath(
    profil: string,
    metier: string
  ): Observable<LearningPathReport> {
    return this.http.get<LearningPathReport>(`${API_ROOT}/learning-path`, {
      params: { profil, metier },
      withCredentials: true
    });
  }

  getOptimalLearningPath(
    profil: string,
    metier: string,
    maxDurationHours: number | null = null
  ): Observable<OptimalLearningPathReport> {
    const params: Record<string, string> = { profil, metier };
    if (maxDurationHours !== null) {
      params['max_duration_hours'] = String(maxDurationHours);
    }
    return this.http.get<OptimalLearningPathReport>(`${API_ROOT}/parcours-optimal`, {
      params,
      withCredentials: true
    });
  }

  getGraph(): Observable<CareerGraph> {
    return this.http.get<CareerGraph>(`${API_ROOT}/graph`, { withCredentials: true });
  }

  getAccessibleJobs(profil: string): Observable<string[]> {
    // The backend wraps the result: { profil, metiers_accessibles, nombre }.
    return this.http.get<{ metiers_accessibles: string[] }>(
      `${API_ROOT}/profils/${encodeURIComponent(profil)}/metiers-accessibles`,
      { withCredentials: true }
    ).pipe(map(response => response.metiers_accessibles ?? []));
  }

  /** Automatic evaluations already stored for the connected profile. */
  getEvaluations(): Observable<EvaluationSummary[]> {
    return this.http.get<EvaluationSummary[]>(`${API_ROOT}/me/evaluations`, {
      withCredentials: true
    });
  }

  getRecommendations(): Observable<SkillRecommendation[]> {
    return this.http.get<SkillRecommendation[]>(`${API_ROOT}/me/recommendations`, {
      withCredentials: true
    });
  }

  getCareerBridges(): Observable<CareerBridge[]> {
    return this.http.get<CareerBridge[]>(`${API_ROOT}/me/career-bridges`, {
      withCredentials: true
    });
  }

  setTargetOccupation(profileId: string, occupationId: string): Observable<void> {
    return this.http.patch<void>(
      `${API_ROOT}/api/profile/${encodeURIComponent(profileId)}`,
      { target_occupation: occupationId },
      { withCredentials: true }
    );
  }

  /**
   * Level required by an occupation (`sp:necessiteNiveau` → `sp:aNiveau`).
   *
   * Read through the public entity endpoints so the "required vs your level"
   * comparison always reflects the occupation actually being analysed, never
   * only the profile's stored target.
   */
  getRequiredLevel(metier: string): Observable<LevelInfo | null> {
    return this.data.getDetail('Metier', metier).pipe(
      switchMap(detail => {
        const niveau = detail.relations?.['necessiteNiveau']?.[0];
        if (!niveau) return of(null);
        return this.data.getDetail('Niveau', niveau.id).pipe(
          map(niveauDetail => ({
            id: niveauDetail.id,
            label: niveauDetail.label || niveau.label,
            value: toInteger(niveauDetail.properties?.['aNiveau']?.[0])
          })),
          catchError(() => of({ id: niveau.id, label: niveau.label, value: null }))
        );
      }),
      catchError(() => of(null))
    );
  }

  /**
   * Recomputes the automatic evaluation of the connected profile against its
   * target occupation. The profile is always taken from the auth token.
   */
  generateEvaluation(): Observable<EvaluationResult> {
    return this.http.post<EvaluationResult>(
      `${API_ROOT}/me/evaluations/generate`,
      {},
      { withCredentials: true }
    );
  }
}

function toInteger(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? null : parsed;
}

function toContext(profile: AccountProfile | null | undefined): CareerContext {
  const relations = profile?.profile?.relations ?? {};
  const target = relations['vise']?.[0];
  return {
    profileIri: profile?.profile?.id ?? profile?.profile_iri ?? null,
    profileName: profile?.profile?.label ?? profile?.full_name ?? null,
    targetOccupation: target ? { id: target.id, label: target.label } : null,
    acquiredSkills: (relations['aAcquis'] ?? []).map(item => item.id),
    followedTrainings: (relations['aSuivi'] ?? []).map(item => item.id),
    savedPaths: (relations['parcours'] ?? []).map(path => ({
      id: path.id,
      label: path.label,
      formations: (path.formations ?? []).map(training => ({ id: training.id, label: training.label }))
    })),
    profileCompletion: profileCompletion(profile, profile?.role),
    level: profile?.level ?? null,
    requiredLevel: profile?.requiredLevel ?? null
  };
}
