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
import { ChartTone, RingChartComponent } from '../../career/charts/ring-chart.component';
import { IconComponent } from '../../career/icon.component';
import {
  CareerGraph,
  CareerGraphNode,
  CareerService,
  LearningPathReport,
  LearningStep,
  SKILL_PRIORITY_META,
  SkillComparison,
  SkillGapReport,
  humanizeIdentifier,
  phaseLabel
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
  hidden: number;
}

/** Same palette and geometry vocabulary as the full knowledge graph page. */
const PREVIEW_COLORS: Record<NodeType, string> = {
  profile: '#5B4FE9',
  skill: '#10B981',
  job: '#2563EB',
  training: '#F59E0B'
};

const PREVIEW_RADIUS: Record<NodeType, number> = {
  profile: 13,
  skill: 7,
  job: 10,
  training: 9
};

const PRIORITY_ORDER: Record<string, number> = { haute: 0, moyenne: 1, basse: 2, aucune: 3 };

const PREVIEW_WIDTH = 320;
const PREVIEW_HEIGHT = 208;

/**
 * Career overview.
 *
 * Personalised entry point into the workspace: it reads the signed-in user's
 * name, ontology profile and the three real analysis endpoints, then surfaces
 * the readiness score, the most urgent gaps, the next training to take and a
 * compact preview of the knowledge graph. Nothing here is invented — every
 * figure either comes from the API or is omitted.
 */
