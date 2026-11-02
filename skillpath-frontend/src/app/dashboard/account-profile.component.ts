import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { finalize, forkJoin } from 'rxjs';

import { AuthService, friendlyAuthError } from '../auth/auth.service';
import { CareerService, courseFormat } from '../career/career.service';
import { IconComponent } from '../career/icon.component';
import {
  DashboardDataService,
  EntityListItem,
  apiErrorMessage,
  displayEntityName
} from './dashboard-data.service';
import {
  ProfilePatch,
  SkillCandidate,
  SmartProfileService,
  SmartProfileView
} from './smart-profile.service';

/** Human wording for the `completeness.missing` keys returned by the API. */
const COMPLETENESS_BLOCKS: { key: string; label: string; suggestion: string }[] = [
  { key: 'target_occupation', label: 'Target occupation', suggestion: 'Add a target occupation' },
  { key: 'skills', label: 'At least one skill', suggestion: 'Add at least one skill' },
  { key: 'trainings', label: 'At least one followed training', suggestion: 'Add at least one followed training' },
  {
    key: 'parcours_or_evaluation',
    label: 'A learning path or an evaluation',
    suggestion: 'Save a learning path or record an evaluation'
  }
];

const SEMANTIC_ACTIONS = [
  {
    label: 'Skill Gap Analysis',
    description: 'Compare your profile with your target occupation',
    icon: 'target',
    path: '/skill-gap'
  },
  {
    label: 'Optimal path',
    description: 'Rank the trainings that close your gaps',
    icon: 'path',
    path: '/parcours-optimal'
  },
  {
    label: 'Knowledge Graph',
    description: 'See how your profile connects to skills and roles',
    icon: 'graph',
    path: '/knowledge-graph'
  },
  {
    label: 'Semantic Assistant',
    description: 'Ask a question in plain language',
    icon: 'sparkle',
    path: '/semantic-assistant'
  }
];

/**
 * Smart Profile / Career Profile.
 *
 * Everything displayed here comes from the live ontology through
 * `GET /api/profile/{id}`: the target occupation (`vise`), the acquired skills
 * (`aAcquis`), the followed trainings (`aSuivi`), the saved path
 * (`suitParcours`) and the evaluations (`aPasseEvaluation`). Edits go through
 * `PATCH /api/profile/{id}` and free-text skill entry through the local
 * spaCy + rapidfuzz matcher `POST /api/profile/resolve-skills`.
 */
