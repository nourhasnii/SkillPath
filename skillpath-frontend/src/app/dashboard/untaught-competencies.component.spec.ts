import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { UntaughtCompetenciesComponent } from './untaught-competencies.component';
import { DashboardDataService, UntaughtCompetenciesReport } from './dashboard-data.service';

const report: UntaughtCompetenciesReport = {
  total_competencies: 1,
  competencies: [{
    id: 'comp_Communication',
    name: 'Communication',
    class: 'CompetenceTransverse'
  }]
};

async function setup(getUntaughtCompetencies: ReturnType<typeof vi.fn>) {
  await TestBed.configureTestingModule({
    imports: [UntaughtCompetenciesComponent],
    providers: [{ provide: DashboardDataService, useValue: { getUntaughtCompetencies } }]
  }).compileComponents();

  const fixture = TestBed.createComponent(UntaughtCompetenciesComponent);
  fixture.detectChanges();
  return fixture;
}

describe('UntaughtCompetenciesComponent', () => {
  it('renders each uncovered competency and supports refresh', async () => {
    const getUntaughtCompetencies = vi.fn(() => of(report));
    const fixture = await setup(getUntaughtCompetencies);

    expect(fixture.nativeElement.textContent).toContain('Communication');
    expect(fixture.nativeElement.textContent).toContain('CompetenceTransverse');
    expect(fixture.nativeElement.querySelectorAll('tbody tr').length).toBe(1);

    fixture.nativeElement.querySelector('button').click();
    fixture.detectChanges();
    expect(getUntaughtCompetencies).toHaveBeenCalledTimes(2);
  });

  it('shows empty and error states', async () => {
    const getUntaughtCompetencies = vi.fn()
      .mockReturnValueOnce(of({ total_competencies: 0, competencies: [] }))
      .mockReturnValueOnce(throwError(() => new HttpErrorResponse({
        status: 502,
        error: { detail: 'Fuseki indisponible.' }
      })));
    const fixture = await setup(getUntaughtCompetencies);

    expect(fixture.nativeElement.textContent).toContain('Toutes les compétences sont enseignées');
    fixture.nativeElement.querySelector('button').click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]')?.textContent)
      .toContain('Fuseki indisponible.');
  });
});
