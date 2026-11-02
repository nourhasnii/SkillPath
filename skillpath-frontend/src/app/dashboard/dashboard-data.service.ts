import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export type EntityKind =
  | 'Competence'
  | 'Formation'
  | 'Module'
  | 'Metier'
  | 'FamilleMetier'
  | 'ProfilUtilisateur'
  | 'Niveau'
  | 'Parcours'
  | 'Evaluation';

export interface EntityConfig {
  kind: EntityKind;
  slug: string;
  label: string;
  singular: string;
  properties: { key: string; label: string; type?: string; required?: boolean }[];
  relations: { key: string; label: string; target: EntityKind; single?: boolean }[];
}

export interface EntityListItem {
  id: string;
  label: string;
  class?: string;
}

export interface RelatedEntity {
  id: string;
  label: string;
  formations?: RelatedEntity[];
}

export interface EntityDetail {
  id: string;
  type: EntityKind;
  class: string;
  label: string;
  properties: Record<string, string[]>;
  relations: Record<string, RelatedEntity[]>;
}

export interface DashboardStats {
  competences: number;
  metiers: number;
  formations: number;
  profils: number;
  modules: number;
  parcours: number;
  evaluations: number;
}

export interface PublicDashboardStats {
  competences: number;
  formations: number;
  metiers: number;
}

export interface CatalogueReference {
  id: string;
  label: string;
}

export interface CatalogueTraining {
  id: string;
  nom: string;
  type: string;
  duree_heures: number | null;
  competences_enseignees: CatalogueReference[];
  prerequis: CatalogueReference[];
  modules?: CatalogueReference[];
}

export interface CatalogueModule {
  id: string;
  nom: string;
  competences_enseignees: CatalogueReference[];
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
}

export interface GraphEdge {
  id: string;
  from: string;
  to: string;
  relation: string;
}