@Component({
  selector: 'app-account-profile',
  standalone: true,
  imports: [FormsModule, RouterLink, IconComponent],
  templateUrl: './account-profile.component.html',
  styleUrl: './account-profile.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class AccountProfileComponent implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly data = inject(DashboardDataService);
  private readonly profiles = inject(SmartProfileService);
  private readonly career = inject(CareerService);

  protected readonly user = this.auth.currentUser;
  protected readonly semanticActions = SEMANTIC_ACTIONS;

  protected readonly profile = signal<SmartProfileView | null>(null);
  protected readonly occupations = signal<EntityListItem[]>([]);
  protected readonly competences = signal<EntityListItem[]>([]);
  protected readonly trainings = signal<EntityListItem[]>([]);

  protected readonly selectedOccupation = signal('');
  protected readonly selectedSkill = signal('');
  protected readonly selectedTraining = signal('');
  protected readonly freeText = signal('');
  protected readonly candidates = signal<SkillCandidate[]>([]);
  protected readonly resolvedText = signal('');

  protected readonly loading = signal(true);
  protected readonly resolving = signal(false);
  protected readonly busy = signal('');
  protected readonly errorMessage = signal('');
  protected readonly successMessage = signal('');

  protected readonly displayName = computed(
    () => this.profile()?.label || this.user()?.full_name || 'SkillPath profile'
  );

  protected readonly initials = computed(() => {
    const name = this.displayName().trim();
    if (!name) return 'SP';
    return name
      .split(/\s+/)
      .slice(0, 2)
      .map(part => part.charAt(0).toUpperCase())
      .join('');
  });

  protected readonly roleLabel = computed(() => {
    const types = this.profile()?.types ?? [];
    if (types.includes('ProfilProfessionnel') || this.user()?.role === 'PROFESSIONAL') {
      return 'Professional';
    }
    if (types.includes('ProfilEtudiant') || this.user()?.role === 'STUDENT') {
      return 'Student';
    }
    return 'Administrator';
  });

  protected readonly skills = computed(() => this.profile()?.skills_acquired ?? []);
  protected readonly trainingsFollowed = computed(() => this.profile()?.trainings_followed ?? []);
  protected readonly evaluations = computed(() => this.profile()?.evaluations ?? []);
  protected readonly parcours = computed(() => this.profile()?.parcours ?? null);
  protected readonly completeness = computed(() => this.profile()?.completeness?.score ?? 0);

  protected readonly completenessSteps = computed(() => {
    const missing = new Set(this.profile()?.completeness?.missing ?? []);
    return COMPLETENESS_BLOCKS.map(block => ({
      key: block.key,
      label: block.label,
      done: !missing.has(block.key)
    }));
  });

  protected readonly suggestions = computed(() => {
    const missing = new Set(this.profile()?.completeness?.missing ?? []);
    return COMPLETENESS_BLOCKS
      .filter(block => missing.has(block.key))
      .map(block => block.suggestion);
  });

  private readonly ownedSkills = computed(
    () => new Set(this.skills().map(skill => skill.id))
  );

  private readonly ownedTrainings = computed(
    () => new Set(this.trainingsFollowed().map(training => training.id))
  );

  /** Ontology competencies the profile does not hold yet. */
  protected readonly availableSkills = computed(() =>
    this.competences().filter(competence => !this.ownedSkills().has(competence.id))
  );

  protected readonly availableTrainings = computed(() =>
    this.trainings().filter(training => !this.ownedTrainings().has(training.id))
  );

  /** Candidates still absent from `aAcquis` (already accepted ones disappear). */
  protected readonly pendingCandidates = computed(() =>
    this.candidates().filter(candidate => !this.ownedSkills().has(candidate.iri))
  );

  ngOnInit(): void {
    const profileId = this.user()?.profile_iri;
    if (!profileId) {
      this.loading.set(false);
      this.errorMessage.set('No SkillPath profile is linked to this account.');
      return;
    }
    forkJoin({
      view: this.profiles.getProfile(profileId),
      occupations: this.data.getList('Metier'),
      competences: this.data.getList('Competence'),
      trainings: this.data.getList('Formation', '', true)
    }).pipe(finalize(() => this.loading.set(false))).subscribe({
      next: result => {
        this.applyView(result.view);
        this.occupations.set(result.occupations);
        this.competences.set(result.competences);
        this.trainings.set(result.trainings);
      },
      error: (error: HttpErrorResponse) => this.errorMessage.set(
        friendlyAuthError(error, 'Your career profile could not be loaded.')
      )
    });
  }

  protected displayLabel(value: string): string {
    return displayEntityName(value);
  }

  /** Ontology-derived format of a followed training (`FormationEnLigne`, …). */
  protected trainingType(trainingId: string): string {
    const training = this.trainings().find(item => item.id === trainingId);
    return courseFormat(training?.class);
  }

  protected saveOccupation(): void {
    const target = this.selectedOccupation();
    this.patch(
      { target_occupation: target || null },
      target ? 'Target occupation updated.' : 'Target occupation cleared.',
      'occupation'
    );
  }

  protected addSelectedSkill(): void {
    const skillId = this.selectedSkill();
    if (!skillId) return;
    this.patch(
      { skills_add: [skillId] },
      'Skill added to your profile.',
      'skills',
      () => this.selectedSkill.set('')
    );
  }

  protected removeSkill(skillId: string): void {
    this.patch({ skills_remove: [skillId] }, 'Skill removed from your profile.', `remove-skill-${skillId}`);
  }

  protected confirmCandidate(candidate: SkillCandidate): void {
    this.patch(
      { skills_add: [candidate.iri] },
      `“${candidate.label}” added to your profile.`,
      `candidate-${candidate.iri}`
    );
  }

  protected addSelectedTraining(): void {
    const trainingId = this.selectedTraining();
    if (!trainingId) return;
    this.patch(
      { trainings_add: [trainingId] },
      'Training added to your profile.',
      'trainings',
      () => this.selectedTraining.set('')
    );
  }

  protected removeTraining(trainingId: string): void {
    this.patch(
      { trainings_remove: [trainingId] },
      'Training removed from your profile.',
      `remove-training-${trainingId}`
    );
  }

  /** Free text → ontology competencies, via the local spaCy + rapidfuzz matcher. */
  protected resolveSkills(): void {
    const text = this.freeText().trim();
    if (!text || this.resolving()) return;
    this.resolving.set(true);
    this.errorMessage.set('');
    this.resolvedText.set('');
    this.profiles.resolveSkills(text)
      .pipe(finalize(() => this.resolving.set(false)))
      .subscribe({
        next: result => {
          this.candidates.set(result.candidates);
          this.resolvedText.set(result.text);
        },
        error: (error: HttpErrorResponse) => this.errorMessage.set(
          apiErrorMessage(error, 'The text could not be matched against the skill list.')
        )
      });
  }

  private patch(
    payload: ProfilePatch,
    message: string,
    action: string,
    onSuccess?: () => void
  ): void {
    const profileId = this.user()?.profile_iri;
    if (!profileId || this.busy()) return;
    this.busy.set(action);
    this.errorMessage.set('');
    this.successMessage.set('');
    this.profiles.patchProfile(profileId, payload)
      .pipe(finalize(() => this.busy.set('')))
      .subscribe({
        next: view => {
          this.applyView(view);
          this.successMessage.set(message);
          // Every feature page reads the cached context: refresh it so the
          // analysis pages immediately see the updated ontology relations.
          this.career.loadContext(true).subscribe({ error: () => undefined });
          onSuccess?.();
        },
        error: (error: HttpErrorResponse) => this.errorMessage.set(
          friendlyAuthError(error, 'The update could not be saved.')
        )
      });
  }

  private applyView(view: SmartProfileView): void {
    this.profile.set(view);
    this.selectedOccupation.set(view.target_occupation?.id ?? '');
  }
}
