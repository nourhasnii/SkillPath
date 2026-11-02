import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive } from '@angular/router';
import { finalize } from 'rxjs';
import {
  AccountProfile,
  AuthService,
  ProfileRelatedEntity,
  friendlyAuthError,
  profileCompletion,
  profileNeedsOnboarding
} from '../auth/auth.service';

@Component({
  selector: 'app-role-dashboard',
  standalone: true,
  imports: [RouterLink, RouterLinkActive],
  templateUrl: './role-dashboard.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class RoleDashboardComponent implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly user = this.auth.currentUser;
  protected readonly accountProfile = signal<AccountProfile | null>(null);
  protected readonly loading = signal(true);
  protected readonly errorMessage = signal('');
  protected readonly loggingOut = signal(false);
  protected readonly progressUpdating = signal<Set<string>>(new Set());

  ngOnInit(): void {
    this.auth.getProfile().pipe(finalize(() => this.loading.set(false))).subscribe({
      next: profile => {
        this.accountProfile.set(profile);
        const role = this.user()?.role ?? profile.role;
        if (profileNeedsOnboarding(role, profile)) {
          const target = `/${role.toLowerCase()}/onboarding`;
          if (this.router.url !== target) {
            void this.router.navigateByUrl(target);
          }
        }
      },
      error: (error: HttpErrorResponse) => this.errorMessage.set(
        friendlyAuthError(error, 'Your profile could not be loaded.')
      )
    });
  }

  protected completionPercent(): number {
    return profileCompletion(this.accountProfile(), this.user()?.role ?? this.accountProfile()?.role);
  }

  protected isProfileIncomplete(): boolean {
    return profileNeedsOnboarding(this.user()?.role ?? this.accountProfile()?.role, this.accountProfile());
  }

  protected signOut(): void {
    if (this.loggingOut()) return;
    this.loggingOut.set(true);
    this.auth.logout().pipe(finalize(() => this.loggingOut.set(false))).subscribe({
      next: () => void this.router.navigateByUrl('/login'),
      error: (error: HttpErrorResponse) => this.errorMessage.set(
        friendlyAuthError(error, 'Sign out could not be completed. Please retry.')
      )
    });
  }

  protected completedCount(path: ProfileRelatedEntity): number {
    const completed = new Set(
      this.accountProfile()?.profile?.relations?.['aSuivi']?.map(item => item.id) ?? []
    );
    return (path.formations ?? []).filter(training => completed.has(training.id)).length;
  }

  protected progressPercent(path: ProfileRelatedEntity): number {
    const total = path.formations?.length ?? 0;
    return total ? Math.round(this.completedCount(path) / total * 100) : 0;
  }

  protected isTrainingComplete(trainingId: string): boolean {
    return this.accountProfile()?.profile?.relations?.['aSuivi']
      ?.some(training => training.id === trainingId) ?? false;
  }

  protected markTrainingComplete(path: ProfileRelatedEntity, training: ProfileRelatedEntity): void {
    if (this.isTrainingComplete(training.id) || this.progressUpdating().has(training.id)) return;
    this.errorMessage.set('');
    this.progressUpdating.update(current => new Set(current).add(training.id));
    const completed = new Set(
      this.accountProfile()?.profile?.relations?.['aSuivi']?.map(item => item.id) ?? []
    );
    completed.add(training.id);
    this.auth.updateLearningProgress(path.id, [...completed]).pipe(
      finalize(() => this.progressUpdating.update(current => {
        const next = new Set(current);
        next.delete(training.id);
        return next;
      }))
    ).subscribe({
      next: () => this.auth.getProfile().subscribe({
        next: profile => this.accountProfile.set(profile),
        error: (error: HttpErrorResponse) => this.errorMessage.set(
          friendlyAuthError(error, 'Progress was saved, but your profile could not be refreshed.')
        )
      }),
      error: (error: HttpErrorResponse) => this.errorMessage.set(
        friendlyAuthError(error, 'Progress could not be saved.')
      )
    });
  }
}
