import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { DashboardAnalytics, DashboardDataService } from './dashboard-data.service';
import { KnowledgeAnalyticsComponent } from './knowledge-analytics.component';

const analytics: DashboardAnalytics = {
  competencyDistribution: [
    { key: 'CompetenceTechnique', label: 'Technical competencies', count: 4 },
    { key: 'CompetenceTransverse', label: 'Transversal competencies', count: 2 }
  ],
  occupationsByFamily: [
    { key: 'FamilleIT', label: 'Famille IT', count: 3 },
    { key: '__unassigned__', label: 'No family declared', count: 1 }
  ],
  profilesDistribution: [{ key: 'ProfilEtudiant', label: 'Students', count: 2 }],
  trainingsDistribution: [{ key: 'FormationEnLigne', label: 'Online trainings', count: 3 }],
  repositoryOverview: [{ key: 'Competence', label: 'Competencies', count: 6 }]
};

async function setup(getDashboardAnalytics: ReturnType<typeof vi.fn>) {
  await TestBed.configureTestingModule({
    imports: [KnowledgeAnalyticsComponent],
    providers: [{ provide: DashboardDataService, useValue: { getDashboardAnalytics } }]
  }).compileComponents();

  const fixture = TestBed.createComponent(KnowledgeAnalyticsComponent);
  fixture.detectChanges();
  return fixture;
}

describe('KnowledgeAnalyticsComponent', () => {
  it('renders every distribution from the ontology counts', async () => {
    const getDashboardAnalytics = vi.fn(() => of(analytics));
    const fixture = await setup(getDashboardAnalytics);

    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Technical competencies');
    expect(text).toContain('Transversal competencies');
    expect(text).toContain('Famille IT');
    expect(text).toContain('Online trainings');
    expect(text).toContain('Students');

    // Three donuts (competencies, profiles, trainings) and three bar rows
    // (two families plus the unassigned bucket, then the repository overview).
    expect(fixture.nativeElement.querySelectorAll('sp-distribution-chart').length).toBe(3);
    expect(fixture.nativeElement.querySelectorAll('.bar-row').length).toBe(3);
  });

  it('shows an empty state per chart when the repository has no individual', async () => {
    const getDashboardAnalytics = vi.fn(() => of({
      competencyDistribution: [],
      occupationsByFamily: [],
      profilesDistribution: [],
      trainingsDistribution: [],
      repositoryOverview: []
    }));
    const fixture = await setup(getDashboardAnalytics);

    expect(fixture.nativeElement.querySelectorAll('.chart-empty').length).toBe(5);
  });

  it('surfaces a retryable error instead of fabricated values', async () => {
    const getDashboardAnalytics = vi.fn()
      .mockReturnValueOnce(throwError(() => new HttpErrorResponse({
        status: 502,
        error: { detail: 'Fuseki indisponible.' }
      })))
      .mockReturnValueOnce(of(analytics));
    const fixture = await setup(getDashboardAnalytics);

    expect(fixture.nativeElement.querySelector('[role="alert"]')?.textContent)
      .toContain('Fuseki indisponible.');
    expect(fixture.nativeElement.querySelectorAll('sp-distribution-chart').length).toBe(0);

    const buttons = Array.from(fixture.nativeElement.querySelectorAll('button')) as HTMLButtonElement[];
    buttons.at(-1)?.click();
    fixture.detectChanges();

    expect(getDashboardAnalytics).toHaveBeenCalledTimes(2);
    expect(fixture.nativeElement.textContent).toContain('Technical competencies');
  });
});
