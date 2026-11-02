import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { finalize } from 'rxjs';
import { friendlyAuthError } from '../auth/auth.service';
import {
  DashboardDataService,
  displayEntityName,
  RedundantCompetencyPair
} from './dashboard-data.service';

const THRESHOLD_OPTIONS = [0.6, 0.7, 0.75, 0.85, 0.95];

@Component({
  selector: 'app-redundant-competencies',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './redundant-competencies.component.html',
  styleUrl: './redundant-competencies.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class RedundantCompetenciesComponent implements OnInit {
  private readonly data = inject(DashboardDataService);

  protected readonly pairs = signal<RedundantCompetencyPair[]>([]);
  protected readonly loading = signal(true);
  protected readonly errorMessage = signal('');
  protected readonly search = signal('');
  protected readonly threshold = signal(0.75);
  protected readonly appliedThreshold = signal(0.75);
  protected readonly classFilter = signal('');
  protected readonly totalCompetencies = signal(0);
  protected readonly thresholdOptions = THRESHOLD_OPTIONS;
  protected readonly displayName = displayEntityName;

  protected readonly classOptions = computed(() =>
    [...new Set(this.pairs().flatMap(pair => [pair.class_a, pair.class_b]))].sort()
  );

  protected readonly filteredPairs = computed(() => {
    const query = this.search().trim().toLowerCase();
    const className = this.classFilter();
    return this.pairs()
      .filter(pair => !className || pair.class_a === className || pair.class_b === className)
      .filter(pair => !query
        || pair.name_a.toLowerCase().includes(query)
        || pair.id_a.toLowerCase().includes(query)
        || pair.name_b.toLowerCase().includes(query)
        || pair.id_b.toLowerCase().includes(query));
  });

  ngOnInit(): void {
    this.scan();
  }

  protected scan(): void {
    const threshold = this.threshold();
    this.loading.set(true);
    this.errorMessage.set('');
    this.data.getRedundantCompetencies(threshold).pipe(
      finalize(() => this.loading.set(false))
    ).subscribe({
      next: report => {
        this.pairs.set(report.pairs);
        this.totalCompetencies.set(report.total_competencies);
        this.appliedThreshold.set(report.threshold);
      },
      error: (error: HttpErrorResponse) => {
        this.errorMessage.set(
          friendlyAuthError(error, 'The redundancy scan could not be completed.')
        );
        this.pairs.set([]);
        this.totalCompetencies.set(0);
      }
    });
  }

  protected setThreshold(value: number | string): void {
    const parsed = typeof value === 'number' ? value : Number.parseFloat(value);
    if (Number.isFinite(parsed)) {
      this.threshold.set(Math.min(1, Math.max(0, parsed)));
      this.scan();
    }
  }

  protected scorePercent(score: number): number {
    return Math.round(score * 100);
  }
}
