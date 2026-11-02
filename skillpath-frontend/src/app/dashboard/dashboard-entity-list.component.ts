import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { forkJoin, of } from 'rxjs';
import { distinctUntilChanged, finalize, map, switchMap } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  apiErrorMessage,
  configForKind,
  configForSlug,
  DashboardDataService,
  displayEntityName,
  EntityConfig,
  EntityDetail,
  EntityListItem,
  RelatedEntity
} from './dashboard-data.service';

interface EntityRow {
  item: EntityListItem;
  detail: EntityDetail;
}

@Component({
  selector: 'app-dashboard-entity-list',
  standalone: true,
  imports: [FormsModule, RouterLink],
  templateUrl: './dashboard-entity-list.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DashboardEntityListComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly data = inject(DashboardDataService);
  private readonly destroyRef = inject(DestroyRef);

  protected config?: EntityConfig;
  protected readonly isReadOnly = signal(false);
  protected readonly loading = signal(true);
  protected readonly filterLoading = signal(false);
  protected readonly errorMessage = signal('');
  protected readonly rows = signal<EntityRow[]>([]);
  protected readonly search = signal('');
  protected readonly classFilter = signal('');
  protected readonly relationFilterKey = signal('');
  protected readonly relationFilterValue = signal('');
  protected readonly relationChoices = signal<EntityListItem[]>([]);
  protected readonly displayName = displayEntityName;
  protected readonly classOptions = computed(() => [
    ...new Set(this.rows().map(row => row.item.class).filter((value): value is string => !!value))
  ]);
  protected readonly filteredRows = computed(() => {
    const classValue = this.classFilter();
    const relationKey = this.relationFilterKey();
    const relationValue = this.relationFilterValue();
    return this.rows()
      .filter(row => !classValue || row.item.class === classValue)
      .filter(row => {
        if (!relationKey || !relationValue) return true;
        const relation = row.detail.relations[relationKey] as RelatedEntity[] | undefined;
        return relation?.some(item => item.id === relationValue) ?? false;
      })
      .sort((left, right) => left.item.label.localeCompare(right.item.label));
  });

  ngOnInit(): void {
    this.route.paramMap.pipe(
      map(params => params.get('type') ?? 'generated-paths'),
      distinctUntilChanged(),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(slug => this.setEntityType(slug));
  }

  private setEntityType(slug: string): void {
    this.isReadOnly.set(slug === 'generated-paths');
    this.config = slug === 'generated-paths' ? configForKind('Parcours') : configForSlug(slug);
    this.classFilter.set('');
    this.relationFilterKey.set('');
    this.relationFilterValue.set('');
    this.relationChoices.set([]);
    this.rows.set([]);
    this.errorMessage.set('');
    if (!this.config) {
      this.errorMessage.set('This entity type is not available.');
      this.loading.set(false);
      return;
    }
    this.loading.set(true);
    this.load();
  }

  protected load(): void {
    const config = this.config;
    if (!config) return;
    this.loading.set(true);
    this.errorMessage.set('');
    this.data.getList(config.kind, this.search(), true).pipe(
      switchMap(items => items.length
        ? forkJoin(items.map(item => this.data.getDetail(config.kind, item.id))).pipe(
            switchMap(details => of(items.map((item, index) => ({ item, detail: details[index] }))))
          )
        : of([] as EntityRow[])
      ),
      finalize(() => this.loading.set(false))
    ).subscribe({
      next: rows => this.rows.set(rows),
      error: (error: HttpErrorResponse) => {
        this.errorMessage.set(apiErrorMessage(error, 'The entity list could not be loaded.'));
        this.rows.set([]);
      }
    });
  }

  protected changeRelationFilter(key: string): void {
    this.relationFilterKey.set(key);
    this.relationFilterValue.set('');
    this.relationChoices.set([]);
    const relation = this.config?.relations.find(item => item.key === key);
    if (!relation) return;
    this.filterLoading.set(true);
    this.data.getList(relation.target).pipe(
      finalize(() => this.filterLoading.set(false))
    ).subscribe({
      next: choices => this.relationChoices.set(choices.sort((a, b) => a.label.localeCompare(b.label))),
      error: (error: HttpErrorResponse) => {
        this.errorMessage.set(apiErrorMessage(error, 'Relation filter options could not be loaded.'));
      }
    });
  }

  protected deleteEntity(row: EntityRow): void {
    const config = this.config;
    if (!config || this.isReadOnly() || !window.confirm(`Delete "${this.displayName(row.item.label)}"?`)) return;
    this.data.delete(config.kind, row.item.id).subscribe({
      next: () => this.load(),
      error: (error: HttpErrorResponse) => {
        this.errorMessage.set(apiErrorMessage(error, 'The entity could not be deleted.'));
      }
    });
  }

  protected detailLink(id: string): string[] {
    return ['/dashboard', this.config?.slug ?? '', id];
  }

  protected editLink(id: string): string[] {
    return ['/dashboard', this.config?.slug ?? '', id, 'edit'];
  }

  // Disambiguate choices that share the same display name by appending the identifier.
  protected choiceLabel(choice: EntityListItem): string {
    const name = this.displayName(choice.label);
    const duplicates = this.relationChoices().filter(item => this.displayName(item.label) === name);
    return duplicates.length > 1 ? `${name} (${this.displayName(choice.id)})` : name;
  }
}