export interface GraphSnapshot {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface RedundantCompetencyPair {
  id_a: string;
  name_a: string;
  class_a: string;
  id_b: string;
  name_b: string;
  class_b: string;
  score: number;
  explanation: string;
}

export interface RedundantCompetenciesReport {
  threshold: number;
  total_competencies: number;
  pair_count: number;
  pairs: RedundantCompetencyPair[];
}

export interface SharedCompetencyOccupation {
  id: string;
  name: string;
}

export interface SharedCompetency {
  id: string;
  name: string;
  occupation_count: number;
  occupations: SharedCompetencyOccupation[];
}

export interface SharedCompetenciesReport {
  total_competencies: number;
  competencies: SharedCompetency[];
}

export interface UntaughtCompetency {
  id: string;
  name: string;
  class: 'CompetenceTechnique' | 'CompetenceTransverse';
}

export interface UntaughtCompetenciesReport {
  total_competencies: number;
  competencies: UntaughtCompetency[];
}

export interface AnalyticsSegment {
  key: string;
  label: string;
  count: number;
}

/**
 * Aggregated knowledge-base analytics for the administration dashboard.
 *
 * Every array is built by the backend from real RDF individuals stored in
 * Fuseki: an empty array means the category genuinely has no individual, it is
 * never a fabricated fallback.
 */
export interface DashboardAnalytics {
  competencyDistribution: AnalyticsSegment[];
  occupationsByFamily: AnalyticsSegment[];
  profilesDistribution: AnalyticsSegment[];
  trainingsDistribution: AnalyticsSegment[];
  repositoryOverview: AnalyticsSegment[];
}

export const ENTITY_CONFIGS: EntityConfig[] = [
  {
    kind: 'Competence',
    slug: 'competences',
    label: 'Competences',
    singular: 'Competence',
    properties: [
      { key: 'aNom', label: 'Name' },
      { key: 'aCodeESCO', label: 'ESCO code' }
    ],
    relations: [
      { key: 'occupations_that_require', label: 'Required by occupations', target: 'Metier' },
      { key: 'trainings_that_teach', label: 'Taught by trainings', target: 'Formation' },
      { key: 'taught_by_modules', label: 'Taught by modules', target: 'Module' }
    ]
  },
  {
    kind: 'Metier',
    slug: 'occupations',
    label: 'Occupations',
    singular: 'Occupation',
    properties: [
      { key: 'aNom', label: 'Name' },
      { key: 'aCodeESCO', label: 'ESCO code' }
    ],
    relations: [
      { key: 'requiert', label: 'Required competences', target: 'Competence' },
      { key: 'appartientA', label: 'Occupation family', target: 'FamilleMetier' },
      { key: 'necessiteNiveau', label: 'Required levels', target: 'Niveau' }
    ]
  },
  {
    kind: 'FamilleMetier',
    slug: 'families',
    label: 'Occupation families',
    singular: 'Occupation family',
    properties: [{ key: 'aNom', label: 'Name' }],
    relations: [{ key: 'metiers', label: 'Occupations', target: 'Metier' }]
  },
  {
    kind: 'Niveau',
    slug: 'levels',
    label: 'Levels',
    singular: 'Level',
    properties: [
      { key: 'aNom', label: 'Name' },
      { key: 'aNiveau', label: 'Value', type: 'number' }
    ],
    relations: [
      { key: 'metiers', label: 'Occupations', target: 'Metier' },
      { key: 'profils', label: 'Profiles', target: 'ProfilUtilisateur' }
    ]
  },
  {
    kind: 'Formation',
    slug: 'trainings',
    label: 'Trainings',
    singular: 'Training',
    properties: [
      { key: 'aNom', label: 'Name' },
      { key: 'aDureeHeures', label: 'Duration (hours)', type: 'number' },
      { key: 'aDateDebut', label: 'Start date', type: 'datetime-local' }
    ],
    relations: [
      { key: 'enseigne', label: 'Teaches competences', target: 'Competence' },
      { key: 'aPourPrerequis', label: 'Prerequisites', target: 'Formation' },
      { key: 'contientModule', label: 'Modules', target: 'Module' }
    ]
  },
  {
    kind: 'Module',
    slug: 'modules',
    label: 'Modules',
    singular: 'Module',
    properties: [{ key: 'aNom', label: 'Name' }],
    relations: [
      { key: 'moduleEnseigne', label: 'Teaches competences', target: 'Competence' },
      { key: 'formations', label: 'Included in trainings', target: 'Formation' }
    ]
  },
  {
    kind: 'ProfilUtilisateur',
    slug: 'profiles',
    label: 'Profiles',
    singular: 'Profile',
    properties: [{ key: 'aNom', label: 'Name' }],
    relations: [
      { key: 'aAcquis', label: 'Acquired competences', target: 'Competence' },
      { key: 'vise', label: 'Target occupations', target: 'Metier' },
      { key: 'aSuivi', label: 'Followed trainings', target: 'Formation' },
      { key: 'parcours', label: 'Learning paths', target: 'Parcours' },
      { key: 'niveau', label: 'Level', target: 'Niveau', single: true },
      { key: 'evaluations', label: 'Evaluations', target: 'Evaluation' }
    ]
  },
  {
    kind: 'Evaluation',
    slug: 'evaluations',
    label: 'Evaluations',
    singular: 'Evaluation',
    properties: [{ key: 'aNom', label: 'Name', required: true }],
    relations: [{ key: 'profils', label: 'Profiles', target: 'ProfilUtilisateur' }]
  },
  {
    kind: 'Parcours',
    slug: 'parcours',
    label: 'Parcours',
    singular: 'Parcours',
    properties: [{ key: 'aNom', label: 'Name' }],
    relations: [{ key: 'contientFormation', label: 'Trainings', target: 'Formation' }]
  }
];

const API_ROOT = 'http://localhost:8000';
const API_BASE = `${API_ROOT}/api`;

@Injectable({ providedIn: 'root' })
export class DashboardDataService {
  private readonly http = inject(HttpClient);

  getStats(): Observable<DashboardStats> {
    return this.http.get<DashboardStats>(`${API_BASE}/stats`, { withCredentials: true });
  }

  getPublicDashboard(): Observable<PublicDashboardStats> {
    return this.http.get<PublicDashboardStats>(`${API_ROOT}/dashboard`);
  }

  getPublicCatalogue(): Observable<CatalogueTraining[]> {
    return this.http.get<CatalogueTraining[]>(`${API_ROOT}/formations`);
  }

  getPublicTraining(id: string): Observable<CatalogueTraining> {
    return this.http.get<CatalogueTraining>(`${API_ROOT}/formations/${encodeURIComponent(id)}`);
  }

