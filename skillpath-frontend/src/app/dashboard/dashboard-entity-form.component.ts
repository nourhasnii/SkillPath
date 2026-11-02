import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import { finalize } from 'rxjs/operators';
import { of } from 'rxjs';
import {
  apiErrorMessage,
  configForSlug,
  DashboardDataService,
  EntityConfig,
  EntityDetail,
  EntityListItem
} from './dashboard-data.service';

@Component({
  selector: 'app-dashboard-entity-form',
  standalone: true,
  imports: [FormsModule, RouterLink],
  templateUrl: './dashboard-entity-form.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DashboardEntityFormComponent implements OnInit {
  private static readonly TRAINING_CLASSES = [
    'Formation',
    'FormationEnLigne',
    'FormationPresentielle'
  ];

  private static readonly EVALUATION_CLASSES = [
    'EvaluationTechnique',
    'EvaluationComportementale'
  ];

  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly data = inject(DashboardDataService);

  protected config?: EntityConfig;
  protected readonly identifier = signal('');
  protected readonly entityClass = signal('');
  protected readonly availableClasses = signal<string[]>([]);
  protected readonly isEdit = signal(false);
  protected readonly loading = signal(true);
  protected readonly formReady = signal(false);
  protected readonly saving = signal(false);
  protected readonly errorMessage = signal('');
  protected readonly propertyValues: Record<string, string> = {};
  protected readonly selectedRelations: Record<string, string[]> = {};
  protected readonly relationOptions: Record<string, EntityListItem[]> = {};

  ngOnInit(): void {
    this.config = configForSlug(this.route.snapshot.paramMap.get('type'));
    const id = this.route.snapshot.paramMap.get('id');
    this.isEdit.set(!!id);
    if (!this.config) {
      this.errorMessage.set('This entity type is not available.');
      this.loading.set(false);
      return;
    }

    this.initializeValues();
    if (id) {
      this.identifier.set(id);
      this.data.getDetail(this.config.kind, id).subscribe({
        next: detail => {
          this.populateForm(detail);
          this.loadRelationOptions();
        },
        error: (error: HttpErrorResponse) => {
          this.errorMessage.set(apiErrorMessage(error, 'The entity could not be loaded.'));
          this.loading.set(false);
        }
      });
    } else {
      this.loadRelationOptions();
    }
  }

  protected setIdentifier(value: string): void {
    this.identifier.set(value);
  }

  protected displayIdentifier(value: string): string {
    return value.replace(/^_?(?:comp|form|met|profil|mod|parc|eval)_/, '');
  }

  // Disambiguate options that share the same display name by appending the identifier.
  protected optionLabel(options: EntityListItem[], option: EntityListItem): string {
    const name = this.displayIdentifier(option.label);
    const duplicates = options.filter(item => this.displayIdentifier(item.label) === name);
    return duplicates.length > 1 ? `${name} (${this.displayIdentifier(option.id)})` : name;
  }

  protected setClass(value: string): void {
    this.entityClass.set(value);
  }

  protected setProperty(key: string, value: string): void {
    this.propertyValues[key] = value;
  }

  protected toggleRelation(key: string, id: string, checked: boolean): void {
    const selected = this.selectedRelations[key] ?? [];
    this.selectedRelations[key] = checked
      ? [...new Set([...selected, id])]
      : selected.filter(item => item !== id);
  }

  protected onRelationChange(key: string, id: string, event: Event): void {
    if (event.target instanceof HTMLInputElement) {
      this.toggleRelation(key, id, event.target.checked);
    }
  }

  protected isSelected(key: string, id: string): boolean {
    return this.selectedRelations[key]?.includes(id) ?? false;
  }

  protected singleSelection(key: string): string {
    return this.selectedRelations[key]?.[0] ?? '';
  }

  protected setSingleRelation(key: string, id: string): void {
    this.selectedRelations[key] = id ? [id] : [];
  }

  protected save(): void {
    const config = this.config;
    const id = this.identifier().trim();
    if (!config || !this.formReady() || this.saving()) return;
    if (!this.isEdit() && !/^[A-Za-z_][A-Za-z0-9_-]*$/.test(id)) {
      this.errorMessage.set('Use letters, numbers, underscores or hyphens; the identifier must start with a letter or underscore.');
      return;
    }
    const missing = config.properties.find(
      property => property.required && !this.propertyValues[property.key]?.trim()
    );
    if (missing) {
      this.errorMessage.set(`${missing.label} is required.`);
      return;
    }

    const properties = Object.fromEntries(
      config.properties.map(property => {
        const value = this.propertyValues[property.key]?.trim() ?? '';
        return [property.key, value ? [value] : []];
      })
    );
    const relations = Object.fromEntries(
      config.relations.map(relation => [relation.key, this.selectedRelations[relation.key] ?? []])
    );
    this.errorMessage.set('');
    this.saving.set(true);
    const request = this.isEdit()
      ? this.data.update(config.kind, this.identifier(), {
          class: this.entityClass(),
          properties,
          relations
        })
      : this.data.create(config.kind, {
          id,
          class: this.entityClass() || config.kind,
          properties,
          relations
        });
    request.pipe(finalize(() => this.saving.set(false))).subscribe({
      next: () => void this.router.navigate(['/dashboard', config.slug]),
      error: (error: HttpErrorResponse) => {
        this.errorMessage.set(apiErrorMessage(error, 'The record could not be saved.'));
      }
    });
  }

  protected cancelLink(): string[] {
    return ['/dashboard', this.config?.slug ?? ''];
  }

  protected identityProperties(): EntityConfig['properties'] {
    return this.config?.properties.filter(property => property.key === 'aNom') ?? [];
  }

  protected classificationProperties(): EntityConfig['properties'] {
    return this.config?.properties.filter(property => property.key !== 'aNom') ?? [];
  }

  private initializeValues(): void {
    const config = this.config;
    if (!config) return;
    this.entityClass.set(config.kind);
    for (const property of config.properties) this.propertyValues[property.key] = '';
    for (const relation of config.relations) this.selectedRelations[relation.key] = [];
  }

  private populateForm(detail: EntityDetail): void {
    this.entityClass.set(detail.class);
    for (const [key, values] of Object.entries(detail.properties)) {
      if (key in this.propertyValues) this.propertyValues[key] = this.formatProperty(key, values[0] ?? '');
    }
    for (const [key, values] of Object.entries(detail.relations)) {
      if (key in this.selectedRelations) this.selectedRelations[key] = values.map(value => value.id);
    }
  }

  private formatProperty(key: string, value: string): string {
    if (key === 'aDateDebut') return value.replace(/Z$/, '').slice(0, 16);
    return value;
  }

  private loadRelationOptions(): void {
    const config = this.config;
    if (!config) {
      this.loading.set(false);
      return;
    }
    forkJoin({
      classes: this.data.getClasses(config.kind),
      relations: config.relations.length
        ? forkJoin(config.relations.map(relation => this.data.getList(relation.target)))
        : of([] as EntityListItem[][])
    }).pipe(
      finalize(() => this.loading.set(false))
    ).subscribe({
      next: result => {
        const classes = config.kind === 'Formation'
          ? result.classes.filter(className =>
              DashboardEntityFormComponent.TRAINING_CLASSES.includes(className)
            )
          : config.kind === 'Evaluation'
            ? result.classes.filter(className =>
                DashboardEntityFormComponent.EVALUATION_CLASSES.includes(className)
              )
            : result.classes;
        this.availableClasses.set(classes);
        config.relations.forEach((relation, index) => {
          this.relationOptions[relation.key] = result.relations[index]
            .filter(option => !(config.kind === 'Formation'
              && relation.key === 'aPourPrerequis'
              && option.id === this.identifier()))
            .sort((a, b) => this.displayIdentifier(a.label).localeCompare(this.displayIdentifier(b.label)));
        });
        if (classes.length && !classes.includes(this.entityClass())) {
          this.entityClass.set(classes[0]);
        }
        this.formReady.set(true);
      },
      error: (error: HttpErrorResponse) => {
        this.errorMessage.set(apiErrorMessage(error, 'Relation choices could not be loaded.'));
      }
    });
  }
}
