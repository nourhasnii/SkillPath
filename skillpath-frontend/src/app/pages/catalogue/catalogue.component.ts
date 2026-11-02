import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import {
  Subject,
  catchError,
  debounceTime,
  distinctUntilChanged,
  finalize,
  forkJoin,
  map,
  of,
  switchMap,
  take,
} from 'rxjs';

import { AuthService } from '../../auth/auth.service';
import { humanizeIdentifier } from '../../career/career.service';
import {
  apiErrorMessage,
  CatalogueModule,
  CatalogueTraining,
  DashboardDataService
} from '../../dashboard/dashboard-data.service';

@Component({
  selector: 'app-catalogue',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './catalogue.component.html',
  styleUrl: './catalogue.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class CatalogueComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly data = inject(DashboardDataService);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly searchChanges = new Subject<string>();
  private readonly searchTerm = signal('');
  private toastTimeout?: number;

  protected readonly trainings = signal<CatalogueTraining[]>([]);
  protected readonly modules = signal<CatalogueModule[]>([]);
  protected readonly selectedId = signal<string | null>(null);
  protected readonly selectedTraining = signal<CatalogueTraining | null>(null);
  protected readonly followedTrainings = signal<string[]>([]);
  protected readonly profileReady = signal(false);
  protected readonly typeFilter = signal<'all' | 'online' | 'onsite'>('all');
  protected readonly loading = signal(true);
  protected readonly detailLoading = signal(false);
  protected readonly profileLoading = signal(true);
  protected readonly savingFollow = signal(false);
  protected readonly error = signal('');
  protected readonly detailError = signal('');
  protected readonly actionError = signal('');
  protected readonly toast = signal('');
  protected readonly humanize = humanizeIdentifier;

  protected readonly filteredTrainings = computed(() => {
    const search = this.searchTerm().trim().toLocaleLowerCase();
    return this.trainings()
      .filter(training => {
        const type = this.trainingCategory(training);
        const matchesType = this.typeFilter() === 'all' || type === this.typeFilter();
        return matchesType && humanizeIdentifier(training.nom).toLocaleLowerCase().includes(search);
      })
      .sort((left, right) =>
        humanizeIdentifier(left.nom).localeCompare(humanizeIdentifier(right.nom))
      );
  });

  protected readonly alreadyFollowed = computed(() => {
    const id = this.selectedId();
    return id !== null && this.followedTrainings().includes(id);
  });

  protected readonly canFollow = computed(() =>
    this.selectedId() !== null
    && this.profileReady()
    && this.profileLoading() === false
    && this.savingFollow() === false
    && this.alreadyFollowed() === false
  );

  ngOnInit(): void {
    this.destroyRef.onDestroy(() => {
      if (this.toastTimeout !== undefined) window.clearTimeout(this.toastTimeout);
    });

    this.data.getPublicCatalogue().pipe(
      takeUntilDestroyed(this.destroyRef),
      finalize(() => this.loading.set(false))
    ).subscribe({
      next: items => this.trainings.set(items),
      error: (error: HttpErrorResponse) => this.error.set(
        apiErrorMessage(error, 'The training catalogue could not be loaded.')
      )
    });

    this.searchChanges.pipe(
      debounceTime(300),
      distinctUntilChanged(),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(value => this.searchTerm.set(value));

    this.auth.getProfile().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: profile => {
        this.followedTrainings.set(
          profile.profile?.relations['aSuivi']?.map(training => training.id) ?? []
        );
        this.profileReady.set(true);
        this.profileLoading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.actionError.set(apiErrorMessage(error, 'Your followed trainings could not be loaded.'));
        this.profileLoading.set(false);
      }
    });

    this.route.paramMap.pipe(
      map(params => params.get('id')),
      distinctUntilChanged(),
      switchMap(id => {
        this.selectedId.set(id);
        this.selectedTraining.set(null);
        this.modules.set([]);
        this.detailError.set('');
        this.actionError.set('');
        if (!id) return of(null);

        this.detailLoading.set(true);
        return this.data.getPublicTraining(id).pipe(
          switchMap(training => {
            const moduleRequests = (training.modules ?? []).map(module =>
              this.data.getPublicModule(module.id)
            );
            return (moduleRequests.length ? forkJoin(moduleRequests) : of([])).pipe(
              map(modules => ({ training, modules }))
            );
          }),
          catchError((error: HttpErrorResponse) => {
            this.detailError.set(apiErrorMessage(error, 'Training details could not be loaded.'));
            return of(null);
          }),
          finalize(() => this.detailLoading.set(false))
        );
      }),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(result => {
      if (!result) return;
      this.selectedTraining.set(result.training);
      this.modules.set(result.modules);
    });
  }

  protected onSearchInput(event: Event): void {
    if (event.target instanceof HTMLInputElement) {
      this.searchChanges.next(event.target.value);
    }
  }

  protected setTypeFilter(value: string): void {
    if (value === 'all' || value === 'online' || value === 'onsite') {
      this.typeFilter.set(value);
    }
  }

  protected onTypeChange(event: Event): void {
    if (event.target instanceof HTMLSelectElement) {
      this.setTypeFilter(event.target.value);
    }
  }

  protected trainingType(training: CatalogueTraining): string {
    switch (training.type) {
      case 'FormationEnLigne': return 'Online';
      case 'FormationPresentielle': return 'On-site';
      default: return 'Training';
    }
  }

  protected trainingCategory(training: CatalogueTraining): 'online' | 'onsite' | 'other' {
    if (training.type === 'FormationEnLigne') return 'online';
    if (training.type === 'FormationPresentielle') return 'onsite';
    return 'other';
  }

  protected followTraining(): void {
    const profileId = this.auth.currentUser()?.profile_iri;
    const trainingId = this.selectedId();
    if (!profileId || !trainingId || !this.canFollow()) return;

    this.savingFollow.set(true);
    this.actionError.set('');
    this.toast.set('');
    const followed = [...new Set([...this.followedTrainings(), trainingId])];
    this.data.followProfileTrainings(profileId, followed).pipe(
      take(1),
      finalize(() => this.savingFollow.set(false))
    ).subscribe({
      next: result => {
        this.followedTrainings.set(result.formations_suivies);
        this.toast.set('Training marked as followed.');
        if (this.toastTimeout !== undefined) window.clearTimeout(this.toastTimeout);
        this.toastTimeout = window.setTimeout(() => this.toast.set(''), 3500);
      },
      error: (error: HttpErrorResponse) => this.actionError.set(
        apiErrorMessage(error, 'The training could not be marked as followed.')
      )
    });
  }
}
