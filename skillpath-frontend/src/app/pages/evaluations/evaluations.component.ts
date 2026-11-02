import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';
import { catchError, finalize, forkJoin, of } from 'rxjs';

import { apiErrorMessage } from '../../dashboard/dashboard-data.service';
import { ChartTone, RingChartComponent } from '../../career/charts/ring-chart.component';
import { IconComponent } from '../../career/icon.component';
import {
  CareerService,
  EvaluationResult,
  EvaluationSummary,
  SkillGapReport,
  humanizeIdentifier,
  levelLabel,
  levelTone
} from '../../career/career.service';

/**
 * "My Evaluations" — automatic, non-supervised assessment of the connected
 * student/professional against the competencies its target occupation requires.
 *
 * The score is the share of required competencies the profile has actually
 * acquired (same rule as the skill-gap analysis). Nothing here is a per-skill
 * proficiency claim: it is a career-readiness percentage plus an overall level.
 */
@Component({
  selector: 'app-evaluations',
  standalone: true,
  imports: [RouterLink, RingChartComponent, IconComponent],
  templateUrl: './evaluations.component.html',
  styleUrl: './evaluations.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class EvaluationsComponent implements OnInit {
  private readonly career = inject(CareerService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly loading = signal(true);
  protected readonly evaluating = signal(false);
  protected readonly error = signal('');
  protected readonly notice = signal('');
  protected readonly result = signal<EvaluationResult | null>(null);
  private readonly history = signal<EvaluationSummary[]>([]);
  private readonly gap = signal<SkillGapReport | null>(null);

  protected readonly context = this.career.context;
  protected readonly targetOccupation = computed(() => this.context()?.targetOccupation ?? null);

  protected readonly occupationName = computed(() => {
    const result = this.result();
    if (result) return result.occupationName;
    const target = this.targetOccupation();
    return target ? humanizeIdentifier(target.label) : '';
  });

  /** Only the evaluation of the CURRENT target occupation is ever displayed. */
  protected readonly currentEvaluation = computed<EvaluationSummary | null>(() => {
    const target = this.targetOccupation();
    if (!target) return null;
    return this.history().find(item => item.occupation === target.id) ?? null;
  });

  protected readonly diagnostic = computed(
    () => this.result()?.diagnostic ?? this.currentEvaluation()?.diagnostic ?? null
  );

  protected readonly evaluated = computed(
    () => this.result() !== null || this.currentEvaluation() !== null
  );

  /** The target occupation declares no required competency: no score is computable. */
  protected readonly noRequired = computed(() => Boolean(this.result()?.message));

  protected readonly showAssessment = computed(() => this.evaluated() && !this.noRequired());

  protected readonly score = computed<number | null>(() => {
    const result = this.result();
    if (result && !result.message) return result.score;
    return this.currentEvaluation()?.score ?? this.gap()?.match_score ?? null;
  });

  protected readonly scoreTone = computed<ChartTone>(() => {
    const score = this.score() ?? 0;
    if (score >= 80) return 'emerald';
    if (score >= 50) return 'violet';
    if (score >= 20) return 'amber';
    return 'rose';
  });

  protected readonly masteredCount = computed(() =>
    this.result()?.masteredCount ?? this.gap()?.competences_acquises.length ?? 0
  );

  protected readonly missingCount = computed(() =>
    this.result()?.missingCount ?? this.gap()?.competences_manquantes.length ?? 0
  );

  // Level always comes from the ontology: freshly returned, or the stored profile level.
  protected readonly level = computed(() =>
    this.result()?.level ?? this.context()?.level ?? null
  );

  protected readonly requiredLevel = computed(() =>
    this.result()?.requiredLevel ?? this.context()?.requiredLevel ?? null
  );

  protected readonly levelText = computed(() => levelLabel(this.level()));
  protected readonly requiredLevelText = computed(() => levelLabel(this.requiredLevel()));
  protected readonly levelBadgeClass = computed(() => `sp-badge sp-badge-${levelTone(this.level())}`);
  protected readonly requiredLevelBadgeClass = computed(
    () => `sp-badge sp-badge-${levelTone(this.requiredLevel())}`
  );

  protected readonly evaluationDate = computed(
    () => this.result()?.date ?? this.currentEvaluation()?.date ?? null
  );

  ngOnInit(): void {
    this.career.loadContext().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: context =>
        this.load(context.profileIri, context.targetOccupation?.id ?? null),
      error: (error: HttpErrorResponse) => {
        this.loading.set(false);
        this.error.set(apiErrorMessage(error, 'Your profile could not be loaded.'));
      }
    });
  }

  protected evaluate(): void {
    if (this.evaluating()) return;
    this.evaluating.set(true);
    this.error.set('');
    this.notice.set('');
    this.career.generateEvaluation().pipe(
      finalize(() => this.evaluating.set(false)),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: result => {
        this.result.set(result);
        if (result.message) {
          this.notice.set(result.message);
          return;
        }
        this.refreshAfterEvaluation();
      },
      error: (error: HttpErrorResponse) => {
        this.error.set(apiErrorMessage(error, 'The evaluation could not be generated.'));
      }
    });
  }

  protected formatDate(value: string | null): string {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
  }

  private load(profileIri: string | null, occupationId: string | null): void {
    const evaluations = this.career.getEvaluations().pipe(catchError(() => of([])));
    if (!profileIri || !occupationId) {
      evaluations.pipe(
        finalize(() => this.loading.set(false)),
        takeUntilDestroyed(this.destroyRef)
      ).subscribe({ next: list => this.history.set(list) });
      return;
    }

    forkJoin({
      evaluations,
      gap: this.career.getSkillGap(profileIri, occupationId).pipe(catchError(() => of(null)))
    }).pipe(
      finalize(() => this.loading.set(false)),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: ({ evaluations: list, gap }) => {
        this.history.set(list);
        this.gap.set(gap);
      },
      error: (error: HttpErrorResponse) => {
        this.error.set(apiErrorMessage(error, 'Your evaluations could not be loaded.'));
      }
    });
  }

  private refreshAfterEvaluation(): void {
    this.career.getEvaluations().pipe(
      catchError(() => of([] as EvaluationSummary[])),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({ next: list => this.history.set(list) });
    this.career.loadContext(true).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      error: () => undefined
    });
  }
}