  getPublicModule(id: string): Observable<CatalogueModule> {
    return this.http.get<CatalogueModule>(`${API_ROOT}/modules/${encodeURIComponent(id)}`);
  }

  followProfileTrainings(profileId: string, trainingIds: string[]): Observable<{
    profil: string;
    formations_suivies: string[];
  }> {
    return this.http.put<{ profil: string; formations_suivies: string[] }>(
      `${API_ROOT}/profils/${encodeURIComponent(profileId)}`,
      { formations_suivies: trainingIds },
      { withCredentials: true }
    );
  }

  getGraph(): Observable<GraphSnapshot> {
    return this.http.get<GraphSnapshot>(`${API_ROOT}/graph`, { withCredentials: true });
  }

  getRedundantCompetencies(threshold: number): Observable<RedundantCompetenciesReport> {
    const params = new HttpParams().set('threshold', String(threshold));
    return this.http.get<RedundantCompetenciesReport>(`${API_ROOT}/admin/redundant-competencies`, {
      params,
      withCredentials: true
    });
  }

  getSharedCompetencies(): Observable<SharedCompetenciesReport> {
    return this.http.get<SharedCompetenciesReport>(`${API_ROOT}/admin/shared-competencies`, {
      withCredentials: true
    });
  }

  getUntaughtCompetencies(): Observable<UntaughtCompetenciesReport> {
    return this.http.get<UntaughtCompetenciesReport>(`${API_ROOT}/admin/untaught-competencies`, {
      withCredentials: true
    });
  }

  getDashboardAnalytics(): Observable<DashboardAnalytics> {
    return this.http.get<DashboardAnalytics>(`${API_ROOT}/admin/dashboard/analytics`, {
      withCredentials: true
    });
  }

  getList(
    kind: EntityKind,
    search = '',
    includeClass = false
  ): Observable<EntityListItem[]> {
    let params = new HttpParams();
    if (search.trim()) params = params.set('search', search.trim());
    if (includeClass) params = params.set('include_class', 'true');
    return this.http.get<EntityListItem[]>(`${API_BASE}/${kind}`, {
      params,
      withCredentials: true
    });
  }

  getDetail(kind: EntityKind, id: string): Observable<EntityDetail> {
    return this.http.get<EntityDetail>(`${API_BASE}/${kind}/${encodeURIComponent(id)}`, {
      withCredentials: true
    });
  }

  getClasses(kind: EntityKind): Observable<string[]> {
    return this.http.get<string[]>(`${API_BASE}/${kind}/classes`, { withCredentials: true });
  }

  create(kind: EntityKind, payload: { id: string; class: string; properties: Record<string, string[]>; relations: Record<string, string[]> }): Observable<unknown> {
    return this.http.post(`${API_BASE}/${kind}`, payload, { withCredentials: true });
  }

  update(kind: EntityKind, id: string, payload: { class: string; properties: Record<string, string[]>; relations: Record<string, string[]> }): Observable<unknown> {
    return this.http.put(`${API_BASE}/${kind}/${encodeURIComponent(id)}`, payload, {
      withCredentials: true
    });
  }

  delete(kind: EntityKind, id: string): Observable<unknown> {
    return this.http.delete(`${API_BASE}/${kind}/${encodeURIComponent(id)}`, {
      withCredentials: true
    });
  }
}

export function configForKind(kind: string | null | undefined): EntityConfig | undefined {
  return ENTITY_CONFIGS.find(config => config.kind === kind || config.slug === kind);
}

export function configForSlug(slug: string | null | undefined): EntityConfig | undefined {
  return ENTITY_CONFIGS.find(config => config.slug === slug);
}

export function configForType(kind: EntityKind): EntityConfig {
  return ENTITY_CONFIGS.find(config => config.kind === kind)!;
}

export function displayEntityName(value: string): string {
  return value.replace(/^_?(?:comp|form|met|profil|mod|parc|eval)_/, '');
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  if (typeof error === 'object' && error !== null && 'error' in error) {
    const body = error.error;
    if (typeof body === 'object' && body !== null && 'detail' in body && typeof body.detail === 'string') {
      return body.detail;
    }
  }
  return fallback;
}
