import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  inject,
  signal,
  viewChild
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { EMPTY, Subject, catchError, finalize, switchMap, tap } from 'rxjs';

import { AuthService, friendlyAuthError } from '../../auth/auth.service';
import { apiErrorMessage } from '../../dashboard/dashboard-data.service';
import {
  CareerSelection,
  CareerSelectorComponent
} from '../../career/career-selector.component';
import { CourseCoverComponent } from '../../career/course-cover.component';
import { IconComponent } from '../../career/icon.component';
import {
  CareerService,
  LearningPathCandidate,
  OptimalLearningPathReport,
  LearningStep,
  RoadmapPhase,
  courseFormat,
  humanizeIdentifier,
  phaseLabel
} from '../../career/career.service';

interface PhaseGroup {
  phase: RoadmapPhase;
  label: string;
  steps: LearningStep[];
}

const PHASE_ORDER: RoadmapPhase[] = ['fondation', 'intermediaire', 'avance'];

/**
 * Ranked optimal learning path candidates.
 *
 * The backend ranks alternative coverage sets and prerequisite closures. The
 * selected sequence can be reordered without violating prerequisites. Progress is written back to the profile's
 * saved path through `/account/parcours/{id}/progress`, so it survives a
 * refresh and a new sign-in.
 */
@Component({
  selector: 'app-parcours-optimal',
  standalone: true,
  imports: [RouterLink, CareerSelectorComponent, CourseCoverComponent, IconComponent],
  templateUrl: './parcours-optimal.component.html',
  styleUrl: './parcours-optimal.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class ParcoursOptimalComponent {
  private readonly career = inject(CareerService);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly loadRequests = new Subject<CareerSelection>();

  private readonly rail = viewChild<ElementRef<HTMLDivElement>>('rail');

  protected readonly selection = signal<CareerSelection | null>(null);
  protected readonly loading = signal(false);
  protected readonly error = signal('');
  protected readonly report = signal<OptimalLearningPathReport | null>(null);
  protected readonly selectedCandidateId = signal('');
  protected readonly sequenceIds = signal<string[]>([]);
  protected readonly maxDurationHours = signal<number | null>(null);

  protected readonly savingPath = signal(false);
  protected readonly pathMessage = signal('');
  protected readonly pathError = signal('');
  protected readonly savingProgress = signal(false);
  protected readonly progressMessage = signal('');
  protected readonly progressError = signal('');
  protected readonly activePathId = signal<string | null>(null);

  constructor() {
    this.loadRequests
      .pipe(
        switchMap(selection => {
          this.selection.set(selection);
          this.loading.set(true);
          this.error.set('');
          this.report.set(null);
          this.selectedCandidateId.set('');
          this.sequenceIds.set([]);
          this.activePathId.set(null);
          this.pathMessage.set('');
          this.pathError.set('');
          this.progressMessage.set('');
          this.progressError.set('');

          return this.career
            .getOptimalLearningPath(
              selection.profil,
              selection.metier,
              this.maxDurationHours()
            )
            .pipe(
              tap(report => {
                this.report.set(report);
                const firstCandidate = report.candidates[0];
                this.selectedCandidateId.set(firstCandidate?.id ?? '');
                this.sequenceIds.set(firstCandidate?.training_ids ?? []);
              }),
              catchError(error => {
                this.report.set(null);
                this.error.set(
                  apiErrorMessage(
                    error,
                    'The learning path could not be built. Check that the backend and Fuseki are running, then try again.'
                  )
                );
                return EMPTY;
              }),
              finalize(() => this.loading.set(false))
            );
        }),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe();
  }

  /** Only students and professionals own an ontology profile that can store progress. */
  protected readonly isPersonal = computed(() => this.auth.currentUser()?.role !== 'ADMIN');

  protected readonly context = this.career.context;

  protected readonly occupationLabel = computed(() =>
    humanizeIdentifier(this.report()?.metier ?? '')
  );

  protected readonly selectedCandidate = computed(() => {
    const report = this.report();
    return report?.candidates.find(candidate => candidate.id === this.selectedCandidateId())
      ?? report?.candidates[0]
      ?? null;
  });

  protected readonly activeSteps = computed<LearningStep[]>(() => {
    const candidate = this.selectedCandidate();
    if (!candidate) return [];
    const byId = new Map(candidate.etapes.map(step => [step.formation, step]));
    const sequence = this.sequenceIds();
    const ordered = sequence.length
      ? sequence.map(id => byId.get(id)).filter((step): step is LearningStep => step !== undefined)
      : candidate.etapes;
    return ordered.map((step, index) => ({ ...step, ordre: index + 1 }));
  });

  protected readonly progression = computed(() => {
    const followed = new Set(this.context()?.followedTrainings ?? []);
    const recommended = this.activeSteps();
    const total = recommended.length;
    const terminees = recommended.filter(step => followed.has(step.formation)).length;
    return {
      total,
      terminees,
      pourcentage: total ? Math.round(terminees / total * 100) : 0
    };
  });

  /** Honest unavailable state: the ontology records no `aDureeHeures` values today. */
  protected readonly remainingTime = computed(() => {
    const duration = this.selectedCandidate()?.duration_hours;
    return duration === null || duration === undefined ? null : `${duration} h`;
  });

  protected readonly phaseGroups = computed<PhaseGroup[]>(() => {
    if (!this.report()) return [];
    return PHASE_ORDER.map(phase => ({
      phase,
      label: phaseLabel(phase),
      steps: this.activeSteps().filter(step => step.phase === phase)
    })).filter(group => group.steps.length > 0);
  });

  protected readonly completedSteps = computed<LearningStep[]>(
    () => this.report()?.etapes_terminees ?? []
  );

  /** Skills the catalogue cannot cover yet, ready for inline display. */
  protected readonly missingList = computed(() =>
    (this.report()?.competences_sans_formation ?? []).map(humanizeIdentifier).join(', ')
  );

  protected readonly inProgressList = computed(() =>
    (this.report()?.competences_en_cours ?? []).map(humanizeIdentifier).join(', ')
  );

  protected readonly uncoveredList = computed(() =>
    (this.selectedCandidate()?.uncovered_competencies ?? []).map(humanizeIdentifier).join(', ')
  );

  /**
   * Whether the selected candidate actually prescribes trainings. The generator
   * still emits an empty candidate when no catalogue training can cover the
   * remaining skills; that placeholder must not be rendered as a real path.
   */
  protected readonly hasNewRecommendations = computed(() => this.activeSteps().length > 0);

  /** Honest, specific message when no catalogue training can cover the gap. */
  protected readonly noTrainingMessage = computed(() => {
    const skills = (this.report()?.competences_sans_formation ?? []).map(humanizeIdentifier);
    if (skills.length) {
      return `No feasible training path is available for ${skills.join(', ')} because no catalogue training teaches ${skills.length === 1 ? 'this skill' : 'these skills'}.`;
    }
    return 'No prerequisite-valid catalogue training can cover the remaining skills.';
  });

  protected readonly prerequisiteBlockedList = computed(() =>
    (this.report()?.competences_bloquees_prerequis ?? []).map(humanizeIdentifier).join(', ')
  );

  /** The saved path that matches this exact generated roadmap, if the user saved it before. */
  private readonly matchedPath = computed(() => {
    const context = this.context();
    const report = this.report();
    if (!context || !report || this.activeSteps().length === 0) return null;
    const wanted = this.activeSteps().map(step => step.formation);
    return (
      context.savedPaths.find(path => {
        const ids = path.formations.map(formation => formation.id);
        return ids.length === wanted.length && ids.every((id, index) => id === wanted[index]);
      }) ?? null
    );
  });

  protected readonly effectivePathId = computed(
    () => this.activePathId() ?? this.matchedPath()?.id ?? null
  );

  private readonly savedPath = computed(() => {
    const context = this.context();
    const id = this.effectivePathId();
    if (!context || !id) return null;
    return context.savedPaths.find(path => path.id === id) ?? null;
  });

  protected readonly completedTrainings = computed<string[]>(() => {
    const path = this.savedPath();
    const context = this.context();
    if (!path || !context) return [];
    const followed = new Set(context.followedTrainings);
    return path.formations.filter(formation => followed.has(formation.id)).map(f => f.id);
  });

  protected readonly canTrackProgress = computed(
    () => this.isPersonal() && this.effectivePathId() !== null
  );

  protected onPreselected(selection: CareerSelection): void {
    this.load(selection);
  }

  protected onSubmitted(selection: CareerSelection): void {
    this.load(selection);
  }

  protected regenerate(): void {
    const selection = this.selection();
    if (selection) this.load(selection);
  }

  protected applyDurationConstraint(event: Event): void {
    const input = event.target as HTMLInputElement;
    const value = input.value.trim();
    const parsed = value === '' ? null : Number(value);
    if (parsed !== null && (!Number.isInteger(parsed) || parsed < 0)) {
      input.value = this.maxDurationHours() === null ? '' : String(this.maxDurationHours());
      return;
    }
    this.maxDurationHours.set(parsed);
    this.regenerate();
  }

  protected selectCandidate(candidate: LearningPathCandidate): void {
    this.selectedCandidateId.set(candidate.id);
    this.sequenceIds.set(candidate.training_ids);
    this.activePathId.set(null);
    this.pathMessage.set('');
    this.pathError.set('');
  }

  protected canMoveStep(trainingId: string, direction: -1 | 1): boolean {
    const steps = this.activeSteps();
    const index = steps.findIndex(step => step.formation === trainingId);
    const targetIndex = index + direction;
    if (index < 0 || targetIndex < 0 || targetIndex >= steps.length) return false;
    if (steps[index].phase !== steps[targetIndex].phase) return false;

    const sequence = steps.map(step => step.formation);
    [sequence[index], sequence[targetIndex]] = [sequence[targetIndex], sequence[index]];
    return this.hasValidPrerequisiteOrder(sequence);
  }

  protected moveStep(trainingId: string, direction: -1 | 1): void {
    if (!this.canMoveStep(trainingId, direction)) return;
    const sequence = this.activeSteps().map(step => step.formation);
    const index = sequence.indexOf(trainingId);
    [sequence[index], sequence[index + direction]] = [sequence[index + direction], sequence[index]];
    this.sequenceIds.set(sequence);
    this.activePathId.set(null);
    this.pathMessage.set('');
    this.pathError.set('');
  }

  protected isCompleted(step: LearningStep): boolean {
    return this.completedTrainings().includes(step.formation);
  }

  protected phaseName(phase: RoadmapPhase): string {
    return phaseLabel(phase);
  }

  protected courseName(value: string): string {
    return humanizeIdentifier(value);
  }

  protected skillsLabel(values: string[]): string {
    return values.map(humanizeIdentifier).join(', ');
  }

  protected format(step: LearningStep): string {
    return courseFormat(step.type);
  }

  protected duration(step: LearningStep): string {
    return step.duree_heures !== null && step.duree_heures !== undefined
      ? `${step.duree_heures} h`
      : 'Duration not recorded';
  }

  protected prerequisiteText(step: LearningStep): string {
    if (!step.prerequis.length) return 'No prerequisite';
    const satisfied = new Set(step.prerequis_satisfaits);
    return step.prerequis
      .map(name => `${humanizeIdentifier(name)}${satisfied.has(name) ? ' ✓' : ''}`)
      .join(' · ');
  }

  protected scrollRail(direction: -1 | 1): void {
    const element = this.rail()?.nativeElement;
    if (!element) return;
    const step = Math.max(240, element.clientWidth * 0.8);
    element.scrollBy({ left: direction * step, behavior: 'smooth' });
  }

  /** Creates the profile's saved path so individual trainings can be marked complete. */
  protected savePath(): void {
    if (!this.report() || this.savingPath()) return;
    const trainings = this.activeSteps().map(step => step.formation);
    if (trainings.length === 0) return;

    this.savingPath.set(true);
    this.pathMessage.set('');
    this.pathError.set('');
    this.auth
      .saveLearningPath(trainings)
      .pipe(
        finalize(() => this.savingPath.set(false)),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe({
        next: path => {
          this.activePathId.set(path.id);
          this.sequenceIds.set(path.formations);
          this.pathMessage.set('This learning path is now saved to your profile. You can mark trainings as completed.');
          this.career.loadContext(true).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({ error: () => undefined });
        },
        error: error =>
          this.pathError.set(friendlyAuthError(error, 'This learning path could not be saved to your profile.'))
      });
  }

  protected toggleStep(step: LearningStep): void {
    if (!this.isPersonal() || this.savingProgress()) return;
    const path = this.savedPath();
    if (!path) {
      this.progressError.set('Save this learning path to your profile before recording progress.');
      return;
    }

    const completed = new Set(this.completedTrainings());
    if (completed.has(step.formation)) completed.delete(step.formation);
    else completed.add(step.formation);

    this.savingProgress.set(true);
    this.progressError.set('');
    this.progressMessage.set('');

    this.auth
      .updateLearningProgress(path.id, [...completed])
      .pipe(
        switchMap(() => this.career.loadContext(true)),
        finalize(() => this.savingProgress.set(false)),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe({
        next: () => {
          this.progressMessage.set('Progress saved to your profile.');
          const selection = this.selection();
          if (selection) this.load(selection);
        },
        error: error =>
          this.progressError.set(friendlyAuthError(error, 'Your progress could not be saved.'))
      });
  }

  private load(selection: CareerSelection): void {
    this.loadRequests.next(selection);
  }

  private hasValidPrerequisiteOrder(sequence: string[]): boolean {
    const steps = new Map(this.activeSteps().map(step => [step.formation, step]));
    const completed = new Set(this.context()?.followedTrainings ?? []);
    for (const training of sequence) {
      const step = steps.get(training);
      if (!step || !step.prerequis.every(prerequisite => completed.has(prerequisite))) {
        return false;
      }
      completed.add(training);
    }
    return true;
  }
}
