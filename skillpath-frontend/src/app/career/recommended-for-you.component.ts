import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { apiErrorMessage } from '../dashboard/dashboard-data.service';
import { CareerService, SkillRecommendation } from './career.service';

@Component({
  selector: 'sp-recommended-for-you',
  standalone: true,
  templateUrl: './recommended-for-you.component.html',
  styleUrl: './recommended-for-you.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class RecommendedForYouComponent implements OnInit {
  private readonly career = inject(CareerService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly loading = signal(true);
  protected readonly error = signal('');
  protected readonly recommendations = signal<SkillRecommendation[]>([]);

  ngOnInit(): void {
    this.career.getRecommendations()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: recommendations => {
          this.recommendations.set(recommendations);
          this.loading.set(false);
        },
        error: error => {
          this.error.set(apiErrorMessage(
            error,
            'Recommendations could not be loaded. Check that the backend and Fuseki are running, then try again.'
          ));
          this.loading.set(false);
        }
      });
  }
}
