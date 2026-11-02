import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { SharedCompetenciesComponent } from './shared-competencies.component';
import { DashboardDataService, SharedCompetenciesReport } from './dashboard-data.service';

const report: SharedCompetenciesReport = {
  total_competencies: 1,
  competencies: [{
    id: 'comp_Python',
    name: 'Python',
    occupation_count: 2,
    occupations: [
      { id: 'met_DataEngineer', name: 'Data Engineer' },
      { id: 'met_BackendDeveloper', name: 'Backend Developer' }
    ]
  }]
};

async function setup(getSharedCompetencies: ReturnType<typeof vi.fn>) {
  await TestBed.configureTestingModule({
    imports: [SharedCompetenciesComponent],
    providers: [{ provide: DashboardDataService, useValue: { getSharedCompetencies } }]
  }).compileComponents();

  const fixture = TestBed.createComponent(SharedCompetenciesComponent);
  fixture.detectChanges();
  return fixture;
}

describe('SharedCompetenciesComponent', () => {
  it('renders the competency and its occupations and supports refresh', async () => {
    const getSharedCompetencies = vi.fn(() => of(report));
    const fixture = await setup(getSharedCompetencies);

    expect(fixture.nativeElement.textContent).toContain('Python');
    expect(fixture.nativeElement.textContent).toContain('2');
    expect(fixture.nativeElement.textContent).toContain('Backend Developer');
    expect(fixture.nativeElement.querySelectorAll('tbody tr').length).toBe(1);

    fixture.nativeElement.querySelector('button').click();
    fixture.detectChanges();
    expect(getSharedCompetencies).toHaveBeenCalledTimes(2);
  });

  it('shows empty and error states', async () => {
    const getSharedCompetencies = vi.fn()
      .mockReturnValueOnce(of({ total_competencies: 0, competencies: [] }))
      .mockReturnValueOnce(throwError(() => new HttpErrorResponse({
        status: 502,
        error: { detail: 'Fuseki indisponible.' }
      })));
    const fixture = await setup(getSharedCompetencies);

    expect(fixture.nativeElement.textContent).toContain('Aucune compétence partagée');
    fixture.nativeElement.querySelector('button').click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]')?.textContent)
      .toContain('Fuseki indisponible.');
  });
});
