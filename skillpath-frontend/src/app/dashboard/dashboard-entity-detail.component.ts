import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { EMPTY } from 'rxjs';
import { catchError, distinctUntilChanged, finalize, map, switchMap } from 'rxjs/operators';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  apiErrorMessage,
  configForKind,
  configForSlug,
  DashboardDataService,
  displayEntityName,
  EntityConfig,
  EntityDetail,
  RelatedEntity
} from './dashboard-data.service';

@Component({
  selector: 'app-dashboard-entity-detail',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './dashboard-entity-detail.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DashboardEntityDetailComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly data = inject(DashboardDataService);
  private readonly destroyRef = inject(DestroyRef);

  protected config?: EntityConfig;
  protected identifier = '';
  protected readonly detail = signal<EntityDetail | null>(null);
  protected readonly loading = signal(true);
  protected readonly errorMessage = signal('');
  protected readonly displayName = displayEntityName;
  protected readonly propertyEntries = computed(() => {
    const detail = this.detail();
    if (!detail) return [];
    return Object.entries(detail.properties).map(([key, values]) => ({
      key,
      label: this.config?.properties.find(property => property.key === key)?.label ?? this.humanize(key),
      values
    }));
  });

  ngOnInit(): void {
    this.route.paramMap.pipe(
      map(params => ({
        slug: params.get('type'),
        id: params.get('id') ?? ''
      })),
      distinctUntilChanged((previous, current) =>
        previous.slug === current.slug && previous.id === current.id
      ),
      switchMap(({ slug, id }) => {
        this.config = configForSlug(slug);
        this.identifier = id;
        this.detail.set(null);
        this.errorMessage.set('');
        if (!this.config || !id) {
          this.errorMessage.set('This entity could not be found.');
          this.loading.set(false);
          return EMPTY;
        }
        this.loading.set(true);
        return this.data.getDetail(this.config.kind, id).pipe(
          catchError((error: HttpErrorResponse) => {
            this.errorMessage.set(
              apiErrorMessage(error, 'The entity details could not be loaded.')
            );
            return EMPTY;
          }),
          finalize(() => this.loading.set(false))
        );
      }),
      takeUntilDestroyed(this.destroyRef)
    ).subscribe(detail => this.detail.set(detail));
  }
  protected relationItems(key: string): RelatedEntity[] {
    return this.detail()?.relations[key] ?? [];
  }

  // Disambiguate linked entities that share the same display name by appending the identifier.
  protected relationLabel(key: string, item: RelatedEntity): string {
    const name = this.displayName(item.label);
    const duplicates = this.relationItems(key).filter(entry => this.displayName(entry.label) === name);
    return duplicates.length > 1 ? `${name} (${this.displayName(item.id)})` : name;
  }

  protected relationLink(targetKind: EntityConfig['kind'], id: string): string[] {
    const target = configForKind(targetKind);
    return target ? ['/dashboard', target.slug, id] : ['/dashboard'];
  }

  protected editLink(): string[] {
    return ['/dashboard', this.config?.slug ?? '', this.identifier, 'edit'];
  }

  protected backLink(): string[] {
    return ['/dashboard', this.config?.slug ?? ''];
  }

  protected deleteEntity(): void {
    const config = this.config;
    if (!config || !window.confirm(`Delete "${this.displayName(this.detail()?.label ?? this.identifier)}"?`)) return;
    this.data.delete(config.kind, this.identifier).subscribe({
      next: () => void this.router.navigate(['/dashboard', config.slug]),
      error: (error: HttpErrorResponse) => {
        this.errorMessage.set(apiErrorMessage(error, 'The entity could not be deleted.'));
      }
    });
  }

  protected humanize(value: string): string {
    return value.replace(/([a-z])([A-Z])/g, '$1 $2').replace(/^a(?=[A-Z])/, '').trim();
  }

}
