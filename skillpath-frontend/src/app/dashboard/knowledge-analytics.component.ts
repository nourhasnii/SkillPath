import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, OnInit, signal } from '@angular/core';
import { finalize } from 'rxjs';

import {
  DistributionChartComponent,
  DistributionSegment
} from '../career/charts/distribution-chart.component';
import {
  AnalyticsSegment,
  apiErrorMessage,
  DashboardAnalytics,
  DashboardDataService
} from './dashboard-data.service';

/**
 * Single shared palette: brand violet plus complementary neutrals.
 * The same colours are reused by every chart so the section stays coherent.
 */
const CHART_COLORS = ['#5B4FE9', '#8B83EF', '#22C55E', '#F97316', '#0EA5E9', '#94A3B8'];

/**
 * Knowledge Analytics — distributions and category comparisons computed from the
 * real RDF individuals stored in Fuseki. Nothing here is estimated: an empty
 * series renders an empty state instead of a fabricated value.
 */
@Component({
  selector: 'sp-knowledge-analytics',
  standalone: true,
  imports: [DistributionChartComponent],
  templateUrl: './knowledge-analytics.component.html',
  styleUrl: './knowledge-analytics.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class KnowledgeAnalyticsComponent implements OnInit {
  private readonly data = inject(DashboardDataService);

  protected readonly analytics = signal<DashboardAnalytics | null>(null);
  protected readonly loading = signal(true);
  protected readonly loaded = signal(false);
  protected readonly errorMessage = signal('');

  protected readonly competencySegments = computed(() =>
    this.toSegments(this.analytics()?.competencyDistribution ?? [])
  );
  protected readonly profileSegments = computed(() =>
    this.toSegments(this.analytics()?.profilesDistribution ?? [])
  );
  protected readonly trainingSegments = computed(() =>
    this.toSegments(this.analytics()?.trainingsDistribution ?? [])
  );
  protected readonly repositorySegments = computed(() =>
    this.toSegments(this.analytics()?.repositoryOverview ?? [])
  );

  protected readonly occupationFamilies = computed<AnalyticsSegment[]>(
    () => this.analytics()?.occupationsByFamily ?? []
  );

  protected readonly competencyLabel = computed(() =>
    this.describeSeries('Competency distribution', this.competencySegments())
  );
  protected readonly profileLabel = computed(() =>
    this.describeSeries('Profile distribution', this.profileSegments())
  );
  protected readonly trainingLabel = computed(() =>
    this.describeSeries('Training distribution', this.trainingSegments())
  );

  /** Largest count of a series, used to scale the horizontal bars. */
  protected readonly occupationPeak = computed(() =>
    this.peak(this.occupationFamilies().map(family => family.count))
  );
  protected readonly repositoryPeak = computed(() =>
    this.peak(this.repositorySegments().map(segment => segment.value))
  );

  ngOnInit(): void {
    this.refresh();
  }

  protected refresh(): void {
    this.loading.set(true);
    this.errorMessage.set('');
    this.data.getDashboardAnalytics().pipe(
      finalize(() => this.loading.set(false))
    ).subscribe({
      next: analytics => {
        this.analytics.set(analytics);
        this.loaded.set(true);
      },
      error: (error: HttpErrorResponse) => {
        this.errorMessage.set(apiErrorMessage(error, 'Knowledge analytics could not be loaded.'));
        this.analytics.set(null);
        this.loaded.set(true);
      }
    });
  }

  protected barWidth(count: number, peak: number): number {
    if (peak <= 0) return 0;
    return Math.max(Math.round((count / peak) * 100), 2);
  }

  protected describe(label: string, count: number, noun: string): string {
    return `${label}: ${count} ${noun}`;
  }

  private toSegments(rows: AnalyticsSegment[]): DistributionSegment[] {
    return rows.map((row, index) => ({
      key: row.key,
      label: row.label,
      value: row.count,
      color: CHART_COLORS[index % CHART_COLORS.length]
    }));
  }

  private peak(values: readonly number[]): number {
    return values.reduce((max, value) => Math.max(max, value), 0);
  }

  private describeSeries(title: string, segments: DistributionSegment[]): string {
    const total = segments.reduce((sum, segment) => sum + segment.value, 0);
    if (!total) return `${title}: no data.`;
    const detail = segments.map(segment => `${segment.label} ${segment.value}`).join(', ');
    return `${title}: ${total} total (${detail}).`;
  }
}
