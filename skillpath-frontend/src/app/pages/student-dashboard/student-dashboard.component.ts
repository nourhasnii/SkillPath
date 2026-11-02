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
import {
  DistributionChartComponent,
  DistributionSegment
} from '../../career/charts/distribution-chart.component';
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
  SkillStatus,
  SKILL_STATUS_META,
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

interface RoadmapEntry {
  step: LearningStep;
  state: 'done' | 'current' | 'upcoming';
}

interface SkillGroup {
  key: SkillStatus;
  label: string;
  description: string;
  items: SkillComparison[];
}

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

const SKILL_GROUP_ORDER: SkillStatus[] = ['manquante', 'en_cours', 'acquise'];

@Component({
  selector: 'app-student-dashboard',
  standalone: true,
  imports: [
    RouterLink,
    CareerSelectorComponent,
    RecommendedForYouComponent,
    RingChartComponent,
    DistributionChartComponent,
    IconComponent,
    CourseCoverComponent,
    LevelCompareComponent
  ],
  templateUrl: './student-dashboard.component.html',
  styleUrl: './student-dashboard.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class StudentDashboardComponent {
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

  /* ---------------------------------------------------------------- hero */

  protected readonly firstName = computed(
    () => this.auth.currentUser()?.full_name?.trim().split(/\s+/)[0] ?? ''
  );

  protected readonly fullName = computed(() => this.auth.currentUser()?.full_name?.trim() ?? '');

  protected readonly initials = computed(() => {
    const name = this.fullName();
    if (!name) return 'SP';
    return name
      .split(/\s+/)
      .slice(0, 2)
      .map(part => part.charAt(0).toUpperCase())
      .join('');
  });

  /** Time-of-day greeting — the name always comes from the authenticated account. */
  protected readonly greeting = computed(() => {
    const hour = new Date().getHours();
    const part = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
    const name = this.firstName();
    return name ? `${part}, ${name} 👋` : `${part} 👋`;
  });

  protected readonly targetLabel = computed(() =>
    humanizeIdentifier(this.gap()?.metier ?? this.context()?.targetOccupation?.label ?? '')
  );

  /* ------------------------------------------------------- readiness level */

  protected readonly level = computed(() => this.context()?.level ?? null);
  protected readonly requiredLevel = computed(() => this.context()?.requiredLevel ?? null);
  protected readonly levelText = computed(() => levelLabel(this.level()));
  protected readonly levelBadgeClass = computed(() => `sp-badge sp-badge-${levelTone(this.level())}`);

  /* ------------------------------------------------------- readiness card */

  protected readonly matchTone = computed<ChartTone>(() => {
    const score = this.gap()?.match_score ?? 0;
    if (score >= 80) return 'emerald';
    if (score >= 50) return 'violet';
    if (score >= 20) return 'amber';
    return 'rose';
  });

  protected readonly badgeClass = computed(() => {
    switch (this.matchTone()) {
      case 'emerald': return 'sp-badge sp-badge-success';
      case 'violet': return 'sp-badge sp-badge-violet';
      case 'amber': return 'sp-badge sp-badge-warning';
      default: return 'sp-badge sp-badge-danger';
    }
  });

  protected readonly readinessLabel = computed(() => {
    const score = this.gap()?.match_score ?? 0;
    if (score >= 80) return 'Ready';
    if (score >= 50) return 'Nearly ready';
    if (score >= 20) return 'Developing';
    return 'Getting started';
  });

  protected readonly matchDescription = computed(() => {
    const score = this.gap()?.match_score ?? 0;
    if (score >= 80) return 'You already cover most of what this role requires. Keep the momentum going.';
    if (score >= 50) return 'You are on the right track — a few targeted skills will close the distance.';
    if (score >= 20) return 'You have a solid base to build on. Follow your roadmap to grow into this role.';
    return 'Start building the foundations for this career, one step at a time.';
  });

  protected readonly requiredCount = computed(() => this.gap()?.competences_requises.length ?? 0);
  protected readonly masteredCount = computed(() => this.gap()?.competences_acquises.length ?? 0);
  protected readonly missingCount = computed(() => this.gap()?.competences_manquantes.length ?? 0);
  protected readonly inProgressCount = computed(() => this.gap()?.competences_en_cours.length ?? 0);

  protected readonly distribution = computed<DistributionSegment[]>(() => {
    const report = this.gap();
    if (!report) return [];
    return [
      { key: 'acquise', label: 'Mastered', value: report.competences_acquises.length, color: '#5B4FE9' },
      { key: 'en_cours', label: 'In progress', value: report.competences_en_cours.length, color: '#F59E0B' },
      { key: 'manquante', label: 'Missing', value: report.competences_manquantes.length, color: '#E11D48' }
    ].filter(segment => segment.value > 0);
  });

  /* ------------------------------------------------------ skills section */

  protected readonly skillGroups = computed<SkillGroup[]>(() => {
    const report = this.gap();
    if (!report) return [];
    const byStatus = new Map<SkillStatus, SkillComparison[]>();
    for (const skill of report.competences) {
      const bucket = byStatus.get(skill.statut) ?? [];
      bucket.push(skill);
      byStatus.set(skill.statut, bucket);
    }
    return SKILL_GROUP_ORDER.map(key => ({
      key,
      label: SKILL_STATUS_META[key].label,
      description: SKILL_STATUS_META[key].description,
      items: byStatus.get(key) ?? []
    })).filter(group => group.items.length > 0);
  });

  protected readonly hasSkills = computed(
    () => this.skillGroups().reduce((total, group) => total + group.items.length, 0) > 0
  );

  /* --------------------------------------------------- continue learning */

  protected readonly upcomingCourses = computed(() =>
    (this.path()?.etapes ?? [])
      .filter(step => step.statut === 'a_suivre')
      .slice(0, 3)
  );

  protected readonly completedCount = computed(() => this.path()?.progression.terminees ?? 0);
  protected readonly totalCount = computed(() => this.path()?.progression.total ?? 0);
  protected readonly progressPercent = computed(() => this.path()?.progression.pourcentage ?? 0);
  protected readonly hoursRemaining = computed(() => this.path()?.progression.heures_restantes ?? null);
  protected readonly durationAvailable = computed(() => this.path()?.progression.duree_disponible ?? false);

  /* ----------------------------------------------------------- roadmap */

  protected readonly roadmap = computed<RoadmapEntry[]>(() => {
    const steps = this.path()?.etapes ?? [];
    let currentAssigned = false;
    return steps.map(step => {
      if (step.statut === 'terminee') return { step, state: 'done' as const };
      if (!currentAssigned) {
        currentAssigned = true;
        return { step, state: 'current' as const };
      }
      return { step, state: 'upcoming' as const };
    });
  });

  /* ------------------------------------------------------ career paths */

  protected readonly preview = computed<GraphPreview | null>(() => {
    const graph = this.graph();
    const context = this.context();
    if (!graph || !graph.nodes.length || !context?.profileIri) return null;

    const byId = new Map(graph.nodes.map(node => [node.id, node]));
    const focusNode = byId.get(context.profileIri);
    if (!focusNode) return null;

    const connected = new Map<string, CareerGraphNode>();
    for (const edge of graph.edges) {
      const otherId = edge.from === focusNode.id ? edge.to : edge.to === focusNode.id ? edge.from : null;
      if (otherId && byId.has(otherId)) connected.set(otherId, byId.get(otherId)!);
    }

    const picked = [...connected.values()].slice(0, 6);
    const centreX = PREVIEW_WIDTH / 2;
    const centreY = PREVIEW_HEIGHT / 2;
    const radius = 60;

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

  protected skillStatusLabel(status: SkillStatus): string {
    return SKILL_STATUS_META[status].label;
  }

  /** Readable prerequisite list — always derived from the real step data. */
  protected prereqText(step: LearningStep): string {
    if (!step.prerequis.length) return '';
    return step.prerequis.map(id => humanizeIdentifier(id)).join(', ');
  }

  protected coveredLabel(step: LearningStep): string {
    const count = step.competences_couvertes.length;
    if (!count) return '';
    return count === 1 ? 'Covers 1 skill' : `Covers ${count} skills`;
  }

  protected remainingText(): string {
    if (!this.durationAvailable() || this.hoursRemaining() === null) return 'Not available';
    return `${this.hoursRemaining()}h`;
  }

  protected remainingCount(): number {
    return Math.max(this.totalCount() - this.completedCount(), 0);
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
      error: err => this.error.set(apiErrorMessage(err, 'Could not load student dashboard data.'))
    });
  }
}
