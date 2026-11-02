import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { finalize } from 'rxjs';
import {
  apiErrorMessage,
  DashboardDataService,
  UntaughtCompetency
} from './dashboard-data.service';

@Component({
  selector: 'app-untaught-competencies',
  standalone: true,
  templateUrl: './untaught-competencies.component.html',
  styleUrl: './untaught-competencies.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class UntaughtCompetenciesComponent implements OnInit {
  private readonly data = inject(DashboardDataService);

  protected readonly competencies = signal<UntaughtCompetency[]>([]);
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
    this.data.getUntaughtCompetencies().pipe(
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
