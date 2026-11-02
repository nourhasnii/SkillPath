import { ChangeDetectionStrategy, Component, OnInit, inject, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { finalize, forkJoin, of, switchMap } from 'rxjs';

import { AuthService } from '../auth/auth.service';
import { apiErrorMessage, DashboardDataService } from '../dashboard/dashboard-data.service';
import { CareerService, humanizeIdentifier } from './career.service';
import { IconComponent } from './icon.component';

export interface CareerSelection {
  profil: string;
  metier: string;
}

interface SelectOption {
  id: string;
  label: string;
}

/**
 * Profile / occupation picker shared by the career features.
 *
 * Students and professionals are locked to their own ontology profile — the
 * backend rejects any other profile for a non-admin account — while
 * administrators can analyse any profile in the repository.
 */
@Component({
  selector: 'sp-career-selector',
  standalone: true,
  imports: [FormsModule, IconComponent],
  template: `
    <form class="selector" (ngSubmit)="submit()">
      <div class="selector-fields">
        <label class="field">
          <span class="field-label">Profile</span>
          <select name="profil" [(ngModel)]="profil" required [disabled]="!isAdmin() || loading() || !!error()">
            <option value="" disabled>Select a profile</option>
            @for (profile of profiles(); track profile.id) {
              <option [value]="profile.id">{{ profile.label }}</option>
            }
          </select>
        </label>

        <label class="field">
          <span class="field-label">Target occupation</span>
          <select name="metier" [(ngModel)]="metier" required [disabled]="loading() || !!error()">
            <option value="" disabled>Select an occupation</option>
            @for (occupation of occupations(); track occupation.id) {
              <option [value]="occupation.id">{{ occupation.label }}</option>
            }
          </select>
        </label>
      </div>

      <button
        type="submit"
        class="sp-btn sp-btn-primary selector-submit"
        [disabled]="loading() || !!error() || !profil || !metier">
        <sp-icon name="sparkle" [size]="16" />
        {{ loading() ? 'Loading…' : submitLabel() }}
      </button>
    </form>

    @if (error()) {
      <p class="sp-alert sp-alert-error selector-message" role="alert">{{ error() }}</p>
    } @else if (!loading() && (!profiles().length || !occupations().length)) {
      <p class="sp-alert sp-alert-info selector-message" role="status">
        No profile or occupation is available yet, so there is nothing to analyse.
      </p>
    }
  `,
  styles: [`
    :host { display: block; }

    .selector {
      display: flex;
      flex-wrap: wrap;
      align-items: flex-end;
      gap: 14px;
      padding: 18px 20px;
      border: 1px solid var(--sp-line);
      border-radius: var(--sp-radius-lg);
      background: var(--sp-surface);
      box-shadow: var(--sp-shadow-sm);
    }

    .selector-fields { display: flex; flex: 1 1 380px; flex-wrap: wrap; gap: 14px; }

    .field { display: grid; flex: 1 1 190px; gap: 7px; min-width: 0; }

    .field-label {
      color: var(--sp-ink-700);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .5px;
      text-transform: uppercase;
    }

    .field select {
      width: 100%;
      height: 42px;
      padding: 0 12px;
      border: 1px solid var(--sp-line-strong);
      border-radius: var(--sp-radius-sm);
      outline: none;
      color: var(--sp-ink-900);
      background: var(--sp-surface);
      font: inherit;
      font-size: 13px;
      transition: border-color .15s ease, box-shadow .15s ease;
    }

    .field select:focus { border-color: var(--sp-violet-400); box-shadow: var(--sp-focus); }
    .field select:disabled { color: var(--sp-ink-500); background: var(--sp-surface-muted); }

    .selector-submit { flex: 0 0 auto; min-height: 42px; }
    .selector-message { margin: 12px 0 0; }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class CareerSelectorComponent implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly data = inject(DashboardDataService);
  private readonly career = inject(CareerService);

  /** Emitted once when a usable profile/occupation pair is already known. */
  readonly preselected = output<CareerSelection>();
  /** Emitted when the user explicitly asks for a (re)computation. */
  readonly submitted = output<CareerSelection>();

  readonly profiles = signal<SelectOption[]>([]);
  readonly occupations = signal<SelectOption[]>([]);
  readonly loading = signal(true);
  readonly error = signal('');
  readonly isAdmin = signal(false);
  readonly submitLabel = signal('Show analysis');

  protected profil = '';
  protected metier = '';

  ngOnInit(): void {
    const user = this.auth.currentUser();
    const isAdmin = user?.role === 'ADMIN';
    this.isAdmin.set(isAdmin);

    this.career
      .loadContext()
      .pipe(
        switchMap(context =>
          forkJoin({
            context: of(context),
            profiles: isAdmin
              ? this.data.getList('ProfilUtilisateur')
              : of(
                  context.profileIri
                    ? [{
                        id: context.profileIri,
                        // Show the profile name (never the profil_<hash> identifier).
                        label: context.profileName || user?.full_name || context.profileIri
                      }]
                    : []
                ),
            occupations: this.data.getList('Metier')
          })
        ),
        finalize(() => this.loading.set(false))
      )
      .subscribe({
        next: ({ context, profiles, occupations }) => {
          const profileOptions = profiles.map(profile => ({
            id: profile.id,
            label: isAdmin ? humanizeIdentifier(profile.label) : profile.label
          }));
          const occupationOptions = occupations.map(occupation => ({
            id: occupation.id,
            label: humanizeIdentifier(occupation.label)
          }));
          this.profiles.set(profileOptions);
          this.occupations.set(occupationOptions);

          const defaultProfil = isAdmin ? profileOptions[0]?.id ?? '' : context.profileIri ?? '';
          const defaultMetier = context.targetOccupation?.id ?? '';
          if (profileOptions.some(option => option.id === defaultProfil)) this.profil = defaultProfil;
          if (occupationOptions.some(option => option.id === defaultMetier)) this.metier = defaultMetier;

          if (this.profil && this.metier) {
            this.preselected.emit({ profil: this.profil, metier: this.metier });
          }
        },
        error: error =>
          this.error.set(
            apiErrorMessage(error, 'Profiles and occupations could not be loaded from SkillPath.')
          )
      });
  }

  protected submit(): void {
    if (!this.profil || !this.metier) return;
    this.submitted.emit({ profil: this.profil, metier: this.metier });
  }
}
