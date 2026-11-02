import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import {
  AccountProfile,
  AuthService,
  friendlyAuthError,
  profileNeedsOnboarding
} from '../auth/auth.service';
import { DashboardDataService, EntityListItem } from './dashboard-data.service';

interface ValidationErrors {
  fullName?: string;
  experience?: string;
  competencies?: string;
  targetOccupation?: string;
}

@Component({
  selector: 'app-profile-onboarding',
  standalone: true,
  imports: [FormsModule, RouterLink],
  templateUrl: './profile-onboarding.component.html',
  styleUrl: './profile-onboarding.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class ProfileOnboardingComponent {
  private readonly auth = inject(AuthService);
  private readonly data = inject(DashboardDataService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly account = signal<AccountProfile | null>(null);
  protected readonly loading = signal(true);
  protected readonly submitting = signal(false);
  protected readonly errorMessage = signal('');
  protected readonly role = signal<'STUDENT' | 'PROFESSIONAL'>('STUDENT');
  protected readonly stepIndex = signal(0);
  protected readonly fullName = signal('');
  protected readonly experience = signal('');
  protected readonly targetOccupation = signal('');
  protected readonly acquiredCompetences = signal<string[]>([]);
  protected readonly occupations = signal<EntityListItem[]>([]);
  protected readonly competences = signal<EntityListItem[]>([]);
  protected readonly validationErrors = signal<ValidationErrors>({});

  protected readonly steps = ['Profile details', 'Your skills', 'Career goal', 'Review'];

  ngOnInit(): void {
    const routeRole = this.route.snapshot.url[0]?.path === 'professional' ? 'PROFESSIONAL' : 'STUDENT';
    this.role.set(routeRole);

    this.data.getList('Metier').subscribe({
      next: occupations => this.occupations.set(occupations),
      error: () => this.errorMessage.set('Occupation data is unavailable right now.')
    });

    this.data.getList('Competence').subscribe({
      next: competences => this.competences.set(competences),
      error: () => this.errorMessage.set('Skill data is unavailable right now.')
    });

    this.auth.getProfile().pipe(finalize(() => this.loading.set(false))).subscribe({
      next: profile => {
        this.account.set(profile);
        this.role.set(profile.role === 'PROFESSIONAL' ? 'PROFESSIONAL' : 'STUDENT');
        this.fullName.set(profile.full_name || '');
        this.experience.set(profile.experience || '');
        this.targetOccupation.set(profile.profile?.relations?.['vise']?.[0]?.id ?? '');
        this.acquiredCompetences.set(
          (profile.profile?.relations?.['aAcquis'] ?? []).map(item => item.id)
        );

        if (!profileNeedsOnboarding(this.role(), profile)) {
          void this.router.navigateByUrl(`/${this.role().toLowerCase()}/dashboard`);
        }
      },
      error: (error: HttpErrorResponse) => this.errorMessage.set(
        friendlyAuthError(error, 'Your profile could not be loaded.')
      )
    });
  }

  protected stepTitle(): string {
    return this.role() === 'STUDENT' ? 'Student onboarding' : 'Professional onboarding';
  }

  protected stepDescription(): string {
    return this.role() === 'STUDENT'
      ? 'Build a profile that matches your academic goals and intended career.'
      : 'Capture your experience, skills, and next professional move.';
  }

  protected isSelectedCompetence(id: string): boolean {
    return this.acquiredCompetences().includes(id);
  }

  protected toggleCompetence(id: string, checked: boolean): void {
    const current = new Set(this.acquiredCompetences());
    if (checked) current.add(id); else current.delete(id);
    this.acquiredCompetences.set([...current]);
  }

  protected validateCurrentStep(step = this.stepIndex()): ValidationErrors {
    const errors: ValidationErrors = {};
    if (step === 0) {
      if (this.fullName().trim().length < 2) {
        errors.fullName = 'Please provide your full name.';
      }
      if (this.requiresExperience() && this.experience().trim().length < 2) {
        errors.experience = 'Please describe your professional background.';
      }
    }
    if (step === 1) {
      if (this.acquiredCompetences().length === 0) {
        errors.competencies = 'Select at least one skill to continue.';
      }
    }
    if (step === 2) {
      if (!this.targetOccupation().trim()) {
        errors.targetOccupation = 'Please choose your target profession.';
      }
    }
    if (step === 3) {
      if (this.fullName().trim().length < 2) {
        errors.fullName = 'Please provide your full name.';
      }
      if (this.requiresExperience() && this.experience().trim().length < 2) {
        errors.experience = 'Please describe your professional background before confirming.';
      }
      if (this.acquiredCompetences().length === 0) {
        errors.competencies = 'Select at least one skill before confirming your profile.';
      }
      if (!this.targetOccupation().trim()) {
        errors.targetOccupation = 'Please choose your target profession before confirming.';
      }
    }
    return errors;
  }

  /**
   * A professional profile is only considered complete once a background has
   * been captured — the same rule `profileCompletion`/`profileCompletionGuard`
   * enforce — so onboarding must validate it up-front instead of reporting a
   * successful save as unverified afterwards.
   */
  private requiresExperience(): boolean {
    return this.role() === 'PROFESSIONAL';
  }

  protected getStepValidationErrors(step = this.stepIndex()): ValidationErrors {
    return this.validateCurrentStep(step);
  }

  protected canContinue(): boolean {
    return Object.keys(this.validateCurrentStep()).length === 0;
  }

  protected nextStep(): void {
    const errors = this.validateCurrentStep();
    this.validationErrors.set(errors);
    if (Object.keys(errors).length > 0) {
      this.errorMessage.set('Please complete the missing required information before continuing.');
      this.stepIndex.set(this.stepIndex() === 0 && errors.fullName ? 0 : this.stepIndex());
      if (this.stepIndex() === 1 && errors.competencies) {
        this.stepIndex.set(1);
      }
      if (this.stepIndex() === 2 && errors.targetOccupation) {
        this.stepIndex.set(2);
      }
      return;
    }
    this.errorMessage.set('');
    this.stepIndex.update(current => Math.min(current + 1, this.steps.length - 1));
  }

  protected previousStep(): void {
    this.errorMessage.set('');
    this.validationErrors.set({});
    this.stepIndex.update(current => Math.max(current - 1, 0));
  }

  protected saveProfile(): void {
    if (this.submitting()) return;
    const errors = this.validateCurrentStep(3);
    this.validationErrors.set(errors);
    if (Object.keys(errors).length > 0) {
      this.errorMessage.set('Please review the required information before confirming your profile.');
      if (errors.fullName || errors.experience) this.stepIndex.set(0);
      else if (errors.competencies) this.stepIndex.set(1);
      else if (errors.targetOccupation) this.stepIndex.set(2);
      return;
    }

    this.submitting.set(true);
    this.errorMessage.set('');
    const completedTrainings = this.account()?.profile?.relations?.['aSuivi']?.map(item => item.id) ?? [];

    this.auth.saveProfile({
      full_name: this.fullName().trim(),
      experience: this.experience().trim(),
      target_occupation: this.targetOccupation(),
      acquired_competences: this.acquiredCompetences(),
      completed_trainings: completedTrainings
    }).pipe(finalize(() => this.submitting.set(false))).subscribe({
      next: () => {
        this.auth.getProfile().subscribe({
          next: profile => {
            this.account.set(profile);
            this.fullName.set(profile.full_name || '');
            this.experience.set(profile.experience || '');
            this.targetOccupation.set(profile.profile?.relations?.['vise']?.[0]?.id ?? '');
            this.acquiredCompetences.set(
              (profile.profile?.relations?.['aAcquis'] ?? []).map(item => item.id)
            );

            if (profileNeedsOnboarding(this.role(), profile)) {
              // The save responded successfully but the reloaded profile is still
              // incomplete: point the user at the field the backend actually missed
              // rather than silently declaring success.
              this.errorMessage.set('Your profile could not be verified as saved successfully. Please review the required information and try again.');
              const persistedName = (profile.full_name ?? '').trim();
              const persistedOccupation = profile.profile?.relations?.['vise']?.[0]?.id ?? '';
              const persistedCompetences = profile.profile?.relations?.['aAcquis'] ?? [];
              if (persistedName.length < 2) this.stepIndex.set(0);
              else if (this.requiresExperience() && (profile.experience ?? '').trim().length < 2) this.stepIndex.set(0);
              else if (persistedCompetences.length === 0) this.stepIndex.set(1);
              else if (!persistedOccupation) this.stepIndex.set(2);
              this.validationErrors.set(this.validateCurrentStep(this.stepIndex()));
              return;
            }

            void this.router.navigateByUrl(`/${this.role().toLowerCase()}/profile-success`);
          },
          error: (error: HttpErrorResponse) => this.errorMessage.set(
            friendlyAuthError(error, 'Your profile could not be confirmed. Please try again.')
          )
        });
      },
      error: (error: HttpErrorResponse) => this.errorMessage.set(
        friendlyAuthError(error, 'Your profile could not be saved. Please review the required information.')
      )
    });
  }

  protected selectedOccupationLabel(): string {
    const selectedId = this.targetOccupation();
    return this.occupations().find(item => item.id === selectedId)?.label ?? 'No occupation selected';
  }

  protected gotoDashboard(): void {
    void this.router.navigateByUrl(`/${this.role().toLowerCase()}/dashboard`);
  }
}
