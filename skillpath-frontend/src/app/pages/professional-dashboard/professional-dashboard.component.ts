import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import { finalize, forkJoin } from 'rxjs';

import { AuthService } from '../../auth/auth.service';
import { apiErrorMessage } from '../../dashboard/dashboard-data.service';
import { CareerSelection, CareerSelectorComponent } from '../../career/career-selector.component';
import { RecommendedForYouComponent } from '../../career/recommended-for-you.component';
import { ChartTone, RingChartComponent } from '../../career/charts/ring-chart.component';
import { SkillBar, SkillBarChartComponent } from '../../career/charts/skill-bar-chart.component';
import { IconComponent } from '../../career/icon.component';
import { CourseCoverComponent } from '../../career/course-cover.component';
import { LevelCompareComponent } from '../../career/level-compare.component';
import {
  CareerGraph,
  CareerGraphNode,
  CareerService,
  LearningPathReport,
  LearningStep,
  SkillComparison,
  SkillGapReport,
  SkillPriority,
  SKILL_PRIORITY_META,
  humanizeIdentifier,
  levelLabel,
  levelTone,
  phaseLabel,
  courseFormat
} from '../../career/career.service';

type NodeType = CareerGraphNode['type'];

interface PreviewNode {
  node: CareerGraphNode;
  x: number;
  y: number;
}

interface GraphPreview {
  focus: PreviewNode;
  nodes: PreviewNode[];
  total: number;
}

/** One stage of the career transition rail — always derived from real analysis data. */
interface TransitionStage {
  index: number;
  title: string;
  note: string;
  chips: string[];
  state: 'done' | 'current' | 'upcoming';
}

const PRIORITY_ORDER: Record<SkillPriority, number> = {
  haute: 0,
  moyenne: 1,
  basse: 2,
  aucune: 3
};

const PREVIEW_COLORS: Record<NodeType, string> = {
  profile: '#5B4FE9',
  skill: '#10B981',
  job: '#2563EB',
  training: '#F59E0B'
};

const PREVIEW_RADIUS: Record<NodeType, number> = {
  profile: 12,
  skill: 6,
  job: 9,
  training: 8
};

const PREVIEW_WIDTH = 300;
const PREVIEW_HEIGHT = 200;

