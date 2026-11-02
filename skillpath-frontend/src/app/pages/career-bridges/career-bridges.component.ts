import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { catchError, finalize, map, of, switchMap } from 'rxjs';

import { apiErrorMessage } from '../../dashboard/dashboard-data.service';
import { CareerBridge, CareerService } from '../../career/career.service';

@Component({
  selector: 'app-career-bridges',
  standalone: true,
  templateUrl: './career-bridges.component.html',
  styleUrl: './career-bridges.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class CareerBridgesComponent implements OnInit {
  private readonly career = inject(CareerService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly context = this.career.context;
  protected readonly bridges = signal<CareerBridge[]>([]);
  protected readonly loading = signal(true);
  protected readonly error = signal('');
  protected readonly actionError = signal('');
  protected readonly settingTarget = signal(false);

  ngOnInit(): void {
    this.career.loadContext().pipe(
      switchMap(() => this.career.getCareerBridges()),
      finalize(() => this.loading.set(false)),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: bridges => this.bridges.set(bridges),
      error: error => this.error.set(
        apiErrorMessage(error, 'Career bridges could not be loaded. Check that the backend and Fuseki are running.')
      )
    });
  }

  protected setBridgeAsTarget(bridge: CareerBridge): void {
    const profileId = this.context()?.profileIri;
    if (!profileId || this.settingTarget()) return;

    this.settingTarget.set(true);
    this.actionError.set('');
    this.career.setTargetOccupation(profileId, bridge.occupationId).pipe(
      switchMap(() => this.career.loadContext(true).pipe(
        map(() => ({ refreshed: true as const })),
        catchError(error => of({ refreshed: false as const, error }))
      )),
      finalize(() => this.settingTarget.set(false)),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe({
      next: result => {
        if (!result.refreshed) {
          this.actionError.set(
            apiErrorMessage(result.error, 'The target was updated, but dashboard data could not be refreshed.')
          );
          return;
        }
        this.router.navigate(['/career']);
      },
      error: error => this.actionError.set(apiErrorMessage(error, 'The target occupation could not be updated.'))
    });
  }
}
