import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { finalize } from 'rxjs';
import { apiErrorMessage, DashboardDataService, SharedCompetency } from './dashboard-data.service';

@Component({
  selector: 'app-shared-competencies',
  standalone: true,
  templateUrl: './shared-competencies.component.html',
  styleUrl: './shared-competencies.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class SharedCompetenciesComponent implements OnInit {
  private readonly data = inject(DashboardDataService);

  protected readonly competencies = signal<SharedCompetency[]>([]);
  protected readonly totalCompetencies = signal(0);
  protected readonly loaded = signal(false);
  protected readonly loading = signal(true);
  protected readonly errorMessage = signal('');

  ngOnInit(): void {
    this.refresh();
  }

  protected refresh(): void {
    this.loading.set(true);
    this.errorMessage.set('');
    this.data.getSharedCompetencies().pipe(
      finalize(() => this.loading.set(false))
    ).subscribe({
      next: report => {
        this.competencies.set(report.competencies);
        this.totalCompetencies.set(report.total_competencies);
        this.loaded.set(true);
      },
      error: (error: HttpErrorResponse) => {
        this.errorMessage.set(apiErrorMessage(error, 'Impossible de charger cette analyse.'));
        this.competencies.set([]);
        this.totalCompetencies.set(0);
        this.loaded.set(true);
      }
    });
  }
}