@Component({
  selector: 'app-professional-dashboard',
  standalone: true,
  imports: [
    RouterLink,
    CareerSelectorComponent,
    RecommendedForYouComponent,
    RingChartComponent,
    SkillBarChartComponent,
    IconComponent,
    CourseCoverComponent,
    LevelCompareComponent
  ],
  templateUrl: './professional-dashboard.component.html',
  styleUrl: './professional-dashboard.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class ProfessionalDashboardComponent {
  private readonly auth = inject(AuthService);
  private readonly career = inject(CareerService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly loading = signal(false);
  protected readonly error = signal('');
  protected readonly gap = signal<SkillGapReport | null>(null);
  protected readonly path = signal<LearningPathReport | null>(null);
  protected readonly accessibleJobs = signal<string[]>([]);
  private readonly graph = signal<CareerGraph | null>(null);

  protected readonly context = this.career.context;
  protected readonly user = this.auth.currentUser;

  /* ------------------------------------------------------- identity (A) */

  protected readonly fullName = computed(() => this.user()?.full_name?.trim() ?? '');

  protected readonly firstName = computed(() => this.fullName().split(/\s+/)[0] ?? '');

  protected readonly initials = computed(() => {
    const name = this.fullName();
    if (!name) return 'SP';
    return name
      .split(/\s+/)
      .slice(0, 2)
      .map(part => part.charAt(0).toUpperCase())
      .join('');
  });

  protected readonly greeting = computed(() => {
    const hour = new Date().getHours();
    const part = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
    const name = this.firstName();
    return name ? `${part}, ${name}` : part;
  });

  /** The signed-in professional's own profile label — never a hardcoded job title. */
  protected readonly currentPosition = computed(
    () => this.context()?.profileName?.trim() || this.fullName() || 'Your profile'
  );

  protected readonly experience = computed(() => this.user()?.experience?.trim() ?? '');

  /* --------------------------------------------- position overview (B) */

  protected readonly targetLabel = computed(() =>
    humanizeIdentifier(this.gap()?.metier ?? this.context()?.targetOccupation?.label ?? '')
  );

  /* ------------------------------------------------------- readiness level */

  protected readonly level = computed(() => this.context()?.level ?? null);
  protected readonly requiredLevel = computed(() => this.context()?.requiredLevel ?? null);
  protected readonly levelText = computed(() => levelLabel(this.level()));
  protected readonly levelBadgeClass = computed(() => `sp-badge sp-badge-${levelTone(this.level())}`);

  protected readonly transitionReadiness = computed(() => this.gap()?.match_score ?? 0);

  protected readonly matchTone = computed<ChartTone>(() => {
    const score = this.transitionReadiness();
    if (score >= 80) return 'emerald';
    if (score >= 50) return 'violet';
    if (score >= 20) return 'amber';
    return 'rose';
  });

  protected readonly compatibilityLabel = computed(() => {
    const score = this.transitionReadiness();
    if (score >= 80) return 'Highly compatible';
    if (score >= 50) return 'On track';
    if (score >= 20) return 'Developing';
    return 'Early stage';
  });

  protected readonly compatibilityBadge = computed(() => {
    switch (this.matchTone()) {
      case 'emerald': return 'sp-badge sp-badge-success';
      case 'violet': return 'sp-badge sp-badge-violet';
      case 'amber': return 'sp-badge sp-badge-warning';
      default: return 'sp-badge sp-badge-danger';
    }
  });

  protected readonly requiredCount = computed(() => this.gap()?.competences_requises.length ?? 0);
  protected readonly transferableCount = computed(() => this.gap()?.competences_acquises.length ?? 0);
  protected readonly priorityGapCount = computed(() => this.gap()?.competences_manquantes.length ?? 0);
  protected readonly inProgressCount = computed(() => this.gap()?.competences_en_cours.length ?? 0);

  /* ------------------------------------------ skills intelligence (C) */

  protected readonly transferableSkills = computed<SkillComparison[]>(() =>
    (this.gap()?.competences ?? []).filter(skill => skill.statut === 'acquise')
  );

  /** Bar chart input — real competency coverage, never synthetic values. */
  protected readonly transferableBars = computed<SkillBar[]>(() =>
    this.transferableSkills()
      .slice(0, 7)
      .map(skill => ({
        id: skill.id,
        label: this.displayName(skill.label || skill.id),
        status: skill.statut,
        note: `Mastered · transferable to ${this.targetLabel() || 'the target role'}`
      }))
  );

  protected readonly priorityGaps = computed<SkillComparison[]>(() =>
    (this.gap()?.competences ?? [])
      .filter(skill => skill.statut === 'manquante')
      .sort((a, b) => PRIORITY_ORDER[a.priorite] - PRIORITY_ORDER[b.priorite])
  );

  protected readonly visibleGaps = computed(() => this.priorityGaps().slice(0, 5));

  /* ---------------------------------------------- upskilling strategy (D) */

  protected readonly recommendedFormations = computed<string[]>(() => {
    const ids = this.gap()?.formations_recommandees ?? [];
    return ids.slice(0, 4).map(id => humanizeIdentifier(id));
  });

  protected readonly upskillingRecommendations = computed<LearningStep[]>(() =>
    (this.path()?.etapes ?? [])
      .filter(step => step.statut === 'a_suivre' && (step.phase === 'avance' || step.phase === 'intermediaire'))
      .slice(0, 3)
  );

  protected readonly nextStep = computed<LearningStep | null>(
    () => this.path()?.etapes.find(step => step.statut === 'a_suivre') ?? null
  );

  protected readonly roadmapPercent = computed(() => this.path()?.progression.pourcentage ?? 0);
  protected readonly roadmapCompleted = computed(() => this.path()?.progression.terminees ?? 0);
  protected readonly roadmapTotal = computed(() => this.path()?.progression.total ?? 0);
  protected readonly roadmapRemaining = computed(() =>
    Math.max(this.roadmapTotal() - this.roadmapCompleted(), 0)
  );
  protected readonly roadmapHours = computed(() => this.path()?.progression.heures_restantes ?? null);
  protected readonly roadmapDurationAvailable = computed(
    () => this.path()?.progression.duree_disponible ?? false
  );

  /* ------------------------------------------------ transition rail (E) */

  protected readonly transitionStages = computed<TransitionStage[]>(() => {
    const transferable = this.transferableSkills().map(skill => this.displayName(skill.label || skill.id));
    const gaps = this.priorityGaps().map(skill => this.displayName(skill.label || skill.id));
    const formations = this.recommendedFormations();

    return [
      {
        index: 1,
        title: 'Current position',
        note: this.experience() || `${this.transferableCount()} skills already recorded`,
        chips: [this.currentPosition()],
        state: 'done'
      },
      {
        index: 2,
        title: 'Transferable skills',
        note: `${this.transferableCount()} of ${this.requiredCount()} required skills covered`,
        chips: transferable.slice(0, 3),
        state: 'done'
      },
      {
        index: 3,
        title: 'Skills to acquire',
        note: `${this.priorityGapCount()} competency gaps to close`,
        chips: gaps.slice(0, 3),
        state: 'current'
      },
      {
        index: 4,
        title: 'Recommended formations',
        note: formations.length
          ? `${formations.length} trainings available in the catalogue`
          : 'Awaiting catalogue coverage',
        chips: formations.slice(0, 3),
        state: 'upcoming'
      },
      {
        index: 5,
        title: 'Target position',
        note: `${this.transitionReadiness()}% compatibility`,
        chips: [this.targetLabel()].filter(Boolean),
        state: 'upcoming'
      }
    ];
  });

  /* --------------------------------------------------- graph preview */

  protected readonly preview = computed<GraphPreview | null>(() => {
    const graph = this.graph();
    const context = this.context();
    if (!graph || !graph.nodes.length || !context?.profileIri) return null;

    const byId = new Map(graph.nodes.map(n => [n.id, n]));
    const focusNode = byId.get(context.profileIri);
    if (!focusNode) return null;

    const connected = new Map<string, CareerGraphNode>();
    for (const edge of graph.edges) {
      const otherId = edge.from === focusNode.id ? edge.to : edge.to === focusNode.id ? edge.from : null;
      if (otherId && byId.has(otherId)) connected.set(otherId, byId.get(otherId)!);
    }

    const picked = [...connected.values()].slice(0, 8);
    const centreX = PREVIEW_WIDTH / 2;
    const centreY = PREVIEW_HEIGHT / 2;
    const radius = 65;

    return {
      focus: { node: focusNode, x: centreX, y: centreY },
      nodes: picked.map((node, i) => {
        const angle = (i / picked.length) * Math.PI * 2;
        return {
          node,
          x: centreX + radius * Math.cos(angle),
          y: centreY + radius * Math.sin(angle)
        };
      }),
      total: connected.size
    };
  });

  protected readonly previewColors = PREVIEW_COLORS;
  protected readonly previewRadius = PREVIEW_RADIUS;
  protected readonly previewWidth = PREVIEW_WIDTH;
  protected readonly previewHeight = PREVIEW_HEIGHT;

  /** Three-segment priority meter scale shared by every gap row. */
  protected readonly prioritySegments = [1, 2, 3];

  /* ---------------------------------------------------------- helpers */

  protected onPreselected(selection: CareerSelection): void {
    this.load(selection);
  }

  protected onSubmitted(selection: CareerSelection): void {
    this.load(selection);
  }

  protected displayName(id: string): string {
    return humanizeIdentifier(id);
  }

  protected phaseLabel(phase: string): string {
    return phaseLabel(phase as any);
  }

  protected getFormat(type: string): string {
    return courseFormat(type);
  }

  protected priorityLabel(priority: SkillPriority): string {
    return SKILL_PRIORITY_META[priority]?.label ?? 'No action';
  }

  protected priorityClass(priority: SkillPriority): string {
    return `sp-badge sp-badge-${SKILL_PRIORITY_META[priority]?.tone ?? 'neutral'}`;
  }

  /** Filled segments of the priority meter — encodes the real ontology priority. */
  protected priorityLevel(priority: SkillPriority): number {
    switch (priority) {
      case 'haute': return 3;
      case 'moyenne': return 2;
      case 'basse': return 1;
      default: return 0;
    }
  }

  protected recommendedFormationFor(skill: SkillComparison): string {
    const first = skill.formations_recommandees[0];
    return first ? this.displayName(first) : '';
  }

  protected remainingText(): string {
    if (!this.roadmapDurationAvailable() || this.roadmapHours() === null) return 'Not available';
    return `${this.roadmapHours()}h`;
  }

  protected openInGraph(label: string): void {
    this.router.navigate(['/knowledge-graph'], { queryParams: { q: humanizeIdentifier(label) } });
  }

  private load(selection: CareerSelection): void {
    this.loading.set(true);
    this.error.set('');
    forkJoin({
      gap: this.career.getSkillGap(selection.profil, selection.metier),
      path: this.career.getLearningPath(selection.profil, selection.metier),
      graph: this.career.getGraph(),
      jobs: this.career.getAccessibleJobs(selection.profil)
    }).pipe(
      finalize(() => this.loading.set(false)),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: ({ gap, path, graph, jobs }) => {
        this.gap.set(gap);
        this.path.set(path);
        this.graph.set(graph);
        this.accessibleJobs.set(jobs);
      },
      error: err => this.error.set(apiErrorMessage(err, 'Could not load professional dashboard data.'))
    });
  }
}
