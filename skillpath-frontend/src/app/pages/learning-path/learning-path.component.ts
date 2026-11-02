import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize, switchMap } from 'rxjs';

import { AuthService, friendlyAuthError } from '../../auth/auth.service';
import { CareerSelection, CareerSelectorComponent } from '../../career/career-selector.component';
import { CareerService, LearningPathReport, LearningStep, humanizeIdentifier } from '../../career/career.service';
import { apiErrorMessage } from '../../dashboard/dashboard-data.service';
import { IconComponent } from '../../career/icon.component';

@Component({
  selector: 'app-learning-path',
  standalone: true,
  imports: [CareerSelectorComponent, IconComponent],
  templateUrl: './learning-path.component.html',
  styleUrl: './learning-path.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class LearningPathComponent {
  private readonly career = inject(CareerService);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly loading = signal(false);
  protected readonly error = signal('');
  protected readonly report = signal<LearningPathReport | null>(null);
  protected readonly selection = signal<CareerSelection | null>(null);
  protected readonly sequence = signal<string[]>([]);
  protected readonly saving = signal(false);
  protected readonly savingProgress = signal(false);
  protected readonly actionError = signal('');
  protected readonly actionMessage = signal('');
  protected readonly savedPathId = signal<string | null>(null);
  protected readonly context = this.career.context;

  protected readonly steps = computed(() => {
    const report = this.report();
    if (!report) return [];
    const byId = new Map(report.etapes.map(step => [step.formation, step]));
    const ids = this.sequence();
    const ordered = ids.length ? ids : report.etapes.map(step => step.formation);
    return ordered
      .map(id => byId.get(id))
      .filter((step): step is LearningStep => step !== undefined)
      .map((step, index) => ({ ...step, ordre: index + 1 }));
  });

  protected readonly missingSkills = computed(() =>
    (this.report()?.competences_non_couvertes ?? []).map(humanizeIdentifier).join(', ')
  );

  protected readonly effectivePathId = computed(() => {
    if (this.savedPathId()) return this.savedPathId();
    const desired = this.steps().map(step => step.formation);
    return this.context()?.savedPaths.find(path => {
      const saved = path.formations.map(training => training.id);
      return saved.length === desired.length && saved.every((id, index) => id === desired[index]);
    })?.id ?? null;
  });

  protected readonly completed = computed(() => new Set(this.context()?.followedTrainings ?? []));

  protected onPreselected(selection: CareerSelection): void {
    this.load(selection);
  }

  protected onSubmitted(selection: CareerSelection): void {
    this.load(selection);
  }

  protected refresh(): void {
    const selection = this.selection();
    if (selection) this.load(selection);
  }

  protected courseName(value: string): string {
    return humanizeIdentifier(value);
  }

  protected skillsLabel(values: string[]): string {
    return values.map(humanizeIdentifier).join(', ');
  }

  protected isCompleted(step: LearningStep): boolean {
    return this.completed().has(step.formation);
  }

  protected canMove(index: number, direction: -1 | 1): boolean {
    const sequence = this.steps().map(step => step.formation);
    const target = index + direction;
    if (target < 0 || target >= sequence.length) return false;
    [sequence[index], sequence[target]] = [sequence[target], sequence[index]];
    return this.validOrder(sequence);
  }

  protected move(index: number, direction: -1 | 1): void {
    if (!this.canMove(index, direction)) return;
    const sequence = this.steps().map(step => step.formation);
    [sequence[index], sequence[index + direction]] = [sequence[index + direction], sequence[index]];
    this.sequence.set(sequence);
    this.savedPathId.set(null);
    this.actionMessage.set('');
  }

  protected save(): void {
    const trainings = this.steps().map(step => step.formation);
    if (!trainings.length || this.saving()) return;
    this.saving.set(true);
    this.actionError.set('');
    this.actionMessage.set('');
    this.auth.saveLearningPath(trainings).pipe(
      switchMap(path => {
        this.savedPathId.set(path.id);
        this.sequence.set(path.formations);
        return this.career.loadContext(true).pipe(switchMap(() => [path]));
      }),
      finalize(() => this.saving.set(false)),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: () => this.actionMessage.set('This learning path is saved to your profile.'),
      error: error => this.actionError.set(friendlyAuthError(error, 'The path could not be saved.'))
    });
  }

  protected toggleProgress(step: LearningStep): void {
    const pathId = this.effectivePathId();
    if (!pathId || this.savingProgress()) return;
    const nextCompleted = new Set(this.completed());
    if (nextCompleted.has(step.formation)) nextCompleted.delete(step.formation);
    else nextCompleted.add(step.formation);
    this.savingProgress.set(true);
    this.actionError.set('');
    this.actionMessage.set('');
    this.auth.updateLearningProgress(pathId, [...nextCompleted]).pipe(
      switchMap(() => this.career.loadContext(true)),
      finalize(() => this.savingProgress.set(false)),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: () => this.actionMessage.set('Progress saved to your profile.'),
      error: error => this.actionError.set(friendlyAuthError(error, 'Progress could not be saved.'))
    });
  }

  private load(selection: CareerSelection): void {
    this.selection.set(selection);
    this.loading.set(true);
    this.error.set('');
    this.actionError.set('');
    this.actionMessage.set('');
    this.career.getLearningPath(selection.profil, selection.metier).pipe(
      finalize(() => this.loading.set(false)),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: report => {
        this.report.set(report);
        this.sequence.set(report.etapes.map(step => step.formation));
        this.savedPathId.set(null);
      },
      error: error => {
        this.report.set(null);
        this.error.set(apiErrorMessage(error, 'The personalised learning path could not be loaded.'));
      }
    });
  }

  private validOrder(sequence: string[]): boolean {
    const steps = new Map((this.report()?.etapes ?? []).map(step => [step.formation, step]));
    const completed = new Set(this.context()?.followedTrainings ?? []);
    for (const training of sequence) {
      const step = steps.get(training);
      if (!step || !step.prerequis.every(prerequisite => completed.has(prerequisite))) return false;
      completed.add(training);
    }
    return true;
  }
}