@Component({
  selector: 'app-career-dashboard',
  standalone: true,
  imports: [RouterLink, CareerSelectorComponent, RingChartComponent, IconComponent],
  templateUrl: './career-dashboard.component.html',
  styleUrl: './career-dashboard.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class CareerDashboardComponent {
  private readonly auth = inject(AuthService);
  private readonly career = inject(CareerService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly loading = signal(false);
  protected readonly error = signal('');
  protected readonly gap = signal<SkillGapReport | null>(null);
  protected readonly path = signal<LearningPathReport | null>(null);
  private readonly graph = signal<CareerGraph | null>(null);

  protected readonly previewColors = PREVIEW_COLORS;
  protected readonly previewRadius = PREVIEW_RADIUS;
  protected readonly previewWidth = PREVIEW_WIDTH;
  protected readonly previewHeight = PREVIEW_HEIGHT;

  protected readonly context = this.career.context;

  protected readonly today = new Intl.DateTimeFormat('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long'
  }).format(new Date());

  protected readonly greeting = computed(() => {
    const hour = new Date().getHours();
    const part = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
    const firstName = this.auth.currentUser()?.full_name?.trim().split(/\s+/)[0];
    return firstName ? `${part}, ${firstName}` : part;
  });

  protected readonly occupationLabel = computed(() =>
    humanizeIdentifier(this.gap()?.metier ?? '')
  );

  /** Deterministic readiness banding over the real match score. */
  protected readonly readiness = computed<{ label: string; tone: ChartTone } | null>(() => {
    const report = this.gap();
    if (!report) return null;
    const score = report.match_score;
    if (score >= 85) return { label: 'Ready', tone: 'emerald' };
    if (score >= 60) return { label: 'Nearly ready', tone: 'violet' };
    if (score >= 35) return { label: 'Developing', tone: 'amber' };
    return { label: 'Getting started', tone: 'rose' };
  });

  protected readonly readinessLabel = computed(() => {
    const report = this.gap();
    const band = this.readiness();
    if (!report || !band) return '';
    return `Career readiness for ${this.occupationLabel()}: ${report.match_score}% — ${band.label}.`;
  });

  /** Missing skills ordered by the priority the backend actually assigned. */
  protected readonly topMissing = computed<SkillComparison[]>(() =>
    (this.gap()?.competences ?? [])
      .filter(skill => skill.statut === 'manquante')
      .sort(
        (a, b) =>
          (PRIORITY_ORDER[a.priorite] ?? 9) - (PRIORITY_ORDER[b.priorite] ?? 9) ||
          a.label.localeCompare(b.label)
      )
      .slice(0, 5)
  );

  protected readonly missingTotal = computed(() => this.gap()?.competences_manquantes.length ?? 0);

  /** The first training of the generated path that is not recorded as completed. */
  protected readonly nextActivity = computed<LearningStep | null>(
    () => this.path()?.etapes.find(step => step.statut !== 'terminee') ?? null
  );

  protected readonly pathPreview = computed<LearningStep[]>(
    () => this.path()?.etapes.slice(0, 4) ?? []
  );

  /** Compact radial layout of the profile's real neighbours in the ontology. */
  protected readonly preview = computed<GraphPreview | null>(() => {
    const graph = this.graph();
    const context = this.context();
    if (!graph || !graph.nodes.length) return null;

    const byId = new Map(graph.nodes.map(node => [node.id, node]));
    const focusId =
      context?.profileIri && byId.has(context.profileIri)
        ? context.profileIri
        : context?.targetOccupation && byId.has(context.targetOccupation.id)
          ? context.targetOccupation.id
          : null;
    if (!focusId) return null;

    const missing = new Set(this.gap()?.competences_manquantes ?? []);
    const managed = new Map<string, CareerGraphNode>();
    for (const edge of graph.edges) {
      const otherId = edge.from === focusId ? edge.to : edge.to === focusId ? edge.from : null;
      if (!otherId || managed.has(otherId)) continue;
      const other = byId.get(otherId);
      if (other) managed.set(otherId, other);
    }
    if (!managed.size) return null;

    const rank = (node: CareerGraphNode): number => {
      if (node.type === 'skill') return missing.has(node.id) ? 0 : 1;
      if (node.type === 'training') return 2;
      if (node.type === 'job') return 3;
      return 4;
    };
    const picked = [...managed.values()]
      .sort((a, b) => rank(a) - rank(b) || a.label.localeCompare(b.label))
      .slice(0, 7);

    const centreX = PREVIEW_WIDTH / 2;
    const centreY = PREVIEW_HEIGHT / 2;
    const ringRadius = 74;
    const nodes = picked.map((node, index) => {
      const angle = (index / picked.length) * Math.PI * 2 - Math.PI / 2;
      return {
        node,
        x: centreX + ringRadius * Math.cos(angle),
        y: centreY + ringRadius * Math.sin(angle)
      };
    });

    return {
      focus: { node: byId.get(focusId)!, x: centreX, y: centreY },
      nodes,
      total: managed.size,
      hidden: Math.max(0, managed.size - picked.length)
    };
  });

  protected onPreselected(selection: CareerSelection): void {
    this.load(selection);
  }

  protected onSubmitted(selection: CareerSelection): void {
    this.load(selection);
  }

  protected displayName(value: string): string {
    return humanizeIdentifier(value);
  }

  protected phaseName(phase: LearningStep['phase']): string {
    return phaseLabel(phase);
  }

  protected priorityLabel(skill: SkillComparison): string {
    return SKILL_PRIORITY_META[skill.priorite].label;
  }

  protected priorityTone(skill: SkillComparison): string {
    return `sp-badge-${SKILL_PRIORITY_META[skill.priorite].tone}`;
  }

  protected actionLabel(skill: SkillComparison): string {
    if (!skill.formations_recommandees.length) {
      return 'No training in the catalogue covers this skill yet.';
    }
    return skill.formations_recommandees.map(humanizeIdentifier).join(' · ');
  }

  protected courseName(step: LearningStep): string {
    return humanizeIdentifier(step.label || step.formation);
  }

  protected covers(step: LearningStep): string {
    return step.competences_couvertes.map(humanizeIdentifier).join(', ');
  }

  /** Opens the full knowledge graph focused on the clicked entity. */
  protected openInGraph(label: string): void {
    this.router.navigate(['/knowledge-graph'], { queryParams: { q: humanizeIdentifier(label) } });
  }

  private load(selection: CareerSelection): void {
    this.loading.set(true);
    this.error.set('');
    forkJoin({
      gap: this.career.getSkillGap(selection.profil, selection.metier),
      path: this.career.getLearningPath(selection.profil, selection.metier),
      graph: this.career.getGraph()
    })
      .pipe(
        finalize(() => this.loading.set(false)),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe({
        next: ({ gap, path, graph }) => {
          this.gap.set(gap);
          this.path.set(path);
          this.graph.set(graph);
        },
        error: error => {
          this.gap.set(null);
          this.path.set(null);
          this.graph.set(null);
          this.error.set(
            apiErrorMessage(
              error,
              'Your career overview could not be built. Check that the backend and Fuseki are running, then try again.'
            )
          );
        }
      });
  }
}
